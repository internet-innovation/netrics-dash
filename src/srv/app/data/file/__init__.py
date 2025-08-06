from app import conf, route
from app.lib import error

from .base import FlatFileBank, Last, Multi, StdDev, ONE_WEEK_S  # noqa: F401


match conf.DATAFILE_BACKEND:
    case 'local':
        try:
            from .local import LocalDataFileBank, populate_caches  # noqa: F401
        except ModuleNotFoundError:
            raise error.ImplicitDependencyError.make_default("local backend")

        class DataFileBank(LocalDataFileBank):
            pass

    case 's3':
        try:
            from .s3 import S3DataFileBank
        except ModuleNotFoundError:
            raise error.ImplicitDependencyError.make_default("s3 backend")

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
