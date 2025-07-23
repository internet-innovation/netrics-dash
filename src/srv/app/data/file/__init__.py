from app import conf, route

from .base import FlatFileBank, Last, Multi, StdDev, ONE_WEEK_S  # noqa: F401
from .local import LocalDataFileBank, populate_caches  # noqa: F401
from .s3 import S3DataFileBank


match conf.DATAFILE_BACKEND:
    case 'local':
        class DataFileBank(LocalDataFileBank):
            pass

    case 's3':
        class DataFileBank(route.DeviceIDProvider, S3DataFileBank):  # noqa: F811
            pass

    case _:
        raise ValueError(f"setting DATAFILE_BACKEND expects either "
                         f"'local' or 's3' not: {conf.DATAFILE_BACKEND!r}")


class FlatDataFileBank(FlatFileBank, DataFileBank):
    pass


def get_points(*ops, **named_ops):
    file_bank = DataFileBank(round_to=1)
    return file_bank.get_points(*ops, **named_ops)
