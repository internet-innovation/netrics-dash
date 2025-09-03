import json
import pathlib
import string
import tempfile
import time
from functools import partial

from argcmdr import cmd, CommandDecorator, Local, localmethod
from plumbum import colors
from plumbum.cmd import aws, zappa

from manage import config
from manage.main import Management


ROOT_DIR = pathlib.Path(__file__).parent.parent.parent


class DeployCommand(Local):

    def __init__(self, parser):
        parser.add_argument('tag', metavar='TAG', help="image tag to pull")
        parser.add_argument('--aws-repo', default=config.AWS_REPO, metavar='URI',
                            help="AWS ECR to which images were pushed" +
                                 (' (default: %(default)s)' if config.AWS_REPO else ''))
        parser.add_argument('--private-subnet',
                            metavar='subnet-id[,subnet-id]',
                            type=config.getlist,
                            default=config.AWS_SUBNET_PRIVATE,
                            help="AWS VPC private subnet(s) within which to provision ElastiCache" +
                                 (' (default: %(default)s)' if config.AWS_SUBNET_PRIVATE else ''))

    @property
    def image_uri(self):
        return f'{self.args.aws_repo}/netrics-dashboard/serve-lambda:{self.args.tag}'

    def __call__(self, args, parser):
        if not args.aws_repo:
            parser.error('specify the --aws-repo to which the lambda app was pushed')

        super().__call__(args)

    def delegate(self, method_name='prepare', *additional):
        return super().delegate(method_name, self.image_uri, *additional)


deploymethod = partial(cmd, binding=CommandDecorator.Binding.parent, base=DeployCommand)


@Management.register
class Deploy(Local):
    """manage a remote dashboard deployment"""

    Unset = object()

    def __init__(self, parser):
        parser.add_argument('env', choices=('dev', 'production'),
                            help="deployment environment to target")

    def print(self, *args, **kwargs):
        if self.args.execute_commands:
            print(*args, **kwargs)

    def poll_until(self, poll_func, success_func, initial_value=Unset, wait=3):
        if initial_value is self.Unset:
            (_retcode, result, _error) = yield self.local.SHH, poll_func()
        else:
            result = initial_value

        if result is None:
            # dry run
            return (None, None)

        if key := success_func(result):
            return (key, result)

        self.print('. ', end='', flush=True)
        time.sleep(wait)

        yield from self.poll_until(poll_func, success_func, wait=wait)

    def discover_cache_address(self, initial_value=Unset):
        self.print('Looking up cache endpoint address . . . ', end='', flush=True)
        (endpoint, _result) = yield from self.poll_until(
            partial(describe_cache, self.args.env),
            partial(extract_cache_address, self.args.env),
            initial_value,
        )
        self.print('done')
        return endpoint

    def render_settings(self, cache_description=Unset):
        cache_endpoint = yield from self.discover_cache_address(cache_description)

        settings_user = ROOT_DIR.joinpath('zappa_settings.toml').read_text()
        settings_template = string.Template(settings_user)
        settings_rendered = settings_template.substitute(
            CACHE_ENDPOINT=make_cache_uri(cache_endpoint),
        )

        settings = tempfile.NamedTemporaryFile(mode='w', suffix='.toml')
        settings.write(settings_rendered)
        settings.flush()

        return settings

    @deploymethod
    def create(self, args, parser, local, image_uri):
        """deploy to a new environment"""
        (_code, result, _error) = yield local.SHH, create_cache(args.env, args.private_subnet)

        with (yield from self.render_settings(result)) as settings:
            yield local.FG, zappa[
                'deploy',
                args.env,
                '--docker-image-uri', image_uri,
                '--settings_file', settings.name,
            ]

        yield local.FG, zappa['certify', args.env]

    @deploymethod
    def update(self, args, parser, local, image_uri):
        """update an existing environment"""
        # TODO: modify-serverless-cache?
        try:
            (_code, result, _error) = yield local.SHH, describe_cache(args.env)
        except local.ProcessExecutionError:
            # doesn't yet exist
            (_code, result, _error) = yield local.SHH, create_cache(args.env, args.private_subnet)

        with (yield from self.render_settings(result)) as settings:
            yield local.FG, zappa[
                'update',
                args.env,
                '--docker-image-uri', image_uri,
                '--settings_file', settings.name,
            ]

    @localmethod('--remove-logs', const='--remove-logs', action='append_const', dest='pass_thru')
    def destroy(self, args, parser, local):
        """remove a deployment environment"""
        yield local.FG, zappa['undeploy', args.pass_thru, args.env]
        yield local.FG, delete_cache(args.env)

    @localmethod
    def status(self, args, parser, local):
        """check the status of an environment"""
        yield local.FG, zappa['status', args.env]

        try:
            (_retcode, result, _error) = yield local.SHH, describe_cache(args.env)
        except local.ProcessExecutionError:
            result = None

        # FIXME: value is overly indented?
        print(
            (colors.fg('green') | '\tElastiCache URI') + ':',
            extract_cache_uri(args.env, result) if result else '',
            sep='\t',
        )


def create_cache(env, subnets=()):
    return aws[
        'elasticache',
        'create-serverless-cache',
        '--engine', 'valkey',
        '--serverless-cache-name', f'netrics-device-dashboard-{env}',
        '--description', 'Data cache for Netrics Device Dashboard'
                         + (f' ({env.upper()})' if env != 'production' else ''),
        '--tags', json.dumps([
            {'Key': 'project', 'Value': 'netrics'},
            {'Key': 'app', 'Value': 'netrics-device-dashboard'},
            {'Key': 'env', 'Value': env},
        ], separators=(',', ':')),
        ('--subnet-ids', *subnets) if subnets else (),
    ]


def describe_cache(env):
    return aws[
        'elasticache',
        'describe-serverless-caches',
        '--serverless-cache-name', f'netrics-device-dashboard-{env}',
    ]


def delete_cache(env):
    return aws[
        'elasticache',
        'delete-serverless-cache',
        '--serverless-cache-name', f'netrics-device-dashboard-{env}',
    ]


def extract_cache_address(env, data):
    for result in json.loads(data).get('ServerlessCaches', ()):
        if result['ServerlessCacheName'] == f'netrics-device-dashboard-{env}':
            return result.get('Endpoint')


def make_cache_uri(endpoint):
    return 'valkeys://{Address}:{Port}'.format_map(endpoint) if endpoint else 'valkeys://DRY:RUN'


def extract_cache_uri(env, data):
    return make_cache_uri(extract_cache_address(env, data))
