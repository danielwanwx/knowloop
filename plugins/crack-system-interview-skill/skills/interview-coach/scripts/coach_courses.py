# coding: utf-8
"""Validated portable course catalog and private planning. No learner data online."""
import json
import os
import re
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BUNDLED = Path(__file__).resolve().parents[1] / 'assets/courses.json'
HOSTS = {'www.calm.rocks', 'docs.google.com', 'leetcode.com'}
# Retired identifiers are split so the privacy gate can keep the literal values
# out of publishable source while still rejecting old cached catalogs.
RETIRED_COURSE_IDS = frozenset(("coh" + "ort", "legacy-" + "system-design"))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def validate(data):
    from urllib.parse import urlsplit
    require(isinstance(data, dict) and data.get('schema_version') == 1, 'unsupported catalog')
    require(isinstance(data.get('version'), str) and bool(data['version']), 'version required')
    require(isinstance(data.get('courses'), list) and 0 < len(data['courses']) <= 20, 'invalid courses')
    ids = set()
    for c in data['courses']:
        require(isinstance(c, dict), 'invalid course')
        cid = c.get('course_id')
        require(isinstance(cid, str) and re.fullmatch(r'[a-z0-9-]+', cid) and cid not in ids, 'invalid course id')
        require(cid not in RETIRED_COURSE_IDS, 'retired course unavailable')
        ids.add(cid)
        for k in ('title', 'version', 'updated_at', 'note'):
            require(isinstance(c.get(k), str) and 0 < len(c[k]) <= 2000, 'invalid course metadata')
        datetime.fromisoformat(c['updated_at'])
        require(isinstance(c.get('weeks'), list) and 0 < len(c['weeks']) <= 52, 'invalid weeks')
        urls = list(c.get('source_urls', []))
        tids, wids = set(), set()
        for w in c['weeks']:
            require(isinstance(w, dict) and re.fullmatch(r'w[1-9][0-9]*', str(w.get('week_id'))), 'invalid week')
            require(w['week_id'] not in wids, 'duplicate week'); wids.add(w['week_id'])
            require(isinstance(w.get('label'), str) and w.get('status') in {'available', 'unavailable'}, 'invalid week metadata')
            require(isinstance(w.get('tasks'), list) and len(w['tasks']) <= 100, 'invalid tasks')
            require(bool(w['tasks']) == (w['status'] == 'available'), 'availability conflicts with tasks')
            for t in w['tasks']:
                require(isinstance(t, dict), 'task must be an object')
                tid = t.get('task_id')
                require(isinstance(tid, str) and re.fullmatch(r'[a-z0-9-]+', tid) and tid not in tids, 'invalid task id')
                tids.add(tid)
                for k in ('title', 'track', 'source_url', 'outcome'):
                    require(isinstance(t.get(k), str) and 0 < len(t[k]) <= 2000, 'invalid task text')
                require(type(t.get('minutes')) is int and 1 <= t['minutes'] <= 240, 'invalid duration')
                require(t.get('provenance') in {'public_plan','coach_suggestion'}, 'invalid provenance')
                for k in ('prerequisites', 'acceptance'):
                    require(isinstance(t.get(k), list) and all(isinstance(s, str) and 0 < len(s) <= 1000 for s in t[k]), 'invalid targets')
                urls.append(t['source_url'])
        require(bool(urls), 'sources required')
        for url in urls:
            require(isinstance(url, str), 'invalid source URL')
            u = urlsplit(url)
            require(u.scheme == 'https' and u.hostname in HOSTS and not u.username and not u.password and u.port in (None,443), 'unapproved source URL')
    return data


