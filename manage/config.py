import re
import os
import pathlib


def getlist(value, sep=','):
    split = re.split(rf' *{sep} *', value.strip())
    return [var for var in split if var]


def getenvlist(name, sep=','):
    value = os.getenv(name, '')
    return getlist(value, sep)


AWS_REPO = os.getenv('AWS_REPO') or None

AWS_SUBNET_PRIVATE = getenvlist('AWS_SUBNET_PRIVATE') or None

BINFMT_TAG = 'a7996909642ee92942dcd6cff44b9b95f08dad64'
BINFMT_TARGET = pathlib.Path('/proc/sys/fs/binfmt_misc/qemu-aarch64')

NDT_SERVER_ORIGIN = 'm-lab/ndt-server'
NDT_SERVER_TAG = 'v0.22.0'

NETRICS_USER = 'ubuntu'
NETRICS_HOST = 'netrics.local'

MANAGE_PATH = pathlib.Path(__file__).absolute().parent

REPO_PATH = MANAGE_PATH.parent

ENV_FILE = REPO_PATH / '.env'

EXTENSION_PATH = REPO_PATH / 'src' / 'ext'
