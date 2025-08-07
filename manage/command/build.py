import pathlib
import re

from descriptors import cachedproperty

from manage import config, lib
from manage.main import Management


def version_type(value):
    if not re.match(r'v?\d+\.\d+\.\d+', value):
        raise ValueError('invalid version number')

    return value


@Management.register
class Build(lib.DockerCommand):
    """build dashboard images for amd64 & arm64"""

    dashboard_stages = ('cmd', 'serve-local2', 'serve-local-s3', 'serve-lambda')
    dashboard_default = dashboard_stages[1]

    def __init__(self, parser):
        parser.add_argument('app', choices=('dash', 'ndt-full', 'ndt-base'), help="app to build")
        parser.add_argument('--version', type=version_type,
                            help="version to apply to the local dashboard app or to "
                                 "the extended ndt server (e.g.: 1.0.1)")
        parser.add_argument('--target',
                            choices=self.dashboard_stages,
                            metavar='STAGE',
                            help="dashboard stage (\"flavor\") to build "
                                 f"(default: {self.dashboard_default}, or one of: %(choices)s)")
        parser.add_argument('--env', metavar='ENV', help="zappa stage-env (for lambda only)")
        parser.add_argument('--aws-repo', help="URI of AWS ECR to push Lambda images")
        parser.add_argument('--ndt-cache', default=(config.REPO_PATH / '.ndt-server'),
                            metavar='PATH', type=pathlib.Path,
                            help="path at which to cache the ndt-server repository "
                                 '(for basic "ndt" build) (default: %(default)s)')
        parser.add_argument('--builder', default='netrics-dashboard', metavar='NAME',
                            help="name to assign to builder (default: %(default)s)")
        parser.add_argument('--binfmt', default=config.BINFMT_TAG, metavar='TAG',
                            help="Docker image tag of binfmt (default: %(default)s)")
        parser.add_argument('--push', action='store_true',
                            help="push images to remote repository "
                                 "(rather than load images locally)")
        parser.add_argument('--no-latest', action='store_false', dest='tag_latest',
                            help="do NOT tag images as \"latest\"")

    @cachedproperty
    def action(self):
        return '--push' if self.args.push else '--load'

    @cachedproperty
    def platforms(self):
        return 'linux/amd64,linux/arm64' if self.args.push else 'linux/amd64'

    def tag_args(self, uri, version):
        args = ('-t', f'{uri}:{version}')

        return args + ('-t', f'{uri}:latest') if self.args.tag_latest else args

    def prepare_ndt_base_tag(self):
        (_retcode, stdout, _stderr) = yield lib.SHH, self.local['git'][
            '-C', self.args.ndt_cache,
            'describe',
            '--tag',
        ]
        return stdout if stdout is None else stdout.strip()

    def prepare_ndt_base(self):
        # 1. m-lab was not initially building images at all
        # 2. now, they're just building for amd64 -- not for arm64 as well
        #
        # here we build their server for amd64 and arm64
        if self.args.ndt_cache.exists():
            # ensure configured tag is checked out
            if (yield from self.prepare_ndt_base_tag()) != config.NDT_SERVER_TAG:
                yield self.local.FG, self.local['git'][
                    '-C', self.args.ndt_cache,
                    'fetch',
                    '--depth', '1',
                    'origin',
                    f'+refs/tags/{config.NDT_SERVER_TAG}:refs/tags/{config.NDT_SERVER_TAG}',
                ]
                yield self.local.FG, self.local['git'][
                    '-C', self.args.ndt_cache,
                    'checkout',
                    config.NDT_SERVER_TAG,
                ]
        else:
            # clone server repo
            yield self.local.FG, self.local['git'][
                'clone',
                '--branch', config.NDT_SERVER_TAG,
                '--config', 'advice.detachedHead=false',
                '--depth', '1',
                f'https://github.com/{config.NDT_SERVER_ORIGIN}.git',
                self.args.ndt_cache,
            ]

        ndt_tag = (yield from self.prepare_ndt_base_tag()) or 'DRY.RUN'

        yield self.local.FG, self.docker[
            'buildx',
            'build',
            '--platform', self.platforms,
            self.tag_args(f'{self.args.image_repo}/ndt-server', ndt_tag),
            self.args.ndt_cache,
            self.action,
        ]

    def prepare_ndt_full(self):
        yield self.local.FG, self.docker[
            'buildx',
            'build',
            '--platform', self.platforms,
            '--build-arg', f'BASE_TAG={config.NDT_SERVER_TAG}',
            self.tag_args(f'{self.args.image_repo}/ndt-server-full', self.args.version),
            config.REPO_PATH / 'image' / 'ndt',
            self.action,
        ]

    def prepare_dash(self):
        if self.args.aws_repo and 'lambda' in self.args.target:
            aws_repo_name = f'{self.args.aws_repo}/netrics-dashboard/{self.args.target}'
            tag_args = [*self.tag_args(aws_repo_name, self.args.version)]
        else:
            repo_stem = f'{self.args.image_repo}/netrics-dashboard'
            repo_tags = (f'{repo_stem}-{self.args.target}',)

            if self.args.target == self.dashboard_default:
                repo_tags += (repo_stem,)

            tag_args = [tag_arg
                        for repo_tag in repo_tags
                        for tag_arg in self.tag_args(repo_tag, self.args.version)]

        env_args = (
            '--build-arg', f'STAGE_ENV={self.args.env}',
        ) if self.args.env and 'lambda' in self.args.target else ()

        yield self.local.FG, self.docker[
            'buildx',
            'build',
            '--target', self.args.target,
            '--platform', 'linux/amd64',
            '--build-arg', f'APPVERSION={self.args.version}',
            env_args,
            tag_args,
            config.REPO_PATH,
            self.action,
        ]

    def prepare(self, args, parser):
        if args.target and args.app != 'dash':
            parser.error('--target only applies to dash builds')
        elif not args.target:
            args.target = self.dashboard_default

        if args.app == 'dash' or args.app == 'ndt-full':
            if not args.version:
                parser.error('--version required to build either dash or ndt-full')
        elif args.version:
            parser.error('--version only applies to dash and ndt-full builds')

        if not config.BINFMT_TARGET.exists():
            yield self.local.FG, self.docker[
                'run',
                '--rm',
                '--privileged',
                f'docker/binfmt:{args.binfmt}',
            ]

        try:
            yield self.local.FG, self.docker[
                'buildx',
                'ls',
            ] | self.local['grep'][args.builder]
        except self.local.ProcessExecutionError:
            yield self.local.FG, self.docker[
                'buildx',
                'create',
                '--name', args.builder,
                '--platform', 'linux/amd64,linux/arm64',
            ]

        yield self.local.FG, self.docker[
            'buildx',
            'use',
            args.builder,
        ]

        if args.app == 'ndt-base':
            yield from self.prepare_ndt_base()

        elif args.app == 'ndt-full':
            yield from self.prepare_ndt_full()

        elif args.app == 'dash':
            yield from self.prepare_dash()

        else:
            raise NotImplementedError(args.app)
