"""
society/store.py — persistence for the Society.

Backends:
  * Supabase (production) when SUPABASE_URL + a key are set AND the soc_* tables exist
    (run society/schema.sql once in the Supabase SQL editor).
  * SQLite (local dev / fallback). On Render's free tier the disk is ephemeral,
    so SQLite data is lost on every redeploy — use Supabase for anything you keep.

The schema is defined once, here, and schema.sql is generated from it
(python -m society.store > society/schema.sql).
"""
import os, json, uuid, sqlite3, threading, logging
from datetime import datetime, timezone

log = logging.getLogger('society.store')

# col -> sql type.  'id' is always the text primary key.
SCHEMA = {
    'soc_agents': dict(
        name='text', status='text', generation='integer', parents='text', voice='text',
        backstory='text', genome='text', energy='double precision', profession='text',
        domain_xp='text', born_tick='integer', born_at='text', retired_at='text',
        fitness='double precision', color='text'),
    'soc_messages': dict(
        ts='text', tick='integer', sender='text', recipient='text', kind='text',
        body='text', read='integer', meta='text'),
    'soc_relationships': dict(
        pair='text', a='text', b='text', affinity='double precision', kind='text',
        interactions='integer', updated_at='text'),
    'soc_findings': dict(
        ts='text', tick='integer', agent='text', kind='text', domain='text', title='text',
        body='text', sources='text', confidence='double precision', reviews='text',
        review_avg='double precision', review_count='integer', reactions='text',
        sil_score='double precision'),
    'soc_memories': dict(ts='text', agent='text', text='text', importance='integer'),
    'soc_events': dict(ts='text', tick='integer', agent='text', type='text', text='text', meta='text'),
    'soc_world': dict(value='text'),
}

