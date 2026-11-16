"""Local-only standalone launcher; no SSH, remote sync or runtime package installs."""
import argparse
import importlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import urllib.request
import webbrowser


def data_directory():
    if os.environ.get('RSS_DESKTOP_DATA_DIR'):
        return Path(os.environ['RSS_DESKTOP_DATA_DIR']).expanduser()
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'LocalRSS'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'LocalRSS'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'localrss'


def load_backend(directory, disable_scheduler=False):
    directory.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('RSS_DB', str(directory / 'global.db'))
    if disable_scheduler:
        os.environ['RSS_DISABLE_SCHEDULER'] = '1'
    backend = importlib.import_module('app')
    # Startup normally reports DB errors as warnings; desktop startup must fail clearly.
    backend.init_db()
    return backend


def check_http(server):
    url = f'http://127.0.0.1:{server.server_port}'
    for path in ('/', '/static/index.html'):
        with urllib.request.urlopen(url + path, timeout=10) as response:
            if response.status != 200 or b'<title>Local RSS</title>' not in response.read():
                raise RuntimeError('LocalRSS browser interface did not load: ' + path)


def self_test():
    # Override any caller DB path so the release check cannot touch real user data.
    with tempfile.TemporaryDirectory() as temp:
        os.environ['RSS_DB'] = str(Path(temp) / 'global.db')
        backend = load_backend(Path(temp), disable_scheduler=True)
        if not backend._acquire_scheduler_leadership():
            raise RuntimeError('Cannot acquire desktop harvester lock')
        try:
            if backend._acquire_scheduler_leadership():
                raise RuntimeError('Harvester lock allowed duplicate ownership')
        finally:
            backend._scheduler_leader_fh.close()
        from werkzeug.serving import make_server
        server = make_server('127.0.0.1', 0, backend.app, threaded=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            check_http(server)
            with backend.app.test_client() as client:
                if client.get('/api/items').status_code != 401:
                    raise RuntimeError('Authentication gate was not preserved')
        finally:
            server.shutdown()
            server.server_close()
            worker.join(5)
    print('PASS: packaged backend, temporary SQLite, browser assets, HTTP startup and authentication gate')


def main():
    parser = argparse.ArgumentParser(description='Run LocalRSS locally and open its browser interface')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=int(os.environ.get('RSS_PORT', '8787')))
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    directory = data_directory()
    os.environ['RSS_PORT'] = str(args.port)
    backend = load_backend(directory)
    from werkzeug.serving import make_server
    # Bind before opening the browser; a port conflict must not look like success.
    server = make_server('127.0.0.1', args.port, backend.app, threaded=True)
    print(f'LocalRSS is running at http://127.0.0.1:{args.port}')
    print(f'Database: {backend.GLOBAL_DB_PATH}')
    print('Keep this window open. Press Ctrl+C to stop LocalRSS.')
    if not args.no_browser:
        webbrowser.open(f'http://127.0.0.1:{args.port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
