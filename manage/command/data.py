from argcmdr import localmethod

from manage import config, lib
from manage.main import Management


@Management.register
class Data(lib.LocalPiCommand):
    """inspect recorded data"""

    @localmethod('limit', nargs='?', default=10, type=int,
                 help="number of database records to return (default: %(default)s)")
    @localmethod('--local', action='store_true',
                 help="read the local development database (rather than the raspberry pi's)")
    def ndt(self, args):
        """list recent ndt7 records"""
        machine = self.local

        if not args.local:
            machine = machine['ssh'][f'{args.username}@{args.host}']

        command = machine['sqlite3'][
            '-column',
            '-header',
        ]

        if args.local:
            command = command[config.REPO_PATH / '.var/data.sqlite']
        else:
            command = command['/var/lib/netrics-dashboard/data.sqlite']

        return lib.FGOut, command << f"""\
            select datetime(ts, 'unixepoch', 'localtime') as datetime,
                   ts,
                   size,
                   period,
                   8 * size / period as mbaud
            from trial order by ts desc limit {args.limit}
        """
