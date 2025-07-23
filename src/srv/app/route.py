"""Request routing support."""
import re

import bottle


DEVICEID_PATTERN = r'[0-9a-zA-Z]{8}'

DEVICEID_PATH_RE = re.compile(r'/(?P<deviceid>{})(?:/|$)'.format(DEVICEID_PATTERN))


def deviceid_filter(config):
    """Match a Netrics device ID (UUID fragment) in a URL path."""
    if config:
        raise ValueError("deviceid filter does not expect any arguments")

    return (
        # Regular expression to match a device ID in the path:
        DEVICEID_PATTERN,

        # input filter: we have no transformations to make *and* this (reasonably)
        # would *require* naming the argument (and passing it to request handlers);
        # (but we'll *allow* it to be anonymous and unpassed):
        None,
        # otherwise we might do this (no-op) input filter:
        # lambda match: match.group(0),

        # builder: also no transformations to make:
        None,
        # otherwise we'd supply this no-op:
        # lambda deviceid: deviceid,
        # for that matter bottle will just use:
        # str,
    )


def deviceid_hook():
    """Provide the Bottle request object with the `device_id` attribute.

    This value is extracted from the request path (if present).

    """
    match = DEVICEID_PATH_RE.search(bottle.request.path)
    bottle.request.device_id = match and match[1]


class DeviceIDProvider:
    """Mix-in for objects whose instantiation requires `device_id`.

    Upon instanation of the resulting subclass, the device ID will be
    taken from the Bottle request object and passed to the superclass
    constructor.

    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, device_id=bottle.request.device_id, **kwargs)
