import functools
import itertools


def is_exc(x):
    return isinstance(x, type) and issubclass(x, BaseException)


def not_exc(x):
    return not is_exc(x)


def apidefault(*keys_excs, default=None):
    keys = [*itertools.takewhile(not_exc, keys_excs)]
    excs = [*itertools.takewhile(is_exc, keys_excs[len(keys):])]

    if len(keys) + len(excs) < len(keys_excs):
        raise TypeError("unexpected signature")

    if not excs:
        raise TypeError("at least one exception class required")

    def decorator(func):
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except excs:
                # measurements (directory) not (yet) initialized
                #
                # treat this no differently than missing data points
                #
                return dict.fromkeys(keys, default)
        return wrapped
    return decorator
