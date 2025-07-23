"""Backend to Netrics data files stored in S3."""
import collections
import concurrent.futures
import datetime
import functools
import itertools
import json
import os.path
import re

import boto3
import botocore
import s3path
from loguru import logger as log

from app import conf
from app.lib.log import log_enum

from ..base import AbstractDataFileBank

from .caching import CachingS3Path


DATAFILE_LIMIT = 50_000

DATE_PATTERN = '[0-9]' * 8

_RE = re.compile

FILE_PATTERNS = (
    # (key_pattern, file_pattern),
    (_RE(r'^ping_latency\.'), _RE(r'^result-.+-ping.json$')),
    (_RE(r'^ookla\.'), _RE(r'^result-.+-ookla(?:-metadata)?.json$')),
    (_RE(r'^ndt7\.'), _RE(r'^result-.+-ndt7(?:-metadata)?.json$')),
)

MAX_POOL_CONNECTIONS = MAX_WORKERS = 30

MAX_WORKERS_LIST = int(0.67 * MAX_WORKERS)

MAX_WORKERS_GET = MAX_WORKERS - MAX_WORKERS_LIST

BOTO_CONFIG = botocore.config.Config(max_pool_connections=MAX_POOL_CONNECTIONS)

#
# increase urllib connection pool size
#
s3path.register_configuration_parameter(
    s3path.PureS3Path('/'),
    resource=boto3.resource('s3', config=BOTO_CONFIG),
)

DATE_PATH_CACHEABLE_AGE = datetime.timedelta(days=2)


