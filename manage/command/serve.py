import pathlib
from configparser import ConfigParser

from plumbum import colors

from manage import config, lib
from manage.main import Management


@Management.register
class Serve(lib.DockerCommand):
    """serve dashboard locally"""

    def __init__(self, parser):
        parser.add_argument('--name', default='ndash',
                            help="name to apply to local dashboard container (default: %(default)s)")
        parser.add_argument('--version', default='latest',
                            help="version/tag of image to run (default: %(default)s)")
        parser.add_argument('--log-level',
                            choices=('trace', 'debug', 'info', 'success',
                                     'warning', 'error', 'critical'),
                            default='debug',
                            help="level of log messages to enable (default: %(default)s)")
        parser.add_argument('--debug', action='store_true', help="enable the server's debug mode")
        parser.add_argument('--profile', action='store_true',
                            help="enable the request-profiling middleware "
                                 "(reports printed to the server's stdout)")
        parser.add_argument('--no-dev', action='store_false', dest='serve_dev',
                            help="do NOT mount the host filesystem's under-development "
                                 "repository tree (src/) into the container and "
                                 "do NOT configure server to autoreload source")
        parser.add_argument('--topic', default='beta',
                            help='netrics "topic" under which measurement data '
                                 'are written (default: %(default)s)')
        parser.add_argument('--upload', metavar='PATH', type=pathlib.Path,
                            help="local path to mounted data upload directory")
        parser.add_argument('--aws-profile', metavar='NAME',
                            help="configured AWS profile credentials to set in the "
                                 "dashboard environment")

    @property
    def aws_credentials(self):
        aws_profile = self.args.aws_profile

        if not aws_profile:
            return {}

        creds_path = pathlib.Path.home() / '.aws' / 'credentials'

        aws_config = ConfigParser()
        aws_config.read(creds_path)

        try:
            creds_values = aws_config[aws_profile]
        except KeyError:
            self.args.__parser__.error(f"no such configured aws profile: {aws_profile}")
        else:
            return {key.upper(): value for (key, value) in creds_values.items()}

    def prepare(self, args):
        for cleanup_command in ('stop', 'rm'):
            try:
                yield lib.SHH, self.docker[
                    cleanup_command,
                    args.name,
                ]
            except self.local.ProcessExecutionError:
                pass

        run_command = self.docker[
            'run',
            '-d',
            '-p', '8080:8080',
            '--name', args.name,
        ]

        if config.ENV_FILE.exists():
            run_command = run_command['--env-file', config.ENV_FILE]
        else:
            print('warning: dashboard will not operate correctly without environment values')
            print(f'tip: scp {config.NETRICS_HOST}:/etc/nm-exp-active-netrics/.env .')

        run_command = run_command['--env', 'APP_LOG_LEVEL=' + args.log_level.upper()]

        if args.debug:
            run_command = run_command['--env', 'APP_DEBUG=1']

        if args.profile:
            run_command = run_command['--env', 'APP_PROFILE=1']

        if args.serve_dev:
            yield self.local['mkdir']['-p', config.REPO_PATH / '.var']

            run_command = run_command[
                '--env', 'APP_RELOAD=1',
                '--volume', str(config.REPO_PATH / 'src') + ':/usr/src/dashboard',
                '--volume', str(config.REPO_PATH / '.var') + ':/var/lib/dashboard',
            ]

        if args.upload:
            run_command = run_command[
                '--env', f'DATAFILE_PENDING=/var/nm/nm-exp-active-netrics/upload/pending/{args.topic}/json/',
                '--env', f'DATAFILE_ARCHIVE=/var/nm/nm-exp-active-netrics/upload/archive/{args.topic}/json/',
                '--volume', f'{args.upload}:/var/nm',
            ]

        for (env_key, env_value) in self.aws_credentials.items():
            run_command = run_command['-e', f'{env_key}={env_value}']

        yield lib.SHH, run_command[
            f'{args.image_repo}/netrics-dashboard:{args.version}',
        ]

        if args.execute_commands:
            print('SUCCESS:' | colors.success,
                  'view local dashboard at',
                  'http://localhost:8080/' | colors.underline)