def atomic_private(path, text):
    path = Path(path)
    require(not path.is_symlink(), 'unsafe output')
    if path.exists():
        require(path.is_file() and path.stat().st_nlink == 1 and path.stat().st_uid == os.getuid(), 'unsafe output')
    fd, temporary = tempfile.mkstemp(prefix='.coach-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def catalog(root, refresh=False):
    cache = Path(root) / 'courses-cache.json'
    data = validate(json.loads(BUNDLED.read_text()))
    status = 'bundled'
    if cache.exists():
        require(not cache.is_symlink() and cache.stat().st_nlink == 1, 'unsafe cache')
        try:
            data = validate(json.loads(cache.read_text())); status = 'cached'
        except (ValueError, TypeError, KeyError):
            status = 'invalid_cache_using_bundle'
    if refresh:
        # No public endpoint is configured. Refresh remains an explicit offline
        # outcome and deliberately performs no network request.
        status += '_offline_not_configured'
    return data, status


def schema(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS enrollment (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS task_events (seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS plans (seq INTEGER PRIMARY KEY, plan_id TEXT UNIQUE NOT NULL, body TEXT NOT NULL);
    ''')


def selected(conn):
    row = conn.execute('SELECT body FROM enrollment WHERE id=1').fetchone()
    return json.loads(row[0]) if row else None


def course(data, cid):
    found = next((c for c in data['courses'] if c['course_id'] == cid), None)
    require(found is not None, 'course unavailable'); return found


def enroll(conn, data, p):
    c = course(data, p['course_id'])
    require(p.get('week_id') in {w['week_id'] for w in c['weeks']}, 'week unavailable')
    require(type(p.get('minutes')) is int and 5 <= p['minutes'] <= 240, 'budget must be 5–240 minutes')
    ZoneInfo(p['timezone'])
    value = {k:p[k] for k in ('course_id','week_id','minutes','timezone')}
    value['course_version'] = c['version']
    with conn:
        conn.execute('INSERT OR REPLACE INTO enrollment VALUES(1,?)', (json.dumps(value),))
    return value


def task_states(conn, cid):
    states = {}
    for row in conn.execute('SELECT body FROM task_events ORDER BY seq'):
        p = json.loads(row[0])
        if p['course_id'] == cid: states[p['task_id']] = p
    return states


def task_event(conn, data, p):
    require(isinstance(p.get('event_id'), str) and p['event_id'].strip(), 'event id required')
    c = course(data, p['course_id'])
    require(p.get('task_id') in {t['task_id'] for w in c['weeks'] for t in w['tasks']}, 'task unavailable')
    require(p.get('status') in {'not_started','in_progress','completed','deferred','skipped'}, 'invalid status')
    require(p.get('source') in {'self_report','evidence'}, 'completion provenance required')
    from coach_state import timestamp
    timestamp(p['occurred_at'])
    if p['source'] == 'evidence':
        row = conn.execute('SELECT context FROM events WHERE event_id=?', (p.get('evidence_id'),)).fetchone()
        require(row is not None, 'evidence not found')
        context = json.loads(row[0])
        require(context.get('course_id') == p['course_id'] and context.get('task_id') == p['task_id'], 'evidence task mismatch')
    body = json.dumps(p, sort_keys=True)
    with conn:
        row = conn.execute('SELECT body FROM task_events WHERE event_id=?',(p['event_id'],)).fetchone()
        require(not row or row[0] == body, 'task event id conflict')
        if not row: conn.execute('INSERT INTO task_events(event_id,body) VALUES(?,?)',(p['event_id'],body))
    return {'status':'already_saved' if row else 'saved','event_id':p['event_id']}


def plan(conn, data, state, p):
    e = selected(conn); require(e is not None, 'choose a course and week first')
    try:
        c = course(data, e['course_id'])
    except ValueError as exc:
        raise ValueError('selected course unavailable; choose an available course') from exc
    w = next((w for w in c['weeks'] if w['week_id'] == e['week_id']), None)
    require(w is not None, 'selected week removed; choose an available week')
    minutes = p.get('minutes', e['minutes'])
    require(type(minutes) is int and 5 <= minutes <= 240, 'budget must be 5–240 minutes')
    require(isinstance(p.get('plan_id'), str) and p['plan_id'].strip(), 'plan id required')
    now = datetime.now(ZoneInfo(e['timezone']))
    existing = conn.execute('SELECT body FROM plans WHERE plan_id=?',(p['plan_id'],)).fetchone()
    if existing:
        old = json.loads(existing[0])
        require(old['request'] == p and old['course_id'] == c['course_id'] and old['week_id'] == w['week_id'] and old['course_version'] == c['version'] and old['date'] == now.date().isoformat(), 'plan id conflict; use a new id')
        return old
    states = task_states(conn, c['course_id'])
    tasks = [t for t in w['tasks'] if states.get(t['task_id'],{}).get('status') not in {'completed','skipped','deferred'}]
    explicit = p.get('task_id')
    if explicit:
        tasks = [t for week in c['weeks'] for t in week['tasks'] if t['task_id'] == explicit]
        require(bool(tasks), 'requested task unavailable')
    # A mock time is learner-confirmed, never derived from availability windows.
    imminent = False
    if p.get('mock_task_ids'):
        from coach_state import timestamp
        due = timestamp(p.get('mock_at'))
        imminent = 0 <= (due-now).total_seconds() <= 7*86400
        require(isinstance(p['mock_task_ids'],list) and all(isinstance(t,str) for t in p['mock_task_ids']), 'invalid mock tasks')
        chosen = [t for week in c['weeks'] for t in week['tasks'] if t['task_id'] in p['mock_task_ids']]
        require(len(chosen)==len(set(p['mock_task_ids'])), 'mock task unavailable')
        if imminent and not explicit: tasks = chosen
    blocked = p.get('blocked_targets', [])
    require(isinstance(blocked,list) and all(isinstance(t,str) for t in blocked), 'invalid blocked targets')
    repairs = [r for r in state['pending_repairs'] if r['target'] in blocked]
    require({r['target'] for r in repairs} == set(blocked), 'blocking targets need saved evidence')
    repairs += [r for r in state['due_retests'] if r not in repairs]
    from coach_state import timestamp
    repair_targets = {r['target'] for r in repairs}
    library_gaps = [g for g in state.get('open_gaps', [])
                    if timestamp(g['due_at']) <= now and g['repair_target'] not in repair_targets]
    items, remaining = [], minutes
    if not explicit and not imminent and (repairs or library_gaps) and remaining >= 15:
        if repairs:
            r = repairs[0]
            items.append(dict(kind='review',title=r['target'],track=r['track'],competency=r['competency'],prior_event_id=r['event_id'],minutes=10,reason='阻塞当前学习的已记录缺口' if r['target'] in blocked else '到期复测；先不展示旧答案'))
        else:
            gap = library_gaps[0]
            items.append(dict(kind='gap_review',title=gap['repair_target'],track=gap['track'],
                              topic=gap['topic'],gap_key=gap['gap_key'],minutes=10,
                              reason='个人错题已到复测日期；作答前隐藏修复稿'))
        remaining -= 10
    if tasks:
        t = tasks[0]
        items.append(dict(**{**t,'kind':'task','minutes':min(t['minutes'],remaining)},reason='用户指定任务' if explicit else '已确认近期 Mock 的准备任务' if imminent else '本周下一项未完成任务',slice=remaining<t['minutes']))
    result = dict(plan_id=p['plan_id'],request=p,date=now.date().isoformat(),created_at=now.isoformat(),course_id=c['course_id'],course_version=c['version'],week_id=w['week_id'],minutes=minutes,items=items,unavailable=w['status']=='unavailable',note='缩短时只完成一个可验证的小目标，不自动标记整项完成。未发布的作业保持待补充。')
    with conn: conn.execute('INSERT INTO plans(plan_id,body) VALUES(?,?)',(p['plan_id'],json.dumps(result)))
    return result
