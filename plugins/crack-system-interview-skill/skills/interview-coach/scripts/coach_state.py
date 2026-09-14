#!/usr/bin/env python3
# coding: utf-8
"""Private, append-only interview evidence store. No automatic grading."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from datetime import datetime, timezone

# Support both direct CLI execution and standalone host loading.
sys.path.insert(0, str(Path(__file__).resolve().parent))

MODES = {'Learn', 'Practice', 'Mock', 'Review'}
TYPES = {'question', 'self_report', 'coach_example', 'prompted', 'independent'}
STATES = {'needs_check', 'needs_hint', 'independent_today', 'delayed_transfer'}


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def timestamp(value):
    require(nonempty(value), 'timestamp must be a nonempty ISO8601 string')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(parsed.tzinfo is not None, 'timestamp requires timezone')
        return parsed
    except (ValueError, OverflowError):
        raise Invalid('invalid ISO8601 timestamp') from None


def keys(obj, required, optional=()):
    require(isinstance(obj, dict), 'expected an object')
    require(set(required) <= obj.keys() and obj.keys() <= set(required) | set(optional),
            'missing or unsupported fields')


def validate(p):
    keys(p, {'event_id', 'occurred_at', 'mode', 'track', 'competency', 'received', 'evaluation', 'repairs'}, {'context'})
    for name in ('event_id', 'track', 'competency'):
        require(nonempty(p[name]), 'identifiers must be nonempty strings')
    if 'context' in p:
        keys(p['context'], set(), {'material_url', 'position', 'next_action', 'language', 'course_id', 'task_id'})
        require(all(isinstance(v, str) for v in p['context'].values()), 'context values must be strings')
    timestamp(p['occurred_at'])
    require(isinstance(p['mode'], str) and p['mode'] in MODES, 'unsupported mode')
    keys(p['received'], {'transcript'}, {'original_answer', 'hints', 'retry'})
    require(nonempty(p['received']['transcript']), 'received transcript is required')
    for value in p['received'].values():
        require(isinstance(value, str), 'received fields must be strings')
    e = p['evaluation']
    keys(e, {'evidence_type', 'scope', 'dimensions', 'state'}, {'transfer', 'rubric_scores', 'attempt_outcome', 'retest_of'})
    require(isinstance(e['evidence_type'], str) and e['evidence_type'] in TYPES, 'unsupported evidence type')
    require(isinstance(e['scope'], str) and e['scope'] in {'complete', 'incomplete'}, 'unsupported scope')
    require(isinstance(e['state'], str) and e['state'] in STATES, 'unsupported state')
    require(isinstance(e['dimensions'], dict) and bool(e['dimensions']) and
            all(nonempty(k) and nonempty(v) for k, v in e['dimensions'].items()),
            'dimensions must contain named textual assessments')
    if e['state'] in {'independent_today', 'delayed_transfer'}:
        require(e['evidence_type'] == 'independent' and e['scope'] == 'complete',
                'independent state requires complete independent evidence')
        require(nonempty(p['received'].get('original_answer')), 'independent evidence requires original answer')
        require(not p['received'].get('hints', '').strip(), 'hinted answer cannot establish independent evidence')
    if e['state'] == 'delayed_transfer':
        t = e.get('transfer')
        keys(t, {'prior_event_id', 'kind', 'evidence'})
        require(nonempty(t['prior_event_id']) and nonempty(t['evidence']), 'transfer evidence is required')
        require(isinstance(t['kind'], str) and t['kind'] in {'retention', 'transfer'}, 'unsupported transfer kind')
    else:
        require('transfer' not in e, 'transfer fields require delayed_transfer state')
    from coach_metrics import validate_scores
    validate_scores(p, require)
    require(isinstance(p['repairs'], list), 'repairs must be a list')
    targets = set()
    for repair in p['repairs']:
        keys(repair, {'target', 'due_at'}, {'status'})
        require(nonempty(repair['target']), 'repair target must be nonempty')
        timestamp(repair['due_at'])
        require(isinstance(repair.get('status', 'open'), str) and
                repair.get('status', 'open') in {'open', 'resolved'}, 'unsupported repair status')
        require(repair['target'] not in targets, 'duplicate repair target')
        targets.add(repair['target'])


def connect(root):
    # Reject lexical symlinks before resolving, including database sidecars.
    root = Path(os.path.abspath(os.path.expanduser(root)))
    require(not any(p.is_symlink() for p in (root, *root.parents)), 'private root must not traverse symlinks')
    install = Path(__file__).resolve().parents[1]
    installs = [install] + [p for p in install.parents if any(
        (p / marker).exists() for marker in ('.codex-plugin', '.claude-plugin', '.cursor-plugin'))]
    require(not any(root == p or p in root.parents for p in installs),
            'private root must be outside skill or plugin installation')
    require(not any((p / '.git').exists() for p in (root, *root.parents)),
            'private root must be outside source repositories')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(root.is_dir(), 'private root must be a directory')
    require(root.stat().st_uid == os.getuid(), 'private root must be owned by current user')
    os.chmod(root, 0o700)
    db = root / 'coach.sqlite3'
    for suffix in ('', '-journal', '-wal', '-shm'):
        candidate = Path(str(db) + suffix)
        require(not candidate.is_symlink(), 'database files must not be symlinks')
        if candidate.exists():
            require(candidate.is_file() and candidate.stat().st_nlink == 1 and
                    candidate.stat().st_uid == os.getuid(), 'unsafe database file')
            os.chmod(candidate, 0o600)
    # Keep umask restrictive for SQLite journals throughout this short-lived CLI.
    os.umask(0o077)
    conn = sqlite3.connect(db, timeout=30)
    os.chmod(db, 0o600)
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA synchronous=FULL')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL,
            digest TEXT NOT NULL, occurred_at TEXT NOT NULL, mode TEXT NOT NULL,
            track TEXT NOT NULL, competency TEXT NOT NULL, received TEXT NOT NULL, context TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS evaluations (
            event_id TEXT PRIMARY KEY REFERENCES events(event_id), body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS repairs (
            event_id TEXT PRIMARY KEY REFERENCES events(event_id), body TEXT NOT NULL);
    ''')
    from coach_library import schema as library_schema
    library_schema(conn)
    return conn


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def save(conn, p):
    validate(p)
    digest = hashlib.sha256(encode(p).encode()).hexdigest()
    conn.execute('BEGIN IMMEDIATE')
    try:
        existing = conn.execute('SELECT digest FROM events WHERE event_id=?', (p['event_id'],)).fetchone()
        if existing:
            require(existing[0] == digest, 'event id conflicts with previously saved content')
            conn.rollback()
            return {'status': 'already_saved', 'event_id': p['event_id']}
        if p['evaluation']['state'] == 'delayed_transfer':
            prior = conn.execute('''SELECT occurred_at,track,competency,body FROM events
                JOIN evaluations USING(event_id) WHERE event_id=?''',
                (p['evaluation']['transfer']['prior_event_id'],)).fetchone()
            require(prior is not None, 'prior independent evidence was not found')
            prior_eval = json.loads(prior[3])
            require(prior[1:3] == (p['track'], p['competency']) and
                    timestamp(prior[0]) < timestamp(p['occurred_at']) and
                    prior_eval['evidence_type'] == 'independent' and prior_eval['scope'] == 'complete' and prior_eval.get('attempt_outcome') != 'not_met' and
                    prior_eval['state'] in {'independent_today', 'delayed_transfer'},
                    'transfer requires earlier independent evidence for same track and competency')
            require(timestamp(prior[0]).astimezone(timezone.utc).date() <
                    timestamp(p['occurred_at']).astimezone(timezone.utc).date(),
                    'delayed transfer requires evidence on a later UTC date')
        if 'retest_of' in p['evaluation']:
            require(not p['evaluation'].get('transfer') or p['evaluation']['transfer']['prior_event_id']==p['evaluation']['retest_of'], 'conflicting retest references')
            prior = conn.execute('''SELECT occurred_at,track,competency,body FROM events
                JOIN evaluations USING(event_id) WHERE event_id=?''', (p['evaluation']['retest_of'],)).fetchone()
            require(prior is not None, 'prior evidence not found')
            ev = json.loads(prior[3])
            require(prior[1:3] == (p['track'],p['competency']) and ev['scope']=='complete' and
                    ev['state'] in {'independent_today','delayed_transfer'} and ev['evidence_type']=='independent' and ev.get('attempt_outcome') != 'not_met', 'retest requires prior independent success')
            require(timestamp(prior[0]).astimezone(timezone.utc).date() < timestamp(p['occurred_at']).astimezone(timezone.utc).date(), 'retest must be on a later UTC day')
        if p.get('context',{}).get('task_id'):
            from coach_courses import catalog, course
            root = Path(conn.execute('PRAGMA database_list').fetchone()[2]).parent
            c = course(catalog(root)[0], p['context'].get('course_id'))
            require(p['context']['task_id'] in {t['task_id'] for w in c['weeks'] for t in w['tasks']}, 'unknown course task')
        conn.execute('''INSERT INTO events(event_id,digest,occurred_at,mode,track,competency,received,context)
            VALUES(?,?,?,?,?,?,?,?)''', (p['event_id'], digest, p['occurred_at'], p['mode'],
                                      p['track'], p['competency'], encode(p['received']), encode(p.get('context', {}))))
        conn.execute('INSERT INTO evaluations VALUES(?,?)', (p['event_id'], encode(p['evaluation'])))
        conn.execute('INSERT INTO repairs VALUES(?,?)', (p['event_id'], encode(p['repairs'])))
        conn.commit()
        return {'status': 'saved', 'event_id': p['event_id']}
    except Exception:
        conn.rollback()
        raise


def resume(conn):
    rows = conn.execute('''SELECT event_id,occurred_at,mode,track,competency,received,
        evaluations.body,repairs.body,context FROM events JOIN evaluations USING(event_id)
        JOIN repairs USING(event_id) ORDER BY seq''').fetchall()
    events = [dict(zip(('event_id', 'occurred_at', 'mode', 'track', 'competency', 'received',
                       'evaluation', 'repairs', 'context'), row)) for row in rows]
    targets, competencies = {}, {}
    for event in events:
        for key in ('received', 'evaluation', 'repairs', 'context'):
            event[key] = json.loads(event[key])
        competency_key = (event['track'], event['competency'])
        if (event['evaluation']['evidence_type'] in {'prompted', 'independent'} or
                competency_key not in competencies):
            competencies[competency_key] = {
                'track': event['track'], 'competency': event['competency'], 'event_id': event['event_id'],
                'occurred_at': event['occurred_at'], 'context': event['context'],
                'evaluation': event['evaluation']}
        if event['evaluation']['state'] == 'delayed_transfer':
            prior_id = event['evaluation']['transfer']['prior_event_id']
            for target in targets.values():
                if target['event_id'] == prior_id:
                    target['status'] = 'resolved'
        for repair in event['repairs']:
            targets[(event['track'], event['competency'], repair['target'])] = {
                **repair, 'track': event['track'], 'competency': event['competency'],
                'event_id': event['event_id']}
    now = datetime.now(timezone.utc)
    pending = [v for v in targets.values() if v.get('status', 'open') == 'open']
    pending.sort(key=lambda v: timestamp(v['due_at']))
    from coach_library import resume_library
    return {'event_count': len(events), 'latest_context': events[-1] if events else None,
            'competencies': list(competencies.values()), 'pending_repairs': pending,
            'due_retests': [v for v in pending if timestamp(v['due_at']) <= now],
            **resume_library(conn)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('save', 'section', 'debrief', 'resume', 'catalog',
                                           'enroll', 'task', 'plan', 'dashboard'))
    parser.add_argument('--root', required=True, help='consistent private directory outside repositories')
    parser.add_argument('--input', help='use - to receive a mutation payload from stdin')
    parser.add_argument('--open', dest='open_dashboard', action='store_true',
                        help='open one in-memory dashboard page (dashboard only)')
    parser.add_argument('--refresh', action='store_true', help='check the public catalog; retain valid cache on failure')
    args = parser.parse_args()
    conn = None
    try:
        require(not args.open_dashboard or args.command=='dashboard', '--open is only valid with dashboard')
        if args.command in {'save','section','debrief','enroll','task','plan'}:
            require(args.input=='-', f'{args.command} requires --input -')
            try:
                payload = json.load(sys.stdin)
            except (OSError, ValueError, UnicodeError):
                raise Invalid('cannot read valid input JSON') from None
            if args.command == 'save': validate(payload)
            elif args.command == 'section':
                from coach_library import validate_section
                validate_section(payload)
            elif args.command == 'debrief':
                from coach_library import validate_debrief
                validate_debrief(payload)
        else:
            require(args.input is None, f'{args.command} does not accept --input')
        conn = connect(args.root)
        root=Path(conn.execute('PRAGMA database_list').fetchone()[2]).parent
        from coach_courses import schema, catalog, enroll, task_event, plan, selected
        schema(conn)
        data, freshness = catalog(args.root, args.refresh)
        if args.command == 'save': result = save(conn, payload)
        elif args.command == 'section':
            from coach_library import save_section
            result = save_section(conn, payload)
        elif args.command == 'debrief':
            from coach_library import save_debrief
            result = save_debrief(conn, payload)
        elif args.command == 'enroll': result = enroll(conn, data, payload)
        elif args.command == 'task': result = task_event(conn, data, payload)
        elif args.command == 'plan': result = plan(conn, data, resume(conn), payload)
        elif args.command == 'catalog': result = {'catalog':data,'freshness':freshness}
        elif args.command == 'resume':
            previous_plan = conn.execute('SELECT body FROM plans ORDER BY seq DESC LIMIT 1').fetchone()
            result = {**resume(conn),'enrollment':selected(conn),'catalog_version':data['version'],
                      'freshness':freshness,'latest_plan':json.loads(previous_plan[0]) if previous_plan else None}
        else:
            result = {'status':'dashboard_ready','event_count':conn.execute('SELECT COUNT(*) FROM events').fetchone()[0],
                      'has_enrollment':selected(conn) is not None,
                      'catalog_version':data['version'],'freshness':freshness}
        from coach_report import remove_legacy_dashboard
        remove_legacy_dashboard(root)
        if args.open_dashboard:
            from coach_report import DASHBOARD_TIMEOUT_SECONDS, serve_dashboard
            serve_dashboard(conn,data,lambda url: print(encode({'status':'dashboard_serving',
                            'dashboard_url':url,'expires_in_seconds':DASHBOARD_TIMEOUT_SECONDS}),flush=True))
        else:
            print(encode(result))
        return 0
    except (Invalid, OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        # Never echo paths, SQL errors, or learner-provided content.
        print('coach_state: input or storage validation failed; check the storage contract', file=sys.stderr)
        return 2
    finally:
        if conn is not None:
            conn.close()


if __name__ == '__main__':
    sys.exit(main())
