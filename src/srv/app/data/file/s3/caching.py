import io
import sys
from typing import Self, Generator

import s3path

from app import conf
from app.lib.cache import FileSystemCache, MemoryCache

try:
    s3path_internals = s3path.current_version
except AttributeError:
    s3path_internals = s3path.old_versions


S3_LIST_CACHE = MemoryCache()

S3_GET_CACHE = FileSystemCache(conf.DATAFILE_S3_CACHE_PATH)


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

        cached = self._get_cache_.get(self)

        if cached is None:
            with super().open(mode) as fd:
                contents = fd.read()

            if not self._get_cache_.set(self, contents):
                return io.BytesIO(contents) if 'b' in mode else io.StringIO(contents)

            cached = self._get_cache_._get_path_(self)

        return cached.open(mode, *args, **kwargs)
