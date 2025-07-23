"""Backend to Netrics data files stored on a local filesystem."""
import contextlib
import functools
import heapq
import threading

import cachetools
from cachetools import TTLCache
from loguru import logger as log

from app import conf

from .base import AbstractDataFileBank, DATAFILE_LIMIT


DATA_PATHS = (
    ((conf.DATAFILE_PENDING,) if conf.DATAFILE_PENDING else ()) +
    ((conf.DATAFILE_ARCHIVE,) if conf.DATAFILE_ARCHIVE else ())
)

DATA_CACHE_SIZE = DATAFILE_LIMIT


def cached(cache, key=cachetools.hashkey, lock=None):
    """Extend cachetools.cached to decorate wrapper with useful
    properties & methods.

    """
    decorator = cachetools.cached(cache, key, lock)

    def wrapped_decorator(func):
        def populate(*args, **kwargs):
            cache_key = key(*args, **kwargs)
            value = func(*args, **kwargs)

            with lock or contextlib.nullcontext():
                cache[cache_key] = value

            return value

        wrapped = decorator(func)

        wrapped.cache = cache
        wrapped.key = key
        wrapped.lock = lock
        wrapped.populate = populate

        return wrapped

    return wrapped_decorator


class LocalDataFileBank(AbstractDataFileBank):

    def __init__(self, *, dirs=DATA_PATHS, **kwargs):
        super().__init__(**kwargs)
        self.dirs = dirs

    #
    # As size of file archive grows and grows, becomes increasingly important to
    # cache its sorted listing as well.
    #
    # Unlike JSON payloads, the file listing is *mutable*; therefore, cache
    # items must expire over time.
    #
    # TTL cache on full argument list should be sufficient for now -- (arguments
    # stable across all typical invocations).
    #
    @staticmethod
    @cached(TTLCache(maxsize=100, ttl=(3600 * 24)), lock=threading.Lock())
    def sorted_dir(path_dir, limit):
        return heapq.nlargest(limit, path_dir.iterdir())

    def iter_paths(self, keys=()):
        """Generate data file paths in descending order.

        Data file directories are read in their order specified upon
        instantiation. Within each directory, files are generated in
        descending order according to their path names; (in so far as
        these are consistenty labeled by timestamp, they are also
        therefore generated in descending time order).

        Paths will not be generated beyond the file limit specified upon
        instantiation.

        """
        path_count = 0

        for path_dir in self.dirs:
            path_remainder = self.file_limit - path_count

            if path_remainder <= 0:
                break

            paths_sorted = self.sorted_dir(path_dir, path_remainder)

            for (path_count, path) in enumerate(paths_sorted, 1 + path_count):
                yield path

    #
    # In testing against an HTTP endpoint whose query required ~500 files,
    # an LRU cache of the same size added a lag of ~10% to the initial request,
    # and reduced subsequent requests' time by an order of magnitude (~90%).
    #
    # However: cache size should be ensured to be at least as large as the file
    # limit, to ensure cache functionality.
    #
    @staticmethod
    @functools.lru_cache(maxsize=DATA_CACHE_SIZE)
    def get_json(path):
        return super().get_json(path)

    @classmethod
    def populate_caches(cls, file_limit=DATAFILE_LIMIT, dirs=DATA_PATHS):
        """Pre- and/or re-populate file caches."""
        log.opt(lazy=True).trace(
            'initial sizes | dirlists: {dirsize} | jsons: {jsize}',
            dirsize=lambda: cls.sorted_dir.cache.currsize,
            jsize=lambda: cls.get_json.cache_info().currsize,
        )

        path_count = 0

        for path_dir in dirs:
            # set/reset sorted_dir()
            paths_sorted = cls.sorted_dir.populate(path_dir, file_limit - path_count)

            # set/reset get_json()
            for (path_count, path) in enumerate(paths_sorted, 1 + path_count):
                try:
                    cls.get_json(path)
                except cls.DATA_FILE_READ_ERRORS:
                    pass

            if path_count == file_limit:
                break

        log.opt(lazy=True).trace(
            'final sizes | dirlists: {dirsize} | jsons: {jsize}',
            dirsize=lambda: cls.sorted_dir.cache.currsize,
            jsize=lambda: cls.get_json.cache_info().currsize,
        )


populate_caches = LocalDataFileBank.populate_caches
