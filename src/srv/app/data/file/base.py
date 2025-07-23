"""Interface to read operations on sets of Netrics data files."""
import abc
import collections
import json
import numbers
import statistics
import time

from app.lib.iteration import pairwise


DATAFILE_PREFIX = 'Measurements'

META_PREFIX = 'Meta'

DATAFILE_LIMIT = 5_000

ONE_WEEK_S = 60 * 60 * 24 * 7


def get_multikey(multikey, values):
    value = values
    for key in multikey.split('.'):
        value = value[key]
    return value


class AbstractDataFileBank(abc.ABC):
    """Interface to read operations on sets of Netrics data files."""

    DATA_FILE_READ_ERRORS = (json.JSONDecodeError, UnicodeDecodeError)

    def __init__(self,
                 *,
                 prefix=DATAFILE_PREFIX,
                 meta_prefix=META_PREFIX,
                 file_limit=DATAFILE_LIMIT,
                 round_to=None,
                 flat=False):
        self.prefix = prefix
        self.meta_prefix = meta_prefix
        self.file_limit = file_limit
        self.round_to = round_to
        self.flat = flat

    def get_points(self, *ops, **named_ops):
        op_stack = dict(((str(op), op) for op in ops), **named_ops)
        points = dict.fromkeys(op_stack)

        if self.flat and len(points) > 1:
            raise ValueError("cannot flatten multiple keys")

        read_keys = frozenset(read_key for op in op_stack.values() for read_key in op.read_keys)

        for (dataset, dataset1) in pairwise(self.iter_datasets(read_keys)):
            (data, full_data) = dataset

            for (write_key, aggregator) in tuple(op_stack.items()):
                try:
                    points[write_key] = aggregator(
                        data,
                        points[write_key],
                        {
                            'data': full_data,
                            'points': points,
                            'write_key': write_key,
                            'file_limit': self.file_limit,
                            'last': dataset1 is None,
                            'meta_prefix': self.meta_prefix,
                            'flat': self.flat,
                        },
                    )
                except aggregator.stop_reduce as stop_reduce:
                    points[write_key] = self.round_value(stop_reduce.value)
                    del op_stack[write_key]

                #
                # note: the following is left for educational purposes only
                #
                # this method originally merely retrieved the last value of the key's time series;
                # hence, the below performed the same as the current DataFileAggregator: Last
                #
                # key_data = data
                #
                # try:
                #     for key in read_key.split('.'):
                #         key_data = key_data[key]
                # except KeyError:
                #     pass
                # else:
                #     del key_stack[write_key]
                #     points[write_key] = self.round_value(key_data)

            if not op_stack:
                break

        # DEBUG: points['_path_count'] = path_count

        if self.flat:
            (points,) = points.values()

        return points

    def round_value(self, value):
        if self.round_to is not None:
            if isinstance(value, numbers.Number):
                return round(value, self.round_to)
            elif isinstance(value, list):
                return [self.round_value(value0) for value0 in value]
            elif isinstance(value, tuple):
                return tuple(self.round_value(value0) for value0 in value)
            elif isinstance(value, dict):
                return {key: self.round_value(value0) for (key, value0) in value.items()}

        return value

    def iter_datablobs(self, keys=()):
        for path in self.iter_paths(keys):
            try:
                yield self.get_json(path)
            except self.DATA_FILE_READ_ERRORS:
                continue

    def iter_datasets(self, keys=()):
        """Generate data files' datasets.

        Files with incompatible encoding or serialization are ignored.

        Data are returned as a tuple of:

          1. the data retrieved from the configured `prefix`
          2. the file's full data object

        See `iter_paths`.

        """
        for full_data in self.iter_datablobs(keys):
            if self.prefix:
                try:
                    data = get_multikey(self.prefix, full_data)
                except KeyError:
                    continue
                else:
                    yield (data, full_data)
            else:
                yield (full_data, full_data)

    @staticmethod
    def get_json(path):
        with path.open() as fd:
            return json.load(fd)

    @abc.abstractmethod
    def iter_paths(self, keys=()):
        """Generate data file paths in descending order.

        Paths will not be generated beyond the file limit specified upon
        instantiation.

        """


