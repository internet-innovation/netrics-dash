import re
import sqlite3
import statistics

from bottle import abort, request, response

from app import dashboard
from app.data.db import sqlite as db
from app.data.file import DataFileBank, Last


TRIAL_REPORTING_TIMEOUT = 30

ACTIVE_TRIAL_CONDITION = """\
size is null and period is null and (strftime('%s', 'now') - ts < ?)\
"""

RECENT_TRIAL_CONDITION = """\
size is not null and period is not null and (strftime('%s', 'now') - ts < ?)\
"""

COMPLETE_TRIAL_CONDITION = """\
size is not null and period is not null\
"""

CAST_TRUE = {'1', 'true', 'on'}
CAST_FALSE = {'0', 'false', 'off', ''}
CAST_VALUES = CAST_TRUE | CAST_FALSE


def clean_flag(flag):
    flag_arg = getattr(request.query, flag).lower()

    if flag_arg not in CAST_VALUES:
        abort(400, 'Bad request')

    return flag_arg in CAST_TRUE


def clean_period():
    if not request.query.period:
        return None

    period_match = re.fullmatch(r'(\d+)(m|h)?', request.query.period.lower())

    if not period_match:
        abort(400, 'Bad request')

    (period_value, period_unit) = period_match.groups()

    period_seconds = int(period_value)

    if period_unit == 'm':
        period_seconds *= 60
    elif period_unit == 'h':
        period_seconds *= 3600

    return period_seconds


def clean_limit():
    if not request.query.limit:
        return None

    try:
        return int(request.query.limit)
    except ValueError:
        abort(400, 'Bad request')


def build_where_clause():
    where = ''
    args = []

    if clean_flag('active'):
        where = f'where ({ACTIVE_TRIAL_CONDITION})'
        args.append(TRIAL_REPORTING_TIMEOUT)

    if (period := clean_period()) is not None:
        where += ' or ' if where else 'where '
        where += f'({RECENT_TRIAL_CONDITION})'
        args.append(period)

    if clean_flag('complete'):
        if period:
            abort(400, 'Bad request')

        where += ' or ' if where else 'where '
        where += f'({COMPLETE_TRIAL_CONDITION})'

    return (where, args)


@dashboard.get('/trial/')
def list_trials():
    (where, args) = build_where_clause()

    limit = '' if (limit_value := clean_limit()) is None else f'limit {limit_value}'

    with db.client.connect() as conn:
        cursor = conn.execute(f"select * from trial {where} order by ts desc {limit}", args)

        names = [column[0] for column in cursor.description]

        results = [
            dict(zip(names, row))
            for row in cursor
        ]

    return {
        'selected': results,
        'count': len(results),
    }


@dashboard.get('/trial/stats')
def stat_trials():
    recent_limit = 10 if (limit_value := clean_limit()) is None else limit_value
    if not 0 <= recent_limit <= 1000:
        abort(400, 'Bad request')

    with db.client.connect() as conn:
        (total_count,) = conn.execute(f"""\
            select count(1) from trial
            where {COMPLETE_TRIAL_CONDITION}
        """).fetchone()

        win_where = "where bucket between 2 and 9" if total_count > 8 else ""

        # trial stores size as bytes and period as microseconds
        # we'll map to a rate of bytes/second
        (stat_mean_win, stat_count_win) = conn.execute(f"""\
            select avg(rate),
                   count(1)

            from (
                select rate,
                       ntile(10) over (order by rate) as bucket

                from (
                    select 1000000.0 * size / period as rate from trial
                    where {COMPLETE_TRIAL_CONDITION}
                )
            )

            {win_where}
        """).fetchone()

        # sqlite doesn't have a built-in stdev function; so we'll load ~all rates for stdev.
        cursor = conn.execute(f"""
            select ts, 1000000.0 * size / period as speed from trial
            where {COMPLETE_TRIAL_CONDITION}
            order by ts desc
            limit 1000
        """)
        names = [column[0] for column in cursor.description]
        history = [
            dict(zip(names, row))
            for row in cursor
        ]
        all_rates = [row['speed'] for row in history]

        success_count = None

        if total_count > 0:
            file_bank = DataFileBank(flat=True)

            try:
                ookla_dl = file_bank.get_points(Last('ookla.speedtest_ookla_download'))
            except FileNotFoundError:
                # measurements (directory) not (yet) initialized
                #
                # treat this no differently than missing data points
                #
                ookla_dl = None

            if ookla_dl is not None:
                cursor = conn.execute(f"""
                    select count(1) from trial
                    where {COMPLETE_TRIAL_CONDITION} and 8.0 * size / period > ?
                """, (ookla_dl,))
                (success_count,) = cursor.fetchone()

    return {
        'total_count': total_count,
        'stat_count_win': stat_count_win,
        'stat_mean_win': stat_mean_win,
        'stat_stdev': statistics.stdev(all_rates) if len(all_rates) > 1 else None,
        'recent_rates': history[:recent_limit],
        'success_count': success_count,
    }


@dashboard.post('/trial/')
def create_trial():
    if request.forms:
        raise NotImplementedError

    (where, args) = build_where_clause()

    if where:
        query = f"""\
            insert into trial (ts)

            select * from (values (strftime('%s', 'now')))
            where not exists (select 1 from trial {where} limit 1)

            returning ts
        """
    else:
        query = "insert into trial default values returning ts"

    with db.client.connect() as conn:
        try:
            cursor = conn.execute(query, args)
        except sqlite3.IntegrityError:
            ts = None
        else:
            (ts,) = cursor.fetchone() or (None,)

    response.status = 409 if ts is None else 201

    return {
        'inserted': None if ts is None else {'ts': ts},
    }


@dashboard.put('/trial/<ts:int>')
def upsert_trial(ts):
    try:
        values = [int(arg) for arg in (request.forms.size,
                                       request.forms.period)]
    except ValueError:
        abort(400, 'Bad request')

    with db.client.connect() as conn:
        conn.execute("""\
            insert into trial values (?, ?, ?)
            on conflict (ts) do update set size=excluded.size, period=excluded.period
        """, [ts] + values)

    response.status = 204
