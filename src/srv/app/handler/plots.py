from app import dashboard
from app.data.file import FlatDataFileBank, ONE_WEEK_S
from app.lib.functional import apidefault


def get_columns(*keys):
    return FlatDataFileBank(round_to=2).get_columns(
        keys,
        age_s=ONE_WEEK_S,
        reverse=True,
        decorate='Time',
    )


@dashboard.get('/plots/throughput')
@apidefault('bw', FileNotFoundError)
def get_throughput():
    (bw_dl, bw_ul, bw_ts) = get_columns(
        'ookla.speedtest_ookla_download',
        'ookla.speedtest_ookla_upload',
    )
    return {
        'bw': {
            'ts': bw_ts,
            'dl': bw_dl,
            'ul': bw_ul,
        },
    }


@dashboard.get('/plots/latency')
@apidefault('latency', FileNotFoundError)
def get_latency():
    (rtt_google, rtt_amazon, rtt_wikipedia, rtt_ts) = get_columns(
        'ping_latency.google_rtt_avg_ms',
        'ping_latency.amazon_rtt_avg_ms',
        'ping_latency.wikipedia_rtt_avg_ms',
    )
    return {
        'latency': {
            'ts': rtt_ts,
            'google': rtt_google,
            'amazon': rtt_amazon,
            'wikipedia': rtt_wikipedia,
        },
    }
