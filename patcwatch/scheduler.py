"""Durable single-host polling. No model or browser dependency."""
import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path


class SourceError(Exception):
    def __init__(self, status, retry_after=0):
        self.status = status
        self.retry_after = max(0, float(retry_after))
        super().__init__(status)


class ProcessLock:
    """Hold one OS lock for the process lifetime; time never unlocks a live owner."""
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.file = open(directory / 'service.lock', 'a+b')
        self.file.seek(0)
        self.file.write(b'0')
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('Patcwatch is already using this data directory') from None

    def close(self):
        self.file.close()


class Store:
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'service.sqlite3'
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.path.chmod(0o600)
        self.lock = threading.RLock()
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS source (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, label TEXT NOT NULL,
                config TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                initialized INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'WAITING', last_attempt REAL,
                last_success REAL, next_due REAL NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0, reads INTEGER NOT NULL DEFAULT 0,
                cursor TEXT NOT NULL DEFAULT '{}', coverage TEXT NOT NULL DEFAULT 'UNVERIFIED');
            CREATE TABLE IF NOT EXISTS seen (
                source_id TEXT NOT NULL, native_id TEXT NOT NULL, digest TEXT NOT NULL,
                PRIMARY KEY(source_id,native_id));
            CREATE TABLE IF NOT EXISTS event (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL,
                native_id TEXT NOT NULL, observed_at REAL NOT NULL, kind TEXT NOT NULL,
                content TEXT NOT NULL, digest TEXT NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0);
        ''')
        self.db.commit()

    def add(self, kind, label, config):
        # Include row mapping in source identity. Changing mapping establishes a new baseline.
        encoded = json.dumps(config, sort_keys=True)
        ident = hashlib.sha256((kind + encoded).encode()).hexdigest()[:24]
        with self.lock, self.db:
            self.db.execute('INSERT OR IGNORE INTO source(id,kind,label,config) VALUES(?,?,?,?)',
                            (ident, kind, label, encoded))
        return ident

    def sources(self):
        with self.lock:
            result = [dict(r) for r in self.db.execute('SELECT * FROM source ORDER BY rowid')]
        for s in result:
            s['config'] = json.loads(s['config'])
            s['cursor'] = json.loads(s['cursor'])
        return result

    def enabled(self, ident, value):
        with self.lock, self.db:
            self.db.execute('UPDATE source SET enabled=? WHERE id=?', (int(value), ident))

    def review(self, ident):
        with self.lock, self.db:
            self.db.execute('UPDATE event SET reviewed=1 WHERE id=?', (ident,))

    def events(self):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT * FROM event ORDER BY id DESC LIMIT 200')]

    def close(self):
        self.db.close()


class Scheduler:
    def __init__(self, store, collector, interval=300, clock=time.time):
        self.store, self.collector = store, collector
        self.interval, self.clock = interval, clock
        self.tick_lock = threading.Lock()
        self.stop = threading.Event()
        self.fatal = None

    def tick(self):
        if not self.tick_lock.acquire(blocking=False):
            return 0
        count = 0
        try:
            for source in self.store.sources():
                if self.stop.is_set():
                    break
                now = self.clock()
                if not source['enabled'] or source['next_due'] > now:
                    continue
                count += 1
                try:
                    capture = self.collector.read(source)
                    self.commit(source, capture, self.clock())
                except SourceError as exc:
                    self.fail(source, exc, self.clock())
            return count
        finally:
            self.tick_lock.release()

    def commit(self, source, capture, now):
        if capture.get('complete') is not True:
            raise SourceError('INCOMPLETE')
        items = capture.get('items')
        if not isinstance(items, list) or len(items) > 20000:
            raise SourceError('INCOMPLETE')
        rows, ids = [], set()
        for item in items:
            ident, content = item.get('id'), item.get('content')
            if not isinstance(ident, str) or not ident or ident in ids or not isinstance(content, str) or len(content) > 100000:
                raise SourceError('INVALID_SOURCE')
            ids.add(ident)
            rows.append((ident, content, hashlib.sha256(content.encode()).hexdigest()))
        with self.store.lock, self.store.db:
            db = self.store.db
            # Paused while I/O was running: no commit of that capture.
            if not db.execute('SELECT enabled FROM source WHERE id=?', (source['id'],)).fetchone()[0]:
                return
            for ident, content, digest in rows:
                old = db.execute('SELECT digest FROM seen WHERE source_id=? AND native_id=?', (source['id'], ident)).fetchone()
                if source['initialized'] and (not old or old[0] != digest):
                    db.execute('INSERT INTO event(source_id,native_id,observed_at,kind,content,digest) VALUES(?,?,?,?,?,?)',
                               (source['id'], ident, now, 'CHANGED' if old else 'NEW', content, digest))
                db.execute('INSERT OR REPLACE INTO seen VALUES(?,?,?)', (source['id'], ident, digest))
            db.execute('UPDATE source SET initialized=1,status=?,last_attempt=?,last_success=?,next_due=?,failures=0,reads=reads+1,cursor=?,coverage=? WHERE id=?',
                       ('CHECKED', now, now, now + self.interval, json.dumps(capture.get('cursor', {})), capture.get('coverage', 'BOUNDED'), source['id']))
            # Bounded event retention; seen hashes are kept to preserve deduplication.
            db.execute('DELETE FROM event WHERE id NOT IN (SELECT id FROM event ORDER BY id DESC LIMIT 10000)')

    def fail(self, source, error, now):
        failures = source['failures'] + 1
        delay = max(error.retry_after, (60, 300, 900)[min(failures - 1, 2)])
        with self.store.lock, self.store.db:
            self.store.db.execute('UPDATE source SET status=?,last_attempt=?,next_due=?,failures=? WHERE id=?',
                                  (error.status, now, now + delay, failures, source['id']))

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:
                # Fail closed. UI reports this; no invisible dead scheduler or tight retry loop.
                self.fatal = 'Scheduler stopped after an internal or persistence error. Restart after resolving storage/configuration.'
                self.stop.set()
            self.stop.wait(1)