class FlatFileBank:

    def __init__(self, **kwargs):
        if 'flat' in kwargs:
            raise TypeError("'flat' may not be specified to FlatFileBank()")

        super().__init__(flat=True, **kwargs)

    def get_columns(self, read_key, age_s, *, decorate=None, reverse=False):
        points = self.get_points(
            Multi(read_key, age_s, decorate=decorate, reverse=reverse)
        )

        if not points:
            count = 1 if isinstance(read_key, str) else len(read_key)
            if decorate:
                count += 1 if isinstance(decorate, str) else len(decorate)

            return (None,) * count

        (data_comp, meta) = zip(*points) if decorate else (points, None)

        if isinstance(read_key, str):
            return data_comp if meta is None else (data_comp, meta)

        data = tuple(zip(*data_comp))

        return data if meta is None else data + (meta,)


class StopReduce(Exception):
    """Raised to indicate completion and to share final result."""

    def __init__(self, value):
        super().__init__(value)
        self.value = value


class ItemError(LookupError):
    """Mapped value does not satisfy "where" filter."""


def where_true(current_value):
    return True


class DataFileAggregator(abc.ABC):

    stop_reduce = StopReduce

    def __init__(self, read_key, *, decorate=None, where=where_true):
        self.read_key = read_key
        self.decorations = decorate
        self.where = where

    @property
    def read_keys(self):
        return (self.read_key,) if isinstance(self.read_key, str) else self.read_key

    def get_multikey(self, values):
        results = []

        for (key_count, read_key) in enumerate(self.read_keys, 1):
            results.append(get_multikey(read_key, values))

        return results[0] if key_count == 1 else results

    def get_uservalue(self, values):
        value = self.get_multikey(values)

        if self.where(value):
            return value

        raise ItemError(self.read_key, value)

    def decorate(self, value, context):
        if self.decorations:
            if isinstance(self.decorations, str):
                decorations = (self.decorations,)
            else:
                decorations = self.decorations

            data = context['data']
            data_meta = data[context['meta_prefix']]

            value_meta = [data_meta.get(meta_key) for meta_key in decorations]

            if context['flat']:
                value = (
                    value,
                    value_meta[0] if isinstance(self.decorations, str) else value_meta,
                )
            else:
                value = {
                    'Measurement': value,
                    'Meta': dict(zip(self.decorations, value_meta)),
                }

        return value

    def __str__(self):
        return '__'.join(self.read_keys)

    def __repr__(self):
        return "{}({})".format(
            self.__class__.__name__,
            ', '.join(f'{key}={value!r}' for (key, value) in self.__dict__.items()),
        )

    @abc.abstractmethod
    def __call__(self, current_values, current_result, context):
        pass


class Last(DataFileAggregator):

    def __call__(self, current_values, _current_result, context):
        try:
            value = self.get_uservalue(current_values)
        except LookupError:
            return None

        raise self.stop_reduce(self.decorate(value, context))


class Multi(DataFileAggregator):

    def __init__(self, read_key, age_s, *, decorate=None, reverse=False, where=where_true):
        super().__init__(read_key, decorate=decorate, where=where)
        self.age_s = age_s
        self.reverse = reverse

    def __call__(self, current_values, collected, context):
        if collected is None:
            collected = collections.deque()

        data = context['data']
        data_meta = data[context['meta_prefix']]
        timestamp = data_meta['Time']
        if time.time() - timestamp >= self.age_s:
            raise self.make_stop(collected)

        try:
            current_value = self.get_uservalue(current_values)
        except LookupError:
            pass
        else:
            decorated = self.decorate(current_value, context)

            if self.reverse:
                collected.appendleft(decorated)
            else:
                collected.append(decorated)

        if context['last']:
            raise self.make_stop(collected)

        return collected

    def make_stop(self, values):
        result = self.finalize(values)
        return self.stop_reduce(result)

    def finalize(self, values):
        return list(values)


class StdDev(Multi):

    def __init__(self, *args, **kwargs):
        if 'decorate' in kwargs:
            raise TypeError("'decorate' is an invalid keyword argument for StdDev()")

        super().__init__(*args, **kwargs)

    def finalize(self, values):
        try:
            return statistics.stdev(values)
        except statistics.StatisticsError:
            return None
