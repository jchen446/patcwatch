"""Patcwatch: local, deterministic feedback experiment. Python stdlib only."""
import argparse
import hashlib
import json
import socket
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
GUARD = {'blocked_outbound_attempts': 0}
LOCK = threading.Lock()

def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'}:
        GUARD['blocked_outbound_attempts'] += 1
        raise PermissionError('Patcwatch offline guard blocked ' + event)

class Detector:
    def __init__(self):
        self.seen = {}

    def read(self, capture):
        if capture.get('status') != 'OK':
            return {'decision': 'UNAVAILABLE', 'drafts': [], 'detail': 'Last successful content retained.'}
        messages = capture.get('messages')
        if not isinstance(messages, list):
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
        first = not self.seen
        self.seen.update({i: h for i, t, h in validated})
        return {'decision': 'BASELINE' if first else 'CHANGED' if drafts else 'UNCHANGED', 'drafts': drafts, 'detail': 'Rendered messages only; missing items are not deletions.'}

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
        out = ROOT / '.local'
        out.mkdir(mode=0o700, exist_ok=True)
        p = out / 'latest.json'
        p.write_text(json.dumps(report, indent=2))
        p.chmod(0o600)
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

    def do_GET(self):
        if self.path == '/':
            self.send(200, (ROOT / 'index.html').read_bytes(), 'text/html; charset=utf-8')
        elif self.path == '/api/report':
            p = ROOT / '.local/latest.json'
            self.send(200, p.read_bytes() if p.exists() else b'null', 'application/json')
        else:
            self.send(404, b'Not found', 'text/plain')

    def do_POST(self):
        if self.path != '/api/experiment':
            self.send(404, b'Not found', 'text/plain'); return
        expected = 'http://127.0.0.1:' + str(self.server.server_port)
        if self.headers.get('Origin') != expected or self.headers.get('X-Patcwatch') != 'local-ui':
            self.send(403, b'Local UI only', 'text/plain'); return
        try:
            report = experiment()
            self.send(200, json.dumps(report).encode(), 'application/json')
        except (ValueError, OSError) as exc:
            self.send(500, json.dumps({'error': str(exc)}).encode(), 'application/json')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', action='store_true', help='Run the offline experiment and exit')
    parser.add_argument('--port', type=int, default=8793)
    args = parser.parse_args()
    sys.addaudithook(audit)
    if args.experiment:
        result = experiment()
        print(json.dumps(result, indent=2))
        sys.exit(0 if result['passed'] else 1)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print('Patcwatch: http://127.0.0.1:' + str(args.port), flush=True)
    server.serve_forever()
