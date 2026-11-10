"""Single logical SQLite writer on the event loop; transactions contain no await.

An OS lock rejects concurrent orchestrators for one DB. WAL readers are possible.
Successful stages commit before downstream scheduling. Billing is at-least-once.
"""
import fcntl
import json
import math
import sqlite3
import time
from pathlib import Path
from .common import dumps, digest, now


class BudgetExhausted(Exception):
    pass


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = open(str(path) + '.lock', 'a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise ValueError('another writer owns this database') from None
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=FULL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS runs(
          run_id TEXT PRIMARY KEY, manifest TEXT NOT NULL, fingerprint TEXT NOT NULL,
          config TEXT NOT NULL, status TEXT NOT NULL, ceiling REAL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS inputs(
          run_id TEXT, input_id TEXT, input_index INTEGER, body TEXT NOT NULL,
          PRIMARY KEY(run_id,input_id), UNIQUE(run_id,input_index));
        CREATE TABLE IF NOT EXISTS jobs(
          run_id TEXT, input_id TEXT, state TEXT NOT NULL, updated_at TEXT,
          PRIMARY KEY(run_id,input_id));
        CREATE TABLE IF NOT EXISTS stage_results(
          run_id TEXT, input_id TEXT, stage INTEGER, status TEXT, result TEXT, cache_key TEXT,
          metadata TEXT, created_at TEXT, PRIMARY KEY(run_id,input_id,stage));
        CREATE TABLE IF NOT EXISTS stage_attempts(
          attempt_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, input_id TEXT, stage INTEGER,
          status TEXT, estimated_cost REAL, actual_cost REAL, input_tokens INTEGER,
          output_tokens INTEGER, reasoning_tokens INTEGER, cached_tokens INTEGER,
          estimated_input INTEGER, estimated_output INTEGER, started REAL, latency REAL,
          error TEXT, provider_model TEXT, response_content TEXT);
        CREATE TABLE IF NOT EXISTS decisions(
          run_id TEXT, input_id TEXT, result TEXT, PRIMARY KEY(run_id,input_id));
        CREATE TABLE IF NOT EXISTS reviews(
          run_id TEXT, input_id TEXT, status TEXT, reasons TEXT, PRIMARY KEY(run_id,input_id));
        CREATE TABLE IF NOT EXISTS events(
          id INTEGER PRIMARY KEY, run_id TEXT, input_id TEXT, event TEXT, data TEXT, at TEXT);
        CREATE TABLE IF NOT EXISTS cache(
          key TEXT PRIMARY KEY, stage INTEGER, result TEXT, origin_run TEXT, origin_input TEXT);
        CREATE TABLE IF NOT EXISTS exports(
          run_id TEXT, status TEXT, manifest TEXT, at TEXT, PRIMARY KEY(run_id,status));
        CREATE TABLE IF NOT EXISTS human_reviews(
          run_id TEXT, input_id TEXT, decision TEXT, PRIMARY KEY(run_id,input_id));
        CREATE INDEX IF NOT EXISTS attempts_run ON stage_attempts(run_id,input_id,stage);
        ''')
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(stage_attempts)')}
        if 'response_content' not in columns:
            self.db.execute('ALTER TABLE stage_attempts ADD COLUMN response_content TEXT')
            self.db.commit()
        if 'elapsed_seconds' not in {r[1] for r in self.db.execute('PRAGMA table_info(runs)')}:
            self.db.execute('ALTER TABLE runs ADD COLUMN elapsed_seconds REAL NOT NULL DEFAULT 0')
            self.db.commit()

    def close(self):
        self.db.close()
        self.lock.close()

    def event(self, run, event, data, input_id=None):
        with self.db:
            self.db.execute('INSERT INTO events(run_id,input_id,event,data,at) VALUES(?,?,?,?,?)',
                            (run, input_id, event, dumps(data), now()))

    def create_run(self, run, manifest, config):
        with self.db:
            self.db.execute('INSERT INTO runs(run_id,manifest,fingerprint,config,status,ceiling,created_at) VALUES(?,?,?,?,?,?,?)',
                            (run, dumps(manifest), digest(manifest), dumps(config.model_dump(mode='json')),
                             'ingesting', config.run.max_spend, now()))

    def run(self, run):
        row = self.db.execute('SELECT * FROM runs WHERE run_id=?', (run,)).fetchone()
        if row is None:
            raise ValueError('unknown run_id')
        return dict(row)

    def set_status(self, run, status):
        with self.db:
            self.db.execute('UPDATE runs SET status=? WHERE run_id=?', (status, run))

    def raise_budget(self, run, ceiling):
        if not math.isfinite(ceiling) or ceiling <= 0:
            raise ValueError('budget ceiling must be finite and positive')
        old = self.run(run)['ceiling']
        if old is None or ceiling <= old:
            raise ValueError('new ceiling must exceed previous explicit budget')
        with self.db:
            self.db.execute('UPDATE runs SET ceiling=? WHERE run_id=?', (ceiling, run))
        self.event(run, 'budget_increased', {'old': old, 'new': ceiling})

    def ingest(self, run, records):
        # One atomic ingest: an interrupted read never leaves a partial population.
        with self.db:
            for i, row in enumerate(records):
                self.db.execute('INSERT INTO inputs VALUES(?,?,?,?)', (run, row['id'], i, dumps(row)))
                self.db.execute('INSERT INTO jobs VALUES(?,?,?,?)', (run, row['id'], 'queued', now()))
        self.set_status(run, 'ready')

    def items(self, run, pending=False):
        query = 'SELECT i.* FROM inputs i'
        if pending:
            query += ' LEFT JOIN decisions d ON i.run_id=d.run_id AND i.input_id=d.input_id'
        query += ' WHERE i.run_id=?'
        if pending:
            query += ' AND d.input_id IS NULL'
        query += ' ORDER BY i.input_index'
        for r in self.db.execute(query, (run,)):
            yield json.loads(r['body'])

    def state(self, run, item, state):
        with self.db:
            self.db.execute('UPDATE jobs SET state=?,updated_at=? WHERE run_id=? AND input_id=?', (state, now(), run, item))

    def stage(self, run, item, stage):
        r = self.db.execute('SELECT * FROM stage_results WHERE run_id=? AND input_id=? AND stage=?', (run, item, stage)).fetchone()
        if r:
            return dict(status=r['status'], result=json.loads(r['result']), metadata=json.loads(r['metadata']))

    def commit_stage(self, run, item, stage, status, result, key, metadata):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO stage_results VALUES(?,?,?,?,?,?,?,?)',
                            (run, item, stage, status, dumps(result), key, dumps(metadata), now()))
            self.db.execute('UPDATE jobs SET state=?,updated_at=? WHERE run_id=? AND input_id=?',
                            (f'stage{stage}_{status}', now(), run, item))
            if status == 'success':
                self.db.execute('INSERT OR IGNORE INTO cache VALUES(?,?,?,?,?)', (key, stage, dumps(result), run, item))

    def cached(self, key):
        r = self.db.execute('SELECT * FROM cache WHERE key=?', (key,)).fetchone()
        return dict(r) if r else None

    def counters(self, run, item, stage):
        rows = self.db.execute('SELECT status,error FROM stage_attempts WHERE run_id=? AND input_id=? AND stage=?', (run, item, stage)).fetchall()
        return {'format_errors': sum(r['status'] == 'format_error' for r in rows),
                'transport_errors': sum(r['status'] in ('transport_error', 'reserved') for r in rows),
                'calls': len(rows), 'last_error': rows[-1]['error'] if rows else None}

    def cost(self, run):
        r = self.db.execute('SELECT COALESCE(SUM(COALESCE(actual_cost,estimated_cost)),0), '
                            'COALESCE(SUM(actual_cost),0), COALESCE(SUM(CASE WHEN actual_cost IS NULL THEN estimated_cost ELSE 0 END),0) '
                            'FROM stage_attempts WHERE run_id=?', (run,)).fetchone()
        return dict(conservative_spend=r[0], usage_based_cost=r[1], unknown_reservations=r[2])

    def reserve(self, run, item, stage, estimated_input, estimated_output, cost):
        ceiling = self.run(run)['ceiling']
        if ceiling is not None and self.cost(run)['conservative_spend'] + cost > ceiling + 1e-12:
            raise BudgetExhausted()
        with self.db:
            r = self.db.execute('INSERT INTO stage_attempts(run_id,input_id,stage,status,estimated_cost,estimated_input,estimated_output,started) VALUES(?,?,?,?,?,?,?,?)',
                                (run, item, stage, 'reserved', cost, estimated_input, estimated_output, time.time()))
        return r.lastrowid

    def settle(self, attempt, response, latency, config):
        actual = None
        if response.input_tokens is not None and response.output_tokens is not None:
            actual = (response.input_tokens * config.input_price_per_million + response.output_tokens * config.output_price_per_million) / 1e6
        with self.db:
            self.db.execute('UPDATE stage_attempts SET actual_cost=?,input_tokens=?,output_tokens=?,reasoning_tokens=?,cached_tokens=?,latency=?,provider_model=?,response_content=? WHERE attempt_id=?',
                            (actual, response.input_tokens, response.output_tokens, response.reasoning_tokens,
                             response.cached_tokens, latency, response.model, response.content, attempt))

    def attempt_status(self, attempt, status, error=None, latency=None):
        with self.db:
            self.db.execute('UPDATE stage_attempts SET status=?,error=?,latency=COALESCE(?,latency) WHERE attempt_id=?', (status, error, latency, attempt))

    def commit_decision(self, run, item, result):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO decisions VALUES(?,?,?)', (run, item, dumps(result)))
            self.db.execute('INSERT OR IGNORE INTO reviews VALUES(?,?,?,?)', (run, item, result['review_status'], dumps(result['review_reasons'])))
            self.db.execute('UPDATE jobs SET state=?,updated_at=? WHERE run_id=? AND input_id=?', (result['review_status'], now(), run, item))

    def results(self, run):
        for row in self.db.execute('SELECT i.body,d.result FROM inputs i JOIN decisions d USING(run_id,input_id) WHERE i.run_id=? ORDER BY i.input_index', (run,)):
            yield {**json.loads(row['result']), 'input': json.loads(row['body'])}
