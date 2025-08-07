from functools import partial

from app import dashboard
from app.data.file import FlatDataFileBank, ONE_WEEK_S
from app.lib.concurrent import parallel
from app.lib.functional import apidefault


@dashboard.get('/plots')
@apidefault('bw', 'latency', 'consumption', 'devices', FileNotFoundError)
def get_measurements():
    bank = FlatDataFileBank(round_to=2)

    get_columns = partial(bank.get_columns,
                          age_s=ONE_WEEK_S,
                          reverse=True,
                          decorate='Time')

    (
        (bw_dl, bw_ul, bw_ts),
        (rtt_google, rtt_amazon, rtt_wikipedia, rtt_ts),
    ) = parallel(
        partial(get_columns, (
            'ookla.speedtest_ookla_download',
            'ookla.speedtest_ookla_upload',
        )),
        partial(get_columns, (
            'ping_latency.google_rtt_avg_ms',
            'ping_latency.amazon_rtt_avg_ms',
            'ping_latency.wikipedia_rtt_avg_ms',
        )),
    )

    #
    # currently disabled
    #
    # (dev_now, dev_1d, dev_1w, dev_tot, dev_ts) = get_columns(
    #     (
    #       'connected_devices_arp.devices_active',
    #       'connected_devices_arp.devices_1day',
    #       'connected_devices_arp.devices_1week',
    #       'connected_devices_arp.devices_total',
    #     ),
    #     decorate='Time',
    # )

    return {
        'bw': {
            'ts': bw_ts,
            'dl': bw_dl,
            'ul': bw_ul,
        },
        'latency': {
            'ts': rtt_ts,
            'google': rtt_google,
            'amazon': rtt_amazon,
            'wikipedia': rtt_wikipedia,
        },
        # note: not currently included: consumption
        'consumption': {
            'ts': (),
            'dl': (),
            'ul': (),
        },
        # note: not currently included: devices
        # 'devices': {
        #     'ts': dev_ts,
        #     'active': dev_now,
        #     '1d': dev_1d,
        #     '1w': dev_1w,
        #     'tot': dev_tot,
        # },
        'devices': {
            'ts': (),
            'active': (),
            '1d': (),
            '1w': (),
            'tot': (),
        },
    }
