"""Patcwatch: deterministic local and Microsoft feedback monitoring."""
import argparse
import hashlib
import json
import os
import tempfile
import socket
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
GUARD = {'blocked_outbound_attempts': 0}
LOCK = threading.Lock()
DATA = Path.home() / '.patcwatch'
MONITOR = None
SERVICE = None

def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'}:
        GUARD['blocked_outbound_attempts'] += 1
        raise PermissionError('Patcwatch offline guard blocked ' + event)

def save_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.patcwatch-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

class Detector:
    def __init__(self):
        self.seen = {}

    def read(self, capture):
        if capture.get('status') != 'OK':
            return {'decision': 'UNAVAILABLE', 'drafts': [], 'detail': 'Last successful content retained.'}
        messages = capture.get('messages')
        if not isinstance(messages, list) or len(messages) > 10000:
            raise ValueError('messages must be a list')
        validated = []
        ids = set()
        for m in messages:
            if not isinstance(m, dict) or not isinstance(m.get('id'), str) or not isinstance(m.get('text'), str) or not m['id'] or m['id'] in ids:
                raise ValueError('Unique nonempty message IDs and text are required')
            ids.add(m['id'])
            validated.append((m['id'], m['text'], hashlib.sha256(m['text'].encode()).hexdigest()))
        drafts = []
        for ident, text, digest in validated:
            old = self.seen.get(ident)
            if old is not None and old != digest:
                drafts.append({'id': ident, 'text': 'Changed feedback for ' + ident + ':\n\n' + text + '\n\nReview required. No fix or verification is implied.'})
            elif old is None and self.seen:
                drafts.append({'id': ident, 'text': 'New feedback for ' + ident + ':\n\n' + text + '\n\nReview required.'})
        if len(set(self.seen) | ids) > 10000:
            raise ValueError('Source exceeds 10000 unique message IDs')
        first = not self.seen
        self.seen.update({i: h for i, t, h in validated})
        return {'decision': 'BASELINE' if first else 'CHANGED' if drafts else 'UNCHANGED', 'drafts': drafts, 'detail': 'Rendered messages only; missing items are not deletions.'}

class Monitor:
    def __init__(self, source, data):
        self.source = source.resolve()
        self.path = data / 'monitor.json'
        self.lock = threading.Lock()
        self.detector = Detector()
        self.saved = {'source': str(self.source), 'seen': {}, 'drafts': [], 'status': 'WAITING'}
        if self.path.exists():
            loaded = json.loads(self.path.read_text())
            if loaded.get('source') != str(self.source):
                raise ValueError('This data directory belongs to another source; use --data-dir for a new source.')
            self.saved = loaded
            self.detector.seen = loaded['seen']

    def check(self):
        with self.lock:
            now = datetime.now(timezone.utc).isoformat()
            before = dict(self.detector.seen)
            try:
                with self.source.open('rb') as stream:
                    raw = stream.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError('Source exceeds 2 MB')
                capture = json.loads(raw)
                if not isinstance(capture, dict):
                    raise ValueError('Capture must be an object')
                result = self.detector.read(capture)
            except (OSError, ValueError, TypeError, UnicodeError):
                result = {'decision': 'UNAVAILABLE', 'drafts': [], 'detail': 'Source missing, unreadable or invalid; previous state retained.'}
            saved = {**self.saved, 'seen': dict(self.detector.seen), 'status': result['decision'],
                'last_attempt': now, 'detail': result['detail'], 'model_calls': 0,
                'drafts': (self.saved['drafts'] + [{**d, 'observed_at': now} for d in result['drafts']])[-200:]}
            if result['decision'] != 'UNAVAILABLE':
                saved['last_success'] = now
            try:
                save_json(self.path, saved)
            except OSError:
                self.detector.seen = before
                raise
            self.saved = saved
            return {k: v for k, v in saved.items() if k != 'seen'}

    def snapshot(self):
        with self.lock:
            return {k: v for k, v in self.saved.items() if k != 'seen'}


