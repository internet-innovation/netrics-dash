import abc
import pathlib

from loguru import logger as log


class SimpleCache(abc.ABC):

    def __init__(self) -> None:
        self.hits = self.misses = 0

    @abc.abstractmethod
    def get(self, key: object) -> object:
        pass

    @abc.abstractmethod
    def set(self, key: object, value: object) -> bool:
        pass

    @abc.abstractmethod
    def discard(self, key: object) -> None:
        pass


class MemoryCache(SimpleCache):

    def __init__(self) -> None:
        super().__init__()
        self._cache_ = {}

    def get(self, key: object) -> object:
        result = self._cache_.get(key)

        if result is None:
            self.misses += 1
        else:
            self.hits += 1

        return result

    def set(self, key: object, value: object) -> bool:
        self._cache_[key] = value
        return True

    def discard(self, key: object) -> None:
        self._cache_.pop(key, None)


class FileSystemCache(SimpleCache):

    def __init__(self, cache_dir: str | pathlib.PurePath) -> None:
        super().__init__()
        self._cache_dir_ = pathlib.Path(cache_dir)

    def _get_path_(self, key: pathlib.PurePath) -> pathlib.Path:
        return self._cache_dir_ / key.relative_to(key.root)

    def discard(self, key: pathlib.PurePath) -> None:
        self._get_path_(key).unlink(missing_ok=True)

    def get(self, key: pathlib.PurePath) -> pathlib.Path | None:
        path = self._get_path_(key)

        if path.exists():
            self.hits += 1
            return path

        self.misses += 1
        return None

    def set(self, key: pathlib.PurePath, value: str | bytes) -> bool:
        key_path = self._get_path_(key)
        key_dir = key_path.parent

        try:
            key_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            log.error("failed to create cache directory: {}", key_dir)
            return False

        if isinstance(value, bytes):
            key_path.write_bytes(value)
        else:
            key_path.write_text(value)

        return True
