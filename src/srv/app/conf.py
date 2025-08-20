import pathlib

from decouple import config, Csv


def path_or_none(value):
    return value if value is None else pathlib.Path(value)


#
# Development & management
#
APP_NAME = config('APP_NAME', default='dashboard')
#
#
APP_DEBUG = config('APP_DEBUG', default=False, cast=bool)
#
#
APP_PROFILE = config('APP_PROFILE', default=False, cast=bool)
#
#
APP_QUIET = config('APP_QUIET', default=False, cast=bool)
#
#
APP_RELOAD = config('APP_RELOAD', default=False, cast=bool)
#
#
APP_VERSION = config('APP_VERSION', default=None)
#
#
# BOTTLE_CHILD: identification of the reloading subprocess
#
# This environment variable is set by Bottle on the special app-reloading child
# process; (i.e., not exactly configuration, but functionally the same).
#
BOTTLE_CHILD = config('BOTTLE_CHILD', default=False, cast=bool)
#
#
LOG_LEVEL = config('APP_LOG_LEVEL', default='INFO')


#
# Address & routing
#
APP_HOST = config('APP_HOST', default='127.0.0.1')
#
#
APP_PORT = config('APP_PORT', default=8080, cast=int)
#
#
# APP_PREFIX: base URL path for app
#
# installed locally, this can be anything (even "/" or ""); traditionally: "/dashboard/"
#
# installed remotely, this should be: "/<:deviceid>/"
#
# (where deviceid is a shortcut filter equivalent to: "/<:re:[0-9a-zA-Z]{8}>/").
#
APP_PREFIX = config('APP_PREFIX', default='')
#
#
# APP_REDIRECT: redirect requests for the server's root path to any supplied APP_PREFIX
#
# this is likely desireable for local installations.
#
# for remote installations, enabling this option may cause errors.
#
APP_REDIRECT = config('APP_REDIRECT', default=False, cast=bool)
#
#
# STATIC_PREFIX: base URL path for the app's static assets
#
STATIC_PREFIX = '/static/'


#
# Resources
#
APP_PATH = pathlib.Path(__file__).absolute().parent
#
#
STATIC_PATH = APP_PATH / 'static'
#
#
ASSET_PATH = STATIC_PATH / 'asset'
#
#
SQLITE_DEFAULT = APP_PATH / 'data.sqlite'
#
#
APP_DATABASE = config('APP_DATABASE', default=f'file:{SQLITE_DEFAULT}')
#
#
# DATAFILE_BACKEND: source of dashboard data
#
# only file backends are currently supported, including 'local' and 's3'.
#
# the local backend requires specification of DATAFILE_PENDING and/or DATAFILE_ARCHIVE.
#
# the s3 backend requires specification of DATAFILE_S3_BUCKET.
#
DATAFILE_BACKEND = config('DATAFILE_BACKEND', default=None)
#
#
# DATAFILE_PENDING:
# DATAFILE_ARCHIVE: path(s) on locally-attached disk(s) where data files may be found
#
DATAFILE_PENDING = config('DATAFILE_PENDING', default=None, cast=path_or_none)
DATAFILE_ARCHIVE = config('DATAFILE_ARCHIVE', default=None, cast=path_or_none)
#
#
# DATAFILE_S3_BUCKET: name of an AWS S3 bucket where data files may be found
#
DATAFILE_S3_BUCKET = config('DATAFILE_S3_BUCKET', default=None)
#
#
# DATAFILE_S3_BASE: common prefix (or "base path") under which data files may be found
#
# data files are expected to be stored in a hierarchy (under this common prefix):
#
#     experiment/topic/device-cohort/date/json/*.json
#
DATAFILE_S3_BASE = config('DATAFILE_S3_BASE', default='')
#
#
# DATAFILE_S3_IGNORE: prefixes ("paths") which need not be walked ("searched") for data files
#
# (This can increase performance by excluding unproductive paths from the search.)
#
DATAFILE_S3_IGNORE = config('DATAFILE_S3_IGNORE', cast=Csv(delimiter=':'), default='')
#
#
DATAFILE_S3_CACHE_BACKEND = config('DATAFILE_S3_CACHE_BACKEND', default='local')
#
#
DATAFILE_S3_CACHE_PATH = config('DATAFILE_S3_CACHE_PATH',
                                default=f'/var/cache/{APP_NAME}/data/file/s3/get/')
#
#
DATAFILE_S3_CACHE_REMOTE = config('DATAFILE_S3_CACHE_REMOTE', default=None)
