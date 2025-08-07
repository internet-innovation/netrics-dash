import operator
from functools import partial

from app import dashboard
from app.data.file import get_points, Last, StdDev, ONE_WEEK_S
from app.lib.functional import apidefault


@dashboard.get('/stats/current')
@apidefault('latency', 'ookla_dl', 'ookla_ul', FileNotFoundError)
def get_current_stats():
    return get_points(
        latency=Last('ping_latency.google_rtt_avg_ms', where=partial(operator.le, 0)),

        # currently disabled
        # ndev_week=Last('connected_devices_arp.devices_1week'),

        ookla_dl=Last('ookla.speedtest_ookla_download'),
        ookla_ul=Last('ookla.speedtest_ookla_upload'),
    )


@dashboard.get('/stats/week')
@apidefault('ookla_dl_sd', FileNotFoundError)
def get_week_stats():
    return get_points(
        ookla_dl_sd=StdDev('ookla.speedtest_ookla_download', ONE_WEEK_S),
    )
