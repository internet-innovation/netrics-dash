import contextlib
import functools
import importlib
import logging as default_logging
import pkgutil
import sys

import bottle
import schedule
import whitenoise
from loguru import logger as log

from app import conf, handler, plugin, route, server, task
from app.middleware.response_header import ResponseHeaderMiddleware


dashboard = bottle.Bottle()


def configure_logging(level='INFO'):
    # clear default handler
    log.remove()

    # determine message format
    if conf.APP_RELOAD:
        process_name = 'ChildProcess' if conf.BOTTLE_CHILD else 'MainProcess'
        process_stanza = f"{process_name:<12} | "
    else:
        process_stanza = ""

    log_format = (
        "{time:YYYY-MM-DD @ HH:mm:ss} | {level:<5} | " +
        process_stanza +
        "{thread.name:<10} | {name}:{function}:{line} | {message}"
    )

    # add stdout sink
    log.add(sys.stdout, format=log_format, level=level)

    # enable schedule's (debug) logging
    default_logging.getLogger('schedule').setLevel(level=level)


def init_submodules(pkg):
    for module_info in pkgutil.walk_packages(pkg.__path__, f'{pkg.__name__}.'):
        if not module_info.ispkg:
            importlib.import_module(module_info.name)


def init_tasks():
    log.trace('init tasks')

    if conf.DATAFILE_BACKEND != 'local':
        if not conf.BOTTLE_CHILD:
            log.info("non-local backend | no jobs or tasks to schedule "
                     "outside of DATAFILE_BACKEND=local mode")

        return None

    if conf.APP_RELOAD and not conf.BOTTLE_CHILD:
        log.warning('bottle reloader | will NOT schedule jobs & tasks in main process')
        return None

    if conf.APP_RELOAD:
        log.info('bottle reloader | (re)-scheduling jobs & tasks in child process')

    # load tasks
    #
    # avoid circular dependency (for config)
    datafile = importlib.import_module('app.data.file')

    # schedule tasks
    #
    # pre- and/or re-populate file caches.
    #
    # Wraps the DataFileBank method, to suppress FileNotFoundError, for
    # use as a periodic task. A race condition may exist between the
    # initialization of this service and of the measurement service(s);
    # however, this should not crash the background thread nor otherwise
    # interrupt the task's schedule.
    #
    # In this initial case, the performance hit of populating measurement
    # caches in the main thread is negligible; and, subsequent task
    # invocations *may* proceed without issue.
    #
    cache_task = task.SafeTask(datafile.populate_caches, exc=FileNotFoundError, level='WARNING')
    cache_job = schedule.every(4).hours.do(cache_task)

    log.opt(lazy=True).debug('scheduled jobs | added {}', lambda: len(schedule.get_jobs()))

    # init executioners
    #
    # ScheduleExecutioner runs tasks as they come due
    executioner = task.ScheduleExecutioner.launch()

    stop_event = executioner.stop_event

    # ItemExecutioner runs one-off tasks as they're enqueued
    #
    # for now we just want to force this one task, once, on start-up:
    worker = task.ItemExecutioner.launch(max_items=1, stop_event=stop_event)
    worker.queue.put(cache_job)

    return stop_event


def logging(func):
    """Initialize logging configuration.

    Implemented as a decorator to enable wrapping of critical
    functionality.

    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not logging.configured:
            logging.configured = True

            configure_logging(conf.LOG_LEVEL)

            bottle.install(plugin.RouteErrorLogger())

        return func(*args, **kwargs)

    return log.catch(wrapper)


logging.configured = False


@contextlib.contextmanager
def _task_loop():
    """Initialize tasks and workers.

    Implemented as a context manager and decorator to ensure that
    workers are shut down on exit.

    """
    stop_event = init_tasks()
    try:
        yield stop_event
    finally:
        if stop_event:
            stop_event.set()


def task_loop(func=None):
    ctx_dec = _task_loop()
    return ctx_dec if func is None else ctx_dec(func)


def redirect_to_dashboard():
    bottle.redirect(conf.APP_PREFIX, 302)


@logging
@task_loop
def main():
    log.trace('init server')

    init_submodules(handler)

    core_app = bottle.app()

    core_app.router.add_filter('deviceid', route.deviceid_filter)

    core_app.add_hook('before_request', route.deviceid_hook)

    core_app.mount(conf.APP_PREFIX or '/', dashboard)

    if conf.APP_REDIRECT and conf.APP_PREFIX.strip('/'):
        core_app.route('/', 'GET', redirect_to_dashboard)

    # WhiteNoise not strictly required --
    # Bottle does support static assets --
    # (but, WhiteNoise is more robust, etc.)
    whitenoise_app = whitenoise.WhiteNoise(
        core_app,
        autorefresh=conf.APP_RELOAD,
        index_file=False,
        prefix=conf.STATIC_PREFIX,
        root=conf.ASSET_PATH,
    )

    version_headers = () if conf.APP_VERSION is None else [('Software-Version', conf.APP_VERSION)]

    app = ResponseHeaderMiddleware(
        whitenoise_app,
        *version_headers,
        Software='netrics-dashboard',
    )

    if conf.APP_PROFILE:
        from app.middleware.profiler import ProfilerMiddleware
        app = ProfilerMiddleware(app)

    bottle.run(
        app,
        server=server.WaitressServer,
        threads=8,                           # Waitress: threads
        clear_untrusted_proxy_headers=True,  # Waitress: silence warnings
        debug=conf.APP_DEBUG,
        host=conf.APP_HOST,
        port=conf.APP_PORT,
        quiet=conf.APP_QUIET,
        reloader=conf.APP_RELOAD,
    )
