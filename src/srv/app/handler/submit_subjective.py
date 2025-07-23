from bottle import abort, request

from app import dashboard
from app.data.db import sqlite as db


PERF_LABELS = ('good', 'slow', 'unusable')


@dashboard.post('/survey/')
def handle_survey():
    subj_label = request.forms.get('subjective')

    try:
        subj_code = PERF_LABELS.index(subj_label)
    except ValueError:
        abort(400, 'Bad request')

    with db.client.connect() as conn:
        conn.execute("insert into survey (subj) values (?)", (subj_code,))

    return {
        'inserted': {
            'value': subj_label,
            'code': subj_code,
        }
    }
