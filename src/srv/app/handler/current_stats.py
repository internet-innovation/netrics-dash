import operator
from functools import partial

from app import dashboard
from app.data.file import get_points, Last, StdDev, ONE_WEEK_S


@dashboard.get('/stats')
def get_recent_results():
    # note: not currently included: consumption
    try:
        return get_points(
            latency=Last('ping_latency.google_rtt_avg_ms', where=partial(operator.le, 0)),

            # currently disabled
            # ndev_week=Last('connected_devices_arp.devices_1week'),

            ookla_dl=Last('ookla.speedtest_ookla_download'),
            ookla_ul=Last('ookla.speedtest_ookla_upload'),
            ookla_dl_sd=StdDev('ookla.speedtest_ookla_download', ONE_WEEK_S),
        )
    except FileNotFoundError:
        # measurements (directory) not (yet) initialized
        #
        # treat this no differently than missing data points
        #
        return {
            'latency': None,

            # 'ndev_week': None,

            'ookla_dl': None,
            'ookla_ul': None,
            'ookla_dl_sd': None,
        }
