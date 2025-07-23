from bottle import static_file

from app import conf, dashboard


@dashboard.get('/')
def index():
    return static_file('index.html', conf.STATIC_PATH)