JSON_COLS = {
    'soc_agents': {'parents': [], 'genome': {}, 'domain_xp': {}},
    'soc_messages': {'meta': {}},
    'soc_findings': {'sources': [], 'reviews': [], 'reactions': {}},
    'soc_events': {'meta': {}},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def ddl_sqlite() -> list:
    out = []
    for t, cols in SCHEMA.items():
        body = ', '.join(['id TEXT PRIMARY KEY'] + [
            f'"{c}" ' + ('REAL' if ty.startswith('double') else 'INTEGER' if ty == 'integer' else 'TEXT')
            for c, ty in cols.items()])
        out.append(f'CREATE TABLE IF NOT EXISTS {t} ({body})')
    out.append('CREATE INDEX IF NOT EXISTS i_ev_ts ON soc_events(ts)')
    out.append('CREATE INDEX IF NOT EXISTS i_msg_rcpt ON soc_messages(recipient, read)')
    out.append('CREATE INDEX IF NOT EXISTS i_find_agent ON soc_findings(agent)')
    return out


def ddl_postgres() -> str:
    lines = ['-- Signal Society V2 tables. Run once in the Supabase SQL editor.', '']
    for t, cols in SCHEMA.items():
        body = ',\n  '.join(['id text primary key'] + [f'"{c}" {ty}' for c, ty in cols.items()])
        lines.append(f'create table if not exists {t} (\n  {body}\n);')
        lines.append(f'alter table {t} disable row level security;')
        lines.append('')
    lines.append('create index if not exists i_ev_ts on soc_events(ts);')
    lines.append('create index if not exists i_msg_rcpt on soc_messages(recipient, read);')
    lines.append('create index if not exists i_find_agent on soc_findings(agent);')
    return '\n'.join(lines)


class Store:
    def __init__(self):
        self.backend = 'sqlite'
        self.fallback_reason = ''
        self._lock = threading.RLock()
        self._sb = None
        self._db = None
        url = os.environ.get('SUPABASE_URL', '').strip()
        key = (os.environ.get('SUPABASE_SERVICE_KEY') or os.environ.get('SUPABASE_KEY')
               or os.environ.get('SUPABASE_ANON_KEY') or '').strip()
        if url and key and os.environ.get('SOC_FORCE_SQLITE', '0') != '1':
            try:
                from supabase import create_client
                client = create_client(url, key)
                client.table('soc_world').select('id').limit(1).execute()
                self._sb = client
                self.backend = 'supabase'
            except Exception as e:  # tables missing, bad key, no package...
                self.fallback_reason = f'{type(e).__name__}: {str(e)[:160]}'
                log.warning(f'Supabase unavailable for Society ({self.fallback_reason}) — using SQLite')
        if self._sb is None:
            path = os.environ.get('SOC_DB_PATH', 'society.db')
            self._db = sqlite3.connect(path, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            for stmt in ddl_sqlite():
                self._db.execute(stmt)
            self._db.commit()
        log.info(f'Society store backend: {self.backend}')

    # ── json helpers ──────────────────────────────────────────────────────────
    def _enc(self, table, row):
        row = dict(row)
        for c in JSON_COLS.get(table, {}):
            if c in row and not isinstance(row[c], str):
                row[c] = json.dumps(row[c])
        return row

    def _dec(self, table, row):
        row = dict(row)
        for c, default in JSON_COLS.get(table, {}).items():
            v = row.get(c)
            if isinstance(v, str) and v:
                try:
                    row[c] = json.loads(v)
                except Exception:
                    row[c] = type(default)()
            elif v is None or v == '':
                row[c] = type(default)()
        return row

    # ── sqlite where builder ──────────────────────────────────────────────────
    @staticmethod
    def _sql_where(where):
        if not where:
            return '', []
        parts, args = [], []
        for k, v in where.items():
            op, val = ('=', v) if not isinstance(v, tuple) else v
            if op == 'in':
                if not val:
                    parts.append('1=0')
                    continue
                parts.append(f'"{k}" IN ({",".join("?" * len(val))})')
                args.extend(val)
            else:
                parts.append(f'"{k}" {op} ?')
                args.append(val)
        return ' WHERE ' + ' AND '.join(parts), args

    # ── public api ────────────────────────────────────────────────────────────
    def insert(self, table, row):
        row = dict(row)
        row.setdefault('id', new_id())
        enc = self._enc(table, row)
        with self._lock:
            if self._sb:
                self._sb.table(table).insert(enc).execute()
            else:
                cols = list(enc.keys())
                self._db.execute(
                    f'INSERT INTO {table} ({",".join(chr(34)+c+chr(34) for c in cols)}) '
                    f'VALUES ({",".join("?" * len(cols))})', [enc[c] for c in cols])
                self._db.commit()
        return row

    def update(self, table, where, fields):
        fields = self._enc(table, fields)
        if not fields:
            return
        with self._lock:
            if self._sb:
                q = self._sb.table(table).update(fields)
                for k, v in where.items():
                    q = self._sb_filter(q, k, v)
                q.execute()
            else:
                w, a = self._sql_where(where)
                sets = ','.join(f'"{c}"=?' for c in fields)
                self._db.execute(f'UPDATE {table} SET {sets}{w}', list(fields.values()) + a)
                self._db.commit()

    def select(self, table, where=None, order=None, limit=None):
        """order: 'col' (asc) or '-col' (desc)."""
        with self._lock:
            if self._sb:
                q = self._sb.table(table).select('*')
                for k, v in (where or {}).items():
                    q = self._sb_filter(q, k, v)
                if order:
                    q = q.order(order.lstrip('-'), desc=order.startswith('-'))
                if limit:
                    q = q.limit(limit)
                rows = q.execute().data or []
            else:
                w, a = self._sql_where(where)
                sql = f'SELECT * FROM {table}{w}'
                if order:
                    sql += f' ORDER BY "{order.lstrip("-")}" {"DESC" if order.startswith("-") else "ASC"}'
                if limit:
                    sql += f' LIMIT {int(limit)}'
                rows = [dict(r) for r in self._db.execute(sql, a).fetchall()]
        return [self._dec(table, r) for r in rows]

    def get(self, table, id_):
        rows = self.select(table, {'id': id_}, limit=1)
        return rows[0] if rows else None

    def delete(self, table, where):
        with self._lock:
            if self._sb:
                q = self._sb.table(table).delete()
                for k, v in where.items():
                    q = self._sb_filter(q, k, v)
                q.execute()
            else:
                w, a = self._sql_where(where)
                self._db.execute(f'DELETE FROM {table}{w}', a)
                self._db.commit()

    @staticmethod
    def _sb_filter(q, k, v):
        op, val = ('=', v) if not isinstance(v, tuple) else v
        return {'=': q.eq, '>': q.gt, '<': q.lt, '>=': q.gte, '<=': q.lte,
                '!=': q.neq, 'in': q.in_}[op](k, val)

    # ── convenience ───────────────────────────────────────────────────────────
    def world_get(self, key, default=None):
        row = self.get('soc_world', key)
        return row['value'] if row else default

    def world_set(self, key, value):
        if self.get('soc_world', key):
            self.update('soc_world', {'id': key}, {'value': str(value)})
        else:
            self.insert('soc_world', {'id': key, 'value': str(value)})

    def event(self, tick, agent, type_, text, meta=None):
        return self.insert('soc_events', dict(ts=now_iso(), tick=tick, agent=agent or '',
                                              type=type_, text=text, meta=meta or {}))

    def remember(self, agent_id, text, importance=1):
        self.insert('soc_memories', dict(ts=now_iso(), agent=agent_id, text=text[:300], importance=importance))


_store = None
_store_lock = threading.Lock()


def get_store() -> Store:
    global _store
    with _store_lock:
        if _store is None:
            _store = Store()
        return _store


if __name__ == '__main__':
    print(ddl_postgres())