def experiment():
    with LOCK:
        blocked_before = GUARD['blocked_outbound_attempts']
        detector = Detector()
        cases = json.loads((ROOT / 'samples.json').read_text())
        rows = []
        for case in cases:
            result = detector.read(case['capture'])
            rows.append({'name': case['name'], 'expected': case['expected'], **result, 'pass': result['decision'] == case['expected']})
        # Real outbound attempt, intercepted before any network connection occurs.
        blocked = False
        with socket.socket() as sock:
            try:
                sock.connect(('127.0.0.1', 9))
            except PermissionError:
                blocked = True
        report = {'name': 'Patcwatch offline experiment', 'at': datetime.now(timezone.utc).isoformat(),
            'mode': 'SYNTHETIC LOCAL FILE REPLAY', 'passed': all(r['pass'] for r in rows) and blocked,
            'checks': rows, 'model_calls': 0, 'outbound_connections': 0,
            'network_guard_test': 'PASS' if blocked else 'FAIL',
            'blocked_attempts': GUARD['blocked_outbound_attempts'] - blocked_before,
            'sample_sha256': hashlib.sha256((ROOT / 'samples.json').read_bytes()).hexdigest(),
            'limits': 'No live Teams/Jira reader or Codex dispatch. Model calls used to build this app are excluded. Drafts use fixed templates. The Python audit guard is an experiment control, not an OS sandbox.'}
        save_json(DATA / 'latest.json', report)
        return report

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, body, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return self.headers.get('Host') == '127.0.0.1:' + str(self.server.server_port)

    def do_GET(self):
        if not self.valid_host():
            self.send(403, b'Loopback host required', 'text/plain'); return
        if self.path == '/':
            self.send(200, (ROOT / ('service.html' if SERVICE else 'index.html')).read_bytes(), 'text/html; charset=utf-8')
        elif self.path == '/api/service':
            self.send(200, json.dumps(SERVICE.status() if SERVICE else None).encode(), 'application/json')
        elif self.path == '/api/monitor':
            self.send(200, json.dumps(MONITOR.snapshot() if MONITOR else None).encode(), 'application/json')
        elif self.path == '/api/report':
            p = DATA / 'latest.json'
            self.send(200, p.read_bytes() if p.exists() else b'null', 'application/json')
        else:
            self.send(404, b'Not found', 'text/plain')

    def do_POST(self):
        if not self.valid_host():
            self.send(403, b'Loopback host required', 'text/plain'); return
        if SERVICE and self.path in ('/api/experiment','/api/check'):
            self.send(404,b'Use scheduler test', 'text/plain'); return
        if self.path not in ('/api/experiment', '/api/check') and not (SERVICE and self.path.startswith('/api/service/')):
            self.send(404, b'Not found', 'text/plain'); return
        expected = 'http://127.0.0.1:' + str(self.server.server_port)
        if self.headers.get('Origin') != expected or self.headers.get('X-Patcwatch') != 'local-ui':
            self.send(403, b'Local UI only', 'text/plain'); return
        try:
            if SERVICE and self.path.startswith('/api/service/'):
                size = int(self.headers.get('Content-Length','0'))
                if size < 0 or size > 32768: raise ValueError('Request too large')
                body = json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(body,dict): raise ValueError('Expected JSON object')
                result = SERVICE.action(self.path.removeprefix('/api/service/'), body)
                self.send(200,json.dumps(result).encode(),'application/json'); return
            if self.path == '/api/check' and MONITOR is None:
                self.send(409, b'{"error":"Start with --watch FILE"}', 'application/json'); return
            report = MONITOR.check() if self.path == '/api/check' else experiment()
            self.send(200, json.dumps(report).encode(), 'application/json')
        except (ValueError, OSError, KeyError) as exc:
            message = str(exc) if isinstance(exc,ValueError) else 'Local configuration or storage error'
            self.send(400, json.dumps({'error':message}).encode(), 'application/json')
        except Exception as exc:
            from .scheduler import SourceError
            message = exc.status if isinstance(exc,SourceError) else 'Request failed; check configuration and Microsoft permissions.'
            self.send(503,json.dumps({'error':message}).encode(),'application/json')

def main():
    global DATA, MONITOR, SERVICE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DATA, help='Private state directory (default: ~/.patcwatch)')
    parser.add_argument('--background', choices=('install','status','uninstall'), help='Manage the macOS background Microsoft service')
    parser.add_argument('--microsoft', action='store_true', help='Microsoft sign-in, Teams and SharePoint service UI')
    parser.add_argument('--interval', type=int, default=300, help='Microsoft source polling interval in seconds (30 minimum)')
    parser.add_argument('--scheduler-test', action='store_true', help='Run the larger isolated scheduler benchmark')
    parser.add_argument('--watch', type=Path, help='Watch a local JSON feedback file every five seconds')
    parser.add_argument('--version', action='version', version='Patcwatch 0.2.0')
    parser.add_argument('--experiment', action='store_true', help='Run the offline experiment and exit')
    parser.add_argument('--port', type=int, default=8793)
    args = parser.parse_args()
    DATA = args.data_dir.expanduser().resolve()
    if args.scheduler_test:
        from .benchmark import run
        result = run(DATA / 'scheduler-test.json')
        print(json.dumps(result,indent=2));sys.exit(0 if result['passed'] else 1)
    if args.microsoft and (args.watch or args.experiment):
        parser.error('--microsoft cannot be combined with --watch or --experiment')
    if args.interval < 30: parser.error('--interval must be at least 30 seconds')
    if not 1 <= args.port <= 65535: parser.error('--port must be 1–65535')
    if args.background:
        from .background import manage
        try: manage(args.background, DATA, args.port, args.interval)
        except (ValueError,OSError) as exc: parser.exit(1,str(exc)+'\n')
        return
    if args.microsoft:
        from .service import Service
        try: SERVICE = Service(DATA,args.interval)
        except (RuntimeError,OSError,ValueError): parser.exit(1,'Cannot start service. Check data directory ownership and configuration.\n')
    else:
        sys.addaudithook(audit)
    if args.experiment:
        result = experiment()
        print(json.dumps(result, indent=2))
        sys.exit(0 if result['passed'] else 1)
    if args.watch:
        try:
            MONITOR = Monitor(args.watch.expanduser(), DATA)
            MONITOR.check()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            parser.exit(1, 'Cannot load monitor state: ' + str(exc) + '\n')
    stop = threading.Event()
    def poll():
        while not stop.wait(5):
            try:
                MONITOR.check()
            except OSError:
                print('Cannot save monitor state; check disk space and permissions.', file=sys.stderr)
    if MONITOR:
        threading.Thread(target=poll, daemon=True).start()
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except OSError as exc:
        parser.exit(1, 'Cannot start Patcwatch. Try a different --port. ' + str(exc) + '\n')
    print('Patcwatch: http://127.0.0.1:' + str(args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        if SERVICE:SERVICE.close()