class S3DataFileBank(AbstractDataFileBank):

    @staticmethod
    def _check_max_workers(max_workers):
        if not isinstance(max_workers, int):
            raise TypeError(f"max_workers expects int not: {max_workers.__class__.__name__}")

        if max_workers < 1:
            raise ValueError(f"max_workers expects natural number not: {max_workers}")

    def __init__(self, *,
                 device_id,
                 max_workers_get=MAX_WORKERS_GET,
                 max_workers_list=MAX_WORKERS_LIST,
                 file_limit=DATAFILE_LIMIT,
                 **kwargs):
        if not isinstance(conf.DATAFILE_S3_BUCKET, str):
            raise TypeError("setting DATAFILE_S3_BUCKET must be str not: "
                            + conf.DATAFILE_S3_BUCKET.__class__.__name__)

        if not conf.DATAFILE_S3_BUCKET:
            raise ValueError("setting DATAFILE_S3_BUCKET must not be empty")

        if not device_id:
            raise ValueError("device_id must not be empty")

        super().__init__(file_limit=file_limit, **kwargs)

        self.device_id = device_id

        self._check_max_workers(max_workers_get)
        self._check_max_workers(max_workers_list)

        self.max_workers_get = max_workers_get
        self.max_workers_list = max_workers_list

    @functools.cached_property
    def bucket_path(_self):
        bucket_spec = (conf.DATAFILE_S3_BUCKET if conf.DATAFILE_S3_BUCKET.startswith('/')
                       else f'/{conf.DATAFILE_S3_BUCKET}')
        bucket_path = CachingS3Path(bucket_spec)
        return bucket_path / conf.DATAFILE_S3_BASE.lstrip('/')

    @functools.cached_property
    def ignored_paths(self):
        return {self.bucket_path / ignored.lstrip('/') for ignored in conf.DATAFILE_S3_IGNORE}

    def prefilter_ignored(self, paths):
        for path in paths:
            if path not in self.ignored_paths:
                yield path

    def get_points(self, *ops, **named_ops):
        # note: wrapped for debug purposes only
        results = super().get_points(*ops, **named_ops)
        log.debug('listing cache hits={0.hits} misses={0.misses}', CachingS3Path._list_cache_)
        log.debug('get cache hits={0.hits} misses={0.misses}', CachingS3Path._get_cache_)
        return results

    def iter_datasets(self, keys=()):
        # note: wrapped for debug purposes only
        yield from log_enum(super().iter_datasets(keys), 'datasets')

    def iter_datablobs(self, keys=(), max_workers=None):
        if max_workers is None:
            max_workers = self.max_workers_get

        self._check_max_workers(max_workers)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # we don't know how many blobs the receiver will need;
            # but requesting them one at a time is too slow.
            #
            # instead, we'll "read ahead", requesting blobs concurrently,
            # and reading further for each blob that's received (sent).
            #
            paths = self.iter_paths(keys)

            futures = collections.deque(
                executor.submit(self.get_datablob, path)
                for path in itertools.islice(paths, int(1.5 * max_workers))
            )

            while futures:
                # wait on result of first/oldest request
                future0 = futures.popleft()
                data = future0.result()

                # add another request to the queue
                try:
                    path = next(paths)
                except StopIteration:
                    pass
                else:
                    future1 = executor.submit(self.get_datablob, path)
                    futures.append(future1)

                # send result
                if data is not None:
                    yield data

    @classmethod
    def get_datablob(cls, path):
        try:
            return cls.get_json(path)
        except cls.DATA_FILE_READ_ERRORS:
            return None

    @staticmethod
    def get_json(path):
        with path.open(cache=True) as fd:
            return json.load(fd)

    def iter_paths(self, keys=()):
        """Generate data file paths in descending order.

        Paths are excluded according to the provision of `keys` and any
        matching `FILE_PATTERNS`.

        Paths will not be generated beyond the file limit specified upon
        instantiation.

        """
        # slice sorted paths to limit
        paths = itertools.islice(self._iter_paths_all_(), self.file_limit)

        # exclude non-matching paths
        file_patterns = set()
        for key in keys:
            for (key_pattern, file_pattern) in FILE_PATTERNS:
                if key_pattern.search(key):
                    file_patterns.add(file_pattern)
                    break
            else:
                log.warning('inspecting every data file in sequence '
                            'as no file pattern matches key {!r}', key)
                file_patterns.clear()
                break

        if file_patterns:
            log.debug('datapaths | filtering to files matching: {}',
                      ', '.join(file_pattern.pattern for file_pattern in file_patterns))

            paths = log_enum(paths, 'datapaths', 2)

            paths = (path for path in paths
                     if any(file_pattern.search(path.name) for file_pattern in file_patterns))
            paths = log_enum(paths, 'datapaths>filtered')
        else:
            paths = log_enum(paths, 'datapaths')

        yield from paths

    def _iter_paths_all_(self):
        """Generate data file paths in descending order."""
        data_dirs = self._list_concurrent(
            self._s3_search_experiment,
            self.prefilter_ignored(self.bucket_path.iterdir(cache=True)),
        )
        data_dirs.sort(
            key=os.path.basename,
            reverse=True,
        )

        for (_date, paths) in itertools.groupby(data_dirs, os.path.basename):
            data_files = self._list_concurrent(
                self._s3_search_date,
                paths,
            )
            data_files.sort(
                key=os.path.basename,
                reverse=True,
            )

            yield from data_files

    def _s3_search_experiment(self, experiment_path):
        return self._list_concurrent(
            self._s3_search_topic,
            self.prefilter_ignored(experiment_path.iterdir(cache=True)),
        )

    def _s3_search_topic(self, topic_path):
        return self._list_concurrent(
            self._s3_search_device,
            topic_path.glob(f'*-{self.device_id}', cache=True),
        )

    @staticmethod
    def _s3_search_device(device_path):
        return [*device_path.glob(DATE_PATTERN)]

    @staticmethod
    def _s3_search_date(date_path):
        path_date = datetime.date.fromisoformat(date_path.name)
        path_age = datetime.date.today() - path_date
        cacheable = path_age >= DATE_PATH_CACHEABLE_AGE

        data_path = date_path / 'json'
        return [*data_path.iterdir(cache=cacheable)]

    def _list_concurrent(self, func, it, *args, max_workers=None, **kwargs):
        if max_workers is None:
            max_workers = self.max_workers_list

        self._check_max_workers(max_workers)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(func, item, *args, **kwargs)
                for item in it
            ]

            return [
                item
                for future in concurrent.futures.as_completed(futures)
                for item in future.result()
            ]
