"""Local HTTP monitoring, isolated centuria fixtures, and CLI regressions."""
import contextlib
import http.client
import io
import json
import os
from pathlib import Path
import runpy
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LEGIO = ROOT / 'legio'
API = runpy.run_path(str(LEGIO))
FIELDS = set(API['API_FIELDS'])


def job():
    return dict(id='001-test', issue=3, title='Test job', stage='custom-stage',
                round=1, round_limit=3, pr=None, gate=None, reviews={},
                cost_usd=1.25, active=True, waiting=False, terminal=False)


class APITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def project(self, name, jobs=None):
        p = self.root / name
        (p / '.centuria/bin').mkdir(parents=True)
        (p / '.centuria/config.json').write_text('{"secret":"private-config"}')
        (p / 'state.json').write_text(json.dumps([] if jobs is None else jobs))
        (p / 'mode').write_text('ok')
        cli = p / '.centuria/bin/job'
        cli.write_text(f'#!{sys.executable}\n' + '''import json, pathlib, sys, time
p = pathlib.Path.cwd()
with (p / 'calls').open('a') as f:
    f.write(json.dumps(sys.argv[1:]) + '\\n')
mode = (p / 'mode').read_text()
if mode == 'timeout': time.sleep(2)
if mode == 'exit':
    print('SECRET raw output', file=sys.stderr)
    sys.exit(1)
if mode == 'bad': print('SECRET invalid JSON')
elif mode == 'unicode': sys.stdout.buffer.write(b'\\xff')
else: print((p / 'state.json').read_text())
''')
        cli.chmod(0o755)
        return p

    @contextlib.contextmanager
    def server(self):
        handler = API['api_handler'](API['discover'](self.root))
        with API['ThreadingHTTPServer'](('127.0.0.1', 0), handler) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                yield server.server_port
            finally:
                server.shutdown()
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())

    def request(self, port, target='/api/status', method='GET'):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=4)
        try:
            conn.request(method, target)
            res = conn.getresponse()
            self.assertEqual(res.getheader('Content-Type'), 'application/json')
            return res.status, json.loads(res.read())
        finally:
            conn.close()

    def error(self, port, target, status, method='GET'):
        actual, data = self.request(port, target, method)
        self.assertEqual(actual, status, data)
        self.assertEqual(set(data), {'error'})
        self.assertEqual(set(data['error']), {'code', 'message'})
        self.assertNotIn('SECRET', json.dumps(data))
        self.assertNotIn('Traceback', json.dumps(data))
        return data['error']['message']

    def test_all_fields_states_filter_freshness_and_read_only(self):
        jobs = [job(), dict(job(), id='002-wait', active=False, waiting=True),
                dict(job(), id='003-end', active=False, terminal=True, issue=None,
                     pr=12, gate='PASS', reviews={'reviewer': 'PASS'}, cost_usd=2)]
        jobs[0].update(secret='SECRET', worktree='/private', prompts={'body': 'SECRET'})
        a = self.project('alpha', jobs)
        b = self.project('beta')
        before = {p: p.read_bytes() for base in (a, b) for p in base.rglob('*') if p.is_file()}
        with self.server() as port:
            status, data = self.request(port)
            self.assertEqual(status, 200)
            self.assertEqual(data, {'projects': [
                {'name': 'alpha', 'jobs': [{k: j[k] for k in FIELDS} for j in jobs]},
                {'name': 'beta', 'jobs': []}]})
            self.assertNotIn('SECRET', json.dumps(data))
            self.assertEqual(self.request(port, '/api/status?project=beta'),
                             (200, {'projects': [{'name': 'beta', 'jobs': []}]}))
            for method in ('POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE'):
                self.error(port, '/api/status', 405, method)
            for target in ('/else', '/api/status?project=missing',
                           '/api/status?project=../alpha', '/api/status?project=%2Ftmp',
                           '/api/status?project=%252e%252e', '/api/%73tatus',
                           '/api/status?project=Alpha'):
                self.error(port, target, 404)
            for target in ('?project=', '?project=alpha&project=alpha', '?x=y',
                           '?project', '?project=%ZZ', '?project=%FF', '?project=alpha&x=y'):
                self.error(port, '/api/status' + target, 400)
            for p, content in before.items():
                self.assertEqual(p.read_bytes(), content, str(p))
            jobs[0]['stage'] = 'later-custom-stage'
            (a / 'state.json').write_text(json.dumps(jobs))
            self.assertEqual(self.request(port)[1]['projects'][0]['jobs'][0]['stage'],
                             'later-custom-stage')
        for p in (a, b):
            self.assertTrue((p / 'calls').exists())
            self.assertTrue(all(json.loads(line) == ['view']
                                for line in (p / 'calls').read_text().splitlines()))

    def test_empty_root(self):
        with self.server() as port:
            self.assertEqual(self.request(port), (200, {'projects': []}))

    def test_project_read_failures_are_safe_and_recoverable(self):
        self.project('alpha', [job()])
        p = self.project('broken')
        globals_ = API['api_jobs'].__globals__
        old_timeout = globals_['API_READ_TIMEOUT']
        globals_['API_READ_TIMEOUT'] = 0.15
        self.addCleanup(globals_.__setitem__, 'API_READ_TIMEOUT', old_timeout)
        with self.server() as port:
            for mode in ('exit', 'bad', 'unicode', 'timeout'):
                with self.subTest(mode=mode):
                    (p / 'mode').write_text(mode)
                    self.assertIn('broken', self.error(port, '/api/status', 502))
                    self.assertEqual(self.request(port, '/api/status?project=alpha')[0], 200)
                    (p / 'mode').write_text('ok')
                    self.assertEqual(self.request(port)[0], 200)
            for invalid in ({}, None, [None], [{}], [dict(job(), active='yes')],
                            [dict(job(), cost_usd=float('nan'))],
                            [dict(job(), reviews={'x': {'secret': 'SECRET'}})]):
                with self.subTest(invalid=invalid):
                    (p / 'state.json').write_text(json.dumps(invalid))
                    self.assertIn('broken', self.error(port, '/api/status', 502))
            (p / 'state.json').write_text('[]')
            cli = p / '.centuria/bin/job'
            cli.chmod(0o644)
            self.assertIn('unavailable', self.error(port, '/api/status', 502))
            cli.unlink()
            self.assertIn('broken', self.error(port, '/api/status', 502))
            self.assertEqual(self.request(port, '/api/status?project=alpha')[0], 200)

    def run_cli(self, *args, script=LEGIO, env=None):
        clean_env = dict(os.environ)
        clean_env.pop('LEGIO_ROOT', None)
        clean_env.update(env or {})
        return subprocess.run([sys.executable, str(script), *args], capture_output=True,
                              text=True, env=clean_env, timeout=5)

    @contextlib.contextmanager
    def cli_server(self, *args, script=LEGIO, env=None):
        clean_env = dict(os.environ)
        clean_env.pop('LEGIO_ROOT', None)
        clean_env.update(env or {})
        proc = subprocess.Popen([sys.executable, str(script), 'api', *args],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=clean_env)
        try:
            self.assertTrue(select.select([proc.stdout], [], [], 5)[0], 'startup timed out')
            line = proc.stdout.readline()
            self.assertIn('127.0.0.1:', line)
            yield int(line.split('127.0.0.1:')[1].split()[0])
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
            out, err = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 0, err)
            self.assertNotIn('Traceback', err)

    def free_port(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]

    def test_cli_startup_root_precedence_shutdown_and_bind(self):
        p = self.project('configured')
        install = self.root / 'install'
        install.mkdir()
        shutil.copy2(LEGIO, install / 'legio')
        (install / 'config.json').write_text(json.dumps({'projects_root': str(self.root)}))
        empty = self.root / 'empty'
        empty.mkdir()
        for args, env, expected in (([], {}, ['configured']),
                                    ([], {'LEGIO_ROOT': str(empty)}, []),
                                    (['--root', str(self.root)], {'LEGIO_ROOT': str(empty)},
                                     ['configured'])):
            port = self.free_port()
            with self.cli_server('--port', str(port), *args,
                                 script=install / 'legio', env=env) as actual:
                self.assertEqual(actual, port)
                status, data = self.request(port)
                self.assertEqual(status, 200)
                self.assertEqual([p['name'] for p in data['projects']], expected)
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            res = self.run_cli('api', '--root', str(empty), '--port',
                               str(occupied.getsockname()[1]))
            self.assertNotEqual(res.returncode, 0)
            self.assertIn('could not bind', res.stderr)
            self.assertNotIn('Traceback', res.stderr)

    def test_loopback_dispatch_and_interrupt_without_socket(self):
        globals_ = API['cmd_api'].__globals__
        fake = mock.MagicMock()
        server = fake.return_value
        server.__enter__.return_value = server
        server.serve_forever.side_effect = KeyboardInterrupt
        server.server_port = 8765
        with mock.patch.dict(globals_, ThreadingHTTPServer=fake):
            with contextlib.redirect_stdout(io.StringIO()):
                API['main'](['api', '--root', str(self.root)])
        self.assertEqual(fake.call_args.args[0], ('127.0.0.1', 8765))
        server.serve_forever.assert_called_once_with()
        server.__exit__.assert_called_once()

    def test_cli_errors_help_and_default(self):
        for args in (['--port', '0'], ['--port', '-1'], ['--port', '65536'],
                     ['--port', 'abc'], ['--port'], ['--host', '0.0.0.0'], ['extra']):
            res = self.run_cli('api', '--root', str(self.root), *args)
            self.assertNotEqual(res.returncode, 0, args)
            self.assertIn('legio:', res.stderr)
            self.assertNotIn('Traceback', res.stderr)
        self.assertEqual(API['parse'](['api'])[0]['port'], 8765)
        for args in (['--help'], ['api', '--help']):
            res = self.run_cli(*args)
            self.assertEqual(res.returncode, 0)
            self.assertIn('legio api', res.stdout)
        help_ = self.run_cli('api', '--help').stdout
        for text in ('127.0.0.1', '8765', 'Ctrl-C', 'LEGIO_ROOT', '502'):
            self.assertIn(text, help_)
        res = self.run_cli('api', '--root', str(self.root / 'missing'))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('does not exist', res.stderr)

    def test_existing_ls_status_and_empty_behavior(self):
        self.project('alpha', [job(), dict(job(), id='002-wait', active=False, waiting=True),
                               dict(job(), id='003-end', active=False, terminal=True)])
        ls = self.run_cli('ls', '--root', str(self.root))
        self.assertEqual(ls.returncode, 0, ls.stderr)
        self.assertRegex(ls.stdout, r'alpha\s+1\s+1\s+1\s+\$3.75')
        status = self.run_cli('status', '--root', str(self.root))
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn('001-test', status.stdout)
        self.assertIn('custom-stage', status.stdout)
        self.assertIn('1/3', status.stdout)
        self.assertNotIn('002-wait', status.stdout)
        self.assertNotIn('003-end', status.stdout)
        all_ = self.run_cli('status', '--all', '--root', str(self.root))
        self.assertEqual(all_.returncode, 0, all_.stderr)
        self.assertIn('002-wait', all_.stdout)
        self.assertIn('003-end', all_.stdout)
        empty = self.root / 'empty'
        empty.mkdir()
        for cmd in ('ls', 'status'):
            res = self.run_cli(cmd, '--root', str(empty))
            self.assertNotEqual(res.returncode, 0)
            self.assertEqual(res.stdout, '')
            self.assertIn('no centuriae under', res.stderr)


if __name__ == '__main__':
    unittest.main()
