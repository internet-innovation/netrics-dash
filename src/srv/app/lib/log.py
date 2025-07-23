import itertools
import time

from loguru import logger as log


class log_enum:

    @staticmethod
    def iter_checkpoints(start_power=0, /):
        # 1, 10, 100, 500, 1000, 5000, 10_000, ...
        for x in itertools.count(start_power):
            y = 10 ** x

            if x >= 3:
                yield y // 2

            yield y

    def __init__(self, iterable, tag, depth=0):
        self.iterable = iterable
        self.tag = tag

        self._check_ = 0
        self._last_check_ = 0
        self._checks_ = self.iter_checkpoints()

        self._time0_ = None

        self._log_ = log.opt(depth=(2 + depth))

    def __iter__(self):
        self._advance_check_()

        self._time0_ = time.time()

        count = 0

        for (count, item) in enumerate(self.iterable, 1):
            if count == self._check_:
                self._advance_check_()
                self._check_in_(count)

            yield item

        if count != self._last_check_:
            self._check_in_(count)

    def _advance_check_(self):
        self._last_check_ = self._check_
        self._check_ = next(self._checks_)

    def _check_in_(self, count):
        self._log_.debug('{tag} | elapsed={elapsed:.1f}s | produced={produced}',
                         tag=self.tag,
                         elapsed=(time.time() - self._time0_),
                         produced=count)
