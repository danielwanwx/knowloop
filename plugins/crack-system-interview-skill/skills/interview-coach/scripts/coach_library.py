#!/usr/bin/env python3
# coding: utf-8
"""Validated study notes, interview scripts, and debrief gap ledger."""
import hashlib
import json
from datetime import datetime


MODES = {'Learn', 'Practice', 'Mock', 'Review'}
STATUSES = {'in_progress', 'complete'}
GAP_STATUSES = {'open', 'resolved'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonempty(value, maximum=20_000):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def timestamp(value):
    require(nonempty(value, 100), 'timestamp must be a nonempty ISO8601 string')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(parsed.tzinfo is not None, 'timestamp requires timezone')
        return parsed
    except (ValueError, OverflowError):
        raise ValueError('invalid ISO8601 timestamp') from None


def keys(obj, required, optional=()):
    require(isinstance(obj, dict), 'expected an object')
    require(set(required) <= obj.keys() and obj.keys() <= set(required) | set(optional),
            'missing or unsupported fields')


def text_list(value, name, allow_empty=False):
    require(isinstance(value, list) and len(value) <= 30 and
            (allow_empty or bool(value)) and
            all(nonempty(item, 2_000) for item in value), f'invalid {name}')


def context(value):
    keys(value, set(), {'course_id', 'task_id', 'language', 'material_url'})
    require(all(isinstance(v, str) and len(v) <= 2_000 for v in value.values()),
            'invalid context')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS study_sections (
            seq INTEGER PRIMARY KEY, section_id TEXT UNIQUE NOT NULL,
            digest TEXT NOT NULL, occurred_at TEXT NOT NULL, track TEXT NOT NULL,
            topic TEXT NOT NULL, stage TEXT NOT NULL, breakdown TEXT NOT NULL,
            status TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS debriefs (
            seq INTEGER PRIMARY KEY, debrief_id TEXT UNIQUE NOT NULL,
            digest TEXT NOT NULL, occurred_at TEXT NOT NULL, mode TEXT NOT NULL,
            track TEXT NOT NULL, topic TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS gap_items (
            seq INTEGER PRIMARY KEY, gap_event_id TEXT UNIQUE NOT NULL,
            gap_key TEXT NOT NULL, debrief_id TEXT NOT NULL REFERENCES debriefs(debrief_id),
            track TEXT NOT NULL, topic TEXT NOT NULL, stage TEXT NOT NULL,
            breakdown TEXT NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS gap_items_lookup
            ON gap_items(track, topic, gap_key, seq);
    ''')


def validate_section(payload):
    keys(payload, {'section_id', 'occurred_at', 'track', 'topic', 'stage', 'breakdown',
                   'status', 'confirmed_points', 'core_ideas', 'learner_shortages',
                   'interview_script', 'source_event_ids'}, {'context'})
    for name in ('section_id', 'track', 'topic', 'stage', 'breakdown'):
        require(nonempty(payload[name], 200), f'invalid {name}')
    timestamp(payload['occurred_at'])
    require(payload['status'] in STATUSES, 'invalid section status')
    text_list(payload['confirmed_points'], 'confirmed points',
              allow_empty=payload['status'] == 'in_progress')
    text_list(payload['core_ideas'], 'core ideas',
              allow_empty=payload['status'] == 'in_progress')
    text_list(payload['learner_shortages'], 'learner shortages', allow_empty=True)
    require(isinstance(payload['interview_script'], str) and
            len(payload['interview_script']) <= 20_000 and
            (payload['status'] == 'in_progress' or payload['interview_script'].strip()),
            'completed section requires an interview script')
    require(isinstance(payload['source_event_ids'], list) and
            len(payload['source_event_ids']) <= 100 and
            all(nonempty(item, 300) for item in payload['source_event_ids']),
            'invalid source event ids')
    require(len(payload['source_event_ids']) == len(set(payload['source_event_ids'])),
            'duplicate source event id')
    require(not payload['learner_shortages'] or payload['source_event_ids'],
            'learner shortages require source evidence')
    if 'context' in payload:
        context(payload['context'])


def validate_gap(gap):
    keys(gap, {'gap_event_id', 'gap_key', 'stage', 'breakdown', 'observed_shortage',
               'core_idea', 'standard_points', 'interview_script', 'repair_target',
               'status'}, {'due_at'})
    for name in ('gap_event_id', 'gap_key', 'stage', 'breakdown', 'observed_shortage',
                 'core_idea', 'interview_script', 'repair_target'):
        require(nonempty(gap[name], 20_000 if name == 'interview_script' else 2_000),
                f'invalid {name}')
    text_list(gap['standard_points'], 'standard points')
    require(gap['status'] in GAP_STATUSES, 'invalid gap status')
    if gap['status'] == 'open':
        require('due_at' in gap, 'open gap requires due date')
    if 'due_at' in gap:
        timestamp(gap['due_at'])


def validate_debrief(payload):
    keys(payload, {'debrief_id', 'occurred_at', 'mode', 'track', 'topic',
                   'summary_points', 'strengths', 'source_event_ids', 'gaps'}, {'context'})
    for name in ('debrief_id', 'track', 'topic'):
        require(nonempty(payload[name], 200), f'invalid {name}')
    timestamp(payload['occurred_at'])
    require(payload['mode'] in MODES, 'invalid debrief mode')
    text_list(payload['summary_points'], 'summary points')
    text_list(payload['strengths'], 'strengths', allow_empty=True)
    require(isinstance(payload['source_event_ids'], list) and
            0 < len(payload['source_event_ids']) <= 100 and
            all(nonempty(item, 300) for item in payload['source_event_ids']),
            'debrief requires source event ids')
    require(isinstance(payload['gaps'], list) and len(payload['gaps']) <= 30,
            'invalid gaps')
    for gap in payload['gaps']:
        validate_gap(gap)
    gap_ids = [gap['gap_event_id'] for gap in payload['gaps']]
    require(len(gap_ids) == len(set(gap_ids)), 'duplicate gap event id')
    gap_keys = [gap['gap_key'] for gap in payload['gaps']]
    require(len(gap_keys) == len(set(gap_keys)), 'duplicate gap key')
    require(len(payload['source_event_ids']) == len(set(payload['source_event_ids'])),
            'duplicate source event id')
    if 'context' in payload:
        context(payload['context'])


def require_source_events(conn, event_ids, track):
    if not event_ids:
        return
    marks = ','.join('?' for _ in event_ids)
    rows = conn.execute(
        f'SELECT event_id,track FROM events WHERE event_id IN ({marks})', event_ids).fetchall()
    found = {row[0] for row in rows}
    require(found == set(event_ids), 'source evidence event not found')
    require(all(row[1] == track for row in rows), 'source evidence track mismatch')


def save_section(conn, payload):
    validate_section(payload)
    require_source_events(conn, payload['source_event_ids'], payload['track'])
    body = encode(payload)
    digest = hashlib.sha256(body.encode()).hexdigest()
    with conn:
        row = conn.execute('SELECT digest FROM study_sections WHERE section_id=?',
                           (payload['section_id'],)).fetchone()
        require(not row or row[0] == digest, 'section id conflict')
        if not row:
            conn.execute('''INSERT INTO study_sections
                (section_id,digest,occurred_at,track,topic,stage,breakdown,status,body)
                VALUES(?,?,?,?,?,?,?,?,?)''',
                (payload['section_id'], digest, payload['occurred_at'], payload['track'],
                 payload['topic'], payload['stage'], payload['breakdown'],
                 payload['status'], body))
    return {'status': 'already_saved' if row else 'saved',
            'section_id': payload['section_id']}


def save_debrief(conn, payload):
    validate_debrief(payload)
    require_source_events(conn, payload['source_event_ids'], payload['track'])
    body = encode(payload)
    digest = hashlib.sha256(body.encode()).hexdigest()
    conn.execute('BEGIN IMMEDIATE')
    try:
        row = conn.execute('SELECT digest FROM debriefs WHERE debrief_id=?',
                           (payload['debrief_id'],)).fetchone()
        require(not row or row[0] == digest, 'debrief id conflict')
        if row:
            conn.rollback()
            return {'status': 'already_saved', 'debrief_id': payload['debrief_id']}
        candidate_gap_ids = [gap['gap_event_id'] for gap in payload['gaps']]
        if candidate_gap_ids:
            marks = ','.join('?' for _ in candidate_gap_ids)
            existing_gap_ids = {item[0] for item in conn.execute(
                f'SELECT gap_event_id FROM gap_items WHERE gap_event_id IN ({marks})',
                candidate_gap_ids)}
            require(not existing_gap_ids, 'gap event id conflict')
        conn.execute('''INSERT INTO debriefs
            (debrief_id,digest,occurred_at,mode,track,topic,body)
            VALUES(?,?,?,?,?,?,?)''',
            (payload['debrief_id'], digest, payload['occurred_at'], payload['mode'],
             payload['track'], payload['topic'], body))
        for gap in payload['gaps']:
            conn.execute('''INSERT INTO gap_items
                (gap_event_id,gap_key,debrief_id,track,topic,stage,breakdown,status,body)
                VALUES(?,?,?,?,?,?,?,?,?)''',
                (gap['gap_event_id'], gap['gap_key'], payload['debrief_id'],
                 payload['track'], payload['topic'], gap['stage'], gap['breakdown'],
                 gap['status'], encode(gap)))
        conn.commit()
        return {'status': 'saved', 'debrief_id': payload['debrief_id']}
    except Exception:
        conn.rollback()
        raise


def resume_library(conn):
    sections = [json.loads(row[0]) for row in conn.execute(
        'SELECT body FROM study_sections ORDER BY seq')]
    latest_sections = {}
    for section in sections:
        key = (section['track'], section['topic'], section['stage'], section['breakdown'])
        latest_sections.pop(key, None)
        latest_sections[key] = section
    debriefs = [json.loads(row[0]) for row in conn.execute(
        'SELECT body FROM debriefs ORDER BY seq')]
    latest_debriefs = {}
    for debrief in debriefs:
        key = (debrief['track'], debrief['topic'])
        latest_debriefs.pop(key, None)
        latest_debriefs[key] = debrief
    gaps = {}
    for row in conn.execute('''SELECT track,topic,gap_key,body FROM gap_items
                               ORDER BY seq'''):
        gap = json.loads(row[3])
        gap.update(track=row[0], topic=row[1])
        gaps[(row[0], row[1], row[2])] = gap
    open_gaps = [gap for gap in gaps.values() if gap['status'] == 'open']
    open_gaps.sort(key=lambda gap: timestamp(gap['due_at']))
    current = list(latest_sections.values())
    return {
        'section_count': len(sections),
        'study_sections': current,
        'latest_section': sections[-1] if sections else None,
        'debrief_count': len(debriefs),
        'debriefs': list(latest_debriefs.values()),
        'latest_debrief': debriefs[-1] if debriefs else None,
        'open_gaps': open_gaps,
    }
