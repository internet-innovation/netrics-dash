from __future__ import annotations
import datetime
import enum
import io
import sys
from collections.abc import Iterable
from functools import cached_property
from typing import Self, Generator

import s3path
import valkey

from app import conf
from app.lib.abstract import abstractmember
from app.lib.cache import FileSystemCache, MemoryCache, SimpleCache

try:
    s3path_internals = s3path.current_version
except AttributeError:
    s3path_internals = s3path.old_versions


S3Key = str | s3path.S3Path


class S3CacheNS(enum.IntEnum):

    LIST = 0
    GET = 1


class ValKeyCache(SimpleCache):

    ns: S3CacheNS = abstractmember()

    def __init__(self, url: str) -> None:
        super().__init__()
        self._client_ = valkey.from_url(url, decode_responses=True)

    @cached_property
    def db(self) -> int | None:
        return self._client_.get_connection_kwargs().get('db')

    def _nskey_(self, key: S3Key) -> str:
        return f'{self.ns}:{key}' if self.db is None else str(key)

    def discard(self, key: S3Key) -> None:
        self._client_.delete(self._nskey_(key))


class S3ListCacheValKey(ValKeyCache):

    ns = S3CacheNS.LIST
    ttl = datetime.timedelta(hours=2)

    def get(self, key: S3Key) -> set[CachingS3Path] | None:
        cached = self._client_.smembers(self._nskey_(key))

        if cached:
            self.hits += 1
            return {CachingS3Path(value) for value in cached if value != ''}
        else:
            self.misses += 1
            return None

    def set(self, key: S3Key, values: Iterable[S3Key]) -> bool:
        nskey = self._nskey_(key)
        prepped = [str(value) for value in values] or ['']
        (count, _expire) = (
            self._client_.pipeline(transaction=True)
            .sadd(nskey, *prepped)
            .expire(nskey, self.ttl)
        ).execute()
        return bool(count)


class S3GetCacheValKey(ValKeyCache):

    ns = S3CacheNS.GET
    ttl = datetime.timedelta(weeks=2)

    def get(self, key: S3Key, decode=True) -> io.StringIO | None:
        if not decode:
            raise NotImplementedError("bytes not supported")

        value = self._client_.getex(self._nskey_(key), ex=self.ttl)

        if value is None:
            self.misses += 1
            return value
        else:
            self.hits += 1
            return io.StringIO(value)

    def set(self, key: S3Key, value: str | bytes) -> bool:
        return self._client_.set(self._nskey_(key), value, ex=self.ttl)


match conf.DATAFILE_S3_CACHE_BACKEND:
    case 'local':
        S3_LIST_CACHE = MemoryCache()
        S3_GET_CACHE = FileSystemCache(conf.DATAFILE_S3_CACHE_PATH)

    case 'remote':
        if not conf.DATAFILE_S3_CACHE_REMOTE:
            raise ValueError("setting DATAFILE_S3_CACHE_BACKEND=remote requires that setting "
                             "DATAFILE_S3_CACHE_REMOTE is not empty")

        S3_LIST_CACHE = S3ListCacheValKey(conf.DATAFILE_S3_CACHE_REMOTE)
        S3_GET_CACHE = S3GetCacheValKey(conf.DATAFILE_S3_CACHE_REMOTE)

    case _:
        raise ValueError(f"setting DATAFILE_S3_CACHE_BACKEND expects either "
                         f"'local' or 'remote' not: {conf.DATAFILE_S3_CACHE_BACKEND!r}")


class CachingS3PathSelector(s3path_internals._Selector):

    _list_cache_ = S3_LIST_CACHE

    def select(self):
        if self._full_keys:
            raise NotImplementedError("only directory listings currently supported")

        for path in self._caching_dir_scan():
            if self.match(str(path)):
                yield path

    def _caching_dir_scan(self):
        paths = self._list_cache_.get(self._path)
        if paths is not None:
            yield self._path
            yield from paths
            return

        paths = []
        for target in self._deep_cached_dir_scan():
            path = type(self._path)(f'{self._path.parser.sep}{self._path.bucket}{target}')
            if path != self._path:
                paths.append(path)
            yield path

        self._list_cache_.set(self._path, paths)


class CachingS3Path(s3path.S3Path):

    _list_cache_ = S3_LIST_CACHE

    _get_cache_ = S3_GET_CACHE

    def glob(self,
             pattern: str, *,
             cache: bool = False,
             case_sensitive: bool | None = None,
             recurse_symlinks: bool = False) -> Generator[Self]:
        if not cache:
            yield from super().glob(pattern,
                                    case_sensitive=case_sensitive,
                                    recurse_symlinks=recurse_symlinks)
            return

        #
        # taken from s3path
        #
        self._absolute_path_validation()
        if case_sensitive is False or recurse_symlinks is True:
            raise ValueError('Glob is case-sensitive and no symbolic links are allowed')

        sys.audit("pathlib.Path.glob", self, pattern)
        if not pattern:
            raise ValueError(f'Unacceptable pattern: {pattern}')
        drv, root, pattern_parts = self._parse_path(pattern)
        if drv or root:
            raise NotImplementedError("Non-relative patterns are unsupported")
        for part in pattern_parts:
            if part != '**' and '**' in part:
                raise ValueError("Invalid pattern: '**' can only be an entire path component")
        selector = CachingS3PathSelector(self, pattern=pattern)
        yield from selector.select()

    def iterdir(self, cache=False):
        if not cache:
            yield from super().iterdir()
            return

        result = self._list_cache_.get(self)
        if result is not None:
            yield from result
            return

        result = []
        for item in super().iterdir():
            result.append(item)
            yield item

        self._list_cache_.set(self, result)

    def open(self, mode='r', *args, cache=False, **kwargs):
        if not cache:
            return super().open(mode, *args, **kwargs)

        if 'w' in mode:
            self._get_cache_.discard(self)
            return super().open(mode, *args, **kwargs)

        cached = self._get_cache_.get(self, decode=('b' not in mode))

        if cached is None:
            with super().open(mode) as fd:
                contents = fd.read()

            self._get_cache_.set(self, contents)

            return io.BytesIO(contents) if 'b' in mode else io.StringIO(contents)

        return cached
