import sqlite3
import threading

from app import conf


# For downstream maintenance, etc.
TABLE_SCHEMA = (
    ('survey', ('ts', 'subj')),
    ('trial', ('ts', 'size', 'period')),
)

# NOTE: rowid ommitted to prevent sqlite from substituting a sequential rowid
# NOTE: for the correct timestamp default;
# NOTE: (however, there might be better solutions).
PREPARE_DATABASE = """\
create table if not exists survey (
    ts integer primary key default (strftime('%s', 'now')),
    subj integer not null
) without rowid;

create table if not exists trial (
    ts integer primary key default (strftime('%s', 'now')),
    size integer,
    period integer
) without rowid;
"""


class Client(threading.local):

    @staticmethod
    def make_connection():
        return sqlite3.connect(
            conf.APP_DATABASE,
            uri=True,
        )

    def connect(self):
        try:
            conn = self.connection
        except AttributeError:
            conn = self.connection = self.make_connection()

        return conn

    def prepare_database(self):
        with self.connect() as conn:
            conn.executescript(PREPARE_DATABASE)


client = Client()

client.prepare_database()
