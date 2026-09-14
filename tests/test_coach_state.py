"""Durability and evidence guardrails; all learner data lives in temp directories."""
import concurrent.futures
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'interview-coach/scripts/coach_state.py'
spec = importlib.util.spec_from_file_location('coach_state', SCRIPT)
state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)


def payload(event_id='source-1:turn-1'):
    return {'event_id': event_id, 'occurred_at': '2026-01-01T12:00:00Z', 'mode': 'Practice',
            'track': 'Algorithms', 'competency': 'binary search boundary',
            'received': {'transcript': 'Learner: I use a half-open interval.',
                         'original_answer': 'I use a half-open interval.'},
            'evaluation': {'evidence_type': 'independent', 'scope': 'complete',
                           'dimensions': {'invariant': 'Explained correct interval invariant.'},
                           'state': 'independent_today'},
            'repairs': [{'target': 'Transfer the boundary invariant to a new problem',
                         'due_at': '2026-01-03T12:00:00Z'}],
            'context': {'position': 'boundary invariant', 'next_action': 'delayed retest'}}


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / 'private'
        self.conn = state.connect(str(self.root))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_replay_and_conflicting_replay(self):
        p = payload()
        self.assertEqual(state.save(self.conn, p)['status'], 'saved')
        self.assertEqual(state.save(self.conn, p)['status'], 'already_saved')
        p['received']['transcript'] = 'different'
        with self.assertRaises(state.Invalid):
            state.save(self.conn, p)
        self.assertEqual(state.resume(self.conn)['event_count'], 1)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / 'coach.sqlite3').stat().st_mode & 0o777, 0o600)

    def test_nonindependent_and_incomplete_never_promote(self):
        for evidence_type in ('question', 'self_report', 'coach_example', 'prompted'):
            p = payload()
            p['evaluation']['evidence_type'] = evidence_type
            with self.assertRaises(state.Invalid):
                state.save(self.conn, p)
        p = payload()
        p['evaluation']['scope'] = 'incomplete'
        with self.assertRaises(state.Invalid):
            state.save(self.conn, p)
        p['evaluation']['state'] = 'needs_check'
        state.save(self.conn, p)
        self.assertEqual(state.resume(self.conn)['latest_context']['evaluation']['state'], 'needs_check')

    def test_hints_are_not_independent(self):
        p = payload()
        p['received']['hints'] = 'Try a half-open interval'
        with self.assertRaises(state.Invalid):
            state.save(self.conn, p)

    def test_transfer_and_repair_resolution(self):
        first = payload()
        state.save(self.conn, first)
        self.assertEqual(len(state.resume(self.conn)['due_retests']), 1)
        later = payload('source-2:turn-1')
        later['occurred_at'] = '2026-01-04T12:00:00Z'
        later['repairs'] = []
        later['evaluation']['state'] = 'delayed_transfer'
        later['evaluation']['transfer'] = {'prior_event_id': first['event_id'],
                                          'kind': 'retention', 'evidence': 'Unprompted reconstruction after three days.'}
        wrong = copy.deepcopy(later)
        wrong['competency'] = 'different'
        with self.assertRaises(state.Invalid):
            state.save(self.conn, wrong)
        same_day = copy.deepcopy(later)
        same_day['occurred_at'] = '2026-01-01T13:00:00Z'
        with self.assertRaises(state.Invalid):
            state.save(self.conn, same_day)
        state.save(self.conn, later)
        resumed = state.resume(self.conn)
        self.assertEqual(resumed['due_retests'], [])
        self.assertEqual(resumed['latest_context']['received'], later['received'])
        self.assertEqual(resumed['latest_context']['context'], later['context'])
        self.assertEqual(resumed['event_count'], 2)

    def test_same_day_transfer_rejected_without_mutation(self):
        state.save(self.conn, payload())
        p = payload('later')
        p['occurred_at'] = '2026-01-01T13:00:00Z'
        p['evaluation'].update(state='delayed_transfer', transfer={
            'prior_event_id': payload()['event_id'], 'kind': 'transfer',
            'evidence': 'Changed constraints answered independently.'})
        before = state.resume(self.conn)
        with self.assertRaises(state.Invalid):
            state.save(self.conn, p)
        self.assertEqual(state.resume(self.conn), before)

    def test_questions_do_not_demote_attempt_but_failed_attempt_does(self):
        state.save(self.conn, payload())
        for kind in ('question', 'self_report', 'coach_example'):
            p = payload(kind)
            p['evaluation'].update(evidence_type=kind, state='needs_check')
            state.save(self.conn, p)
            resumed = state.resume(self.conn)
            self.assertEqual(resumed['latest_context']['event_id'], kind)
            self.assertEqual(resumed['competencies'][0]['evaluation']['state'], 'independent_today')
        p = payload('failed-attempt')
        p['evaluation'].update(evidence_type='prompted', state='needs_hint')
        state.save(self.conn, p)
        self.assertEqual(state.resume(self.conn)['competencies'][0]['evaluation']['state'], 'needs_hint')

    def test_cross_topic_resume_preserves_review_date_and_renewed_target(self):
        first = payload()
        state.save(self.conn, first)
        review = payload('review-day-3')
        review['occurred_at'] = '2026-01-03T12:00:00Z'
        review['evaluation'].update(state='delayed_transfer', transfer={
            'prior_event_id': first['event_id'], 'kind': 'retention',
            'evidence': 'Independent reconstruction on a later day.'})
        review['evaluation']['dimensions']['review_plan'] = 'Actual interval 2 days; next interval 7 days.'
        review['repairs'][0]['due_at'] = '2026-01-10T12:00:00Z'
        state.save(self.conn, review)
        unrelated = payload('other-topic')
        unrelated.update(track='Statistics', competency='conditional probability')
        unrelated['occurred_at'] = '2026-01-04T12:00:00Z'
        unrelated['repairs'] = []
        state.save(self.conn, unrelated)
        result = state.resume(self.conn)
        self.assertEqual(result['latest_context']['event_id'], 'other-topic')
        original = next(c for c in result['competencies'] if c['track'] == 'Algorithms')
        self.assertEqual(original['occurred_at'], review['occurred_at'])
        self.assertEqual(original['context'], review['context'])
        self.assertIn('2 days', original['evaluation']['dimensions']['review_plan'])
        self.assertEqual(len(result['pending_repairs']), 1)
        self.assertEqual(result['pending_repairs'][0]['event_id'], review['event_id'])
        self.assertEqual(result['pending_repairs'][0]['due_at'], '2026-01-10T12:00:00Z')

    def test_transfer_missing_prior_is_atomic(self):
        p = payload()
        p['evaluation'].update(state='delayed_transfer', transfer={
            'prior_event_id': 'absent', 'kind': 'transfer', 'evidence': 'Changed constraints.'})
        with self.assertRaises(state.Invalid):
            state.save(self.conn, p)
        self.assertEqual(state.resume(self.conn)['event_count'], 0)

    def test_transaction_rolls_back_mid_write(self):
        self.conn.execute("CREATE TRIGGER fail_eval BEFORE INSERT ON evaluations BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(sqlite3.Error):
            state.save(self.conn, payload())
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM events').fetchone()[0], 0)

    def test_paths_reject_repository_and_symlinks(self):
        with self.assertRaises(state.Invalid):
            state.connect(str(SCRIPT.parent / 'private'))
        linked = self.root.parent / 'linked'
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(state.Invalid):
            state.connect(str(linked))
        outside = self.root.parent / 'outside'
        outside.write_text('unchanged')
        self.conn.close()
        (self.root / 'coach.sqlite3').unlink()
        (self.root / 'coach.sqlite3').symlink_to(outside)
        with self.assertRaises(state.Invalid):
            state.connect(str(self.root))
        self.assertEqual(outside.read_text(), 'unchanged')

    def test_cli_errors_do_not_leak_input(self):
        result = subprocess.run([sys.executable, str(SCRIPT), 'save', '--root', str(self.root), '--input', '-'],
                                input='SECRET private malformed {', text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('SECRET', result.stderr + result.stdout)

    def test_concurrent_exact_replays_and_distinct_events(self):
        def write(event_id):
            result = subprocess.run([sys.executable, str(SCRIPT), 'save', '--root', str(self.root), '--input', '-'],
                                    input=json.dumps(payload(event_id)), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)['status']
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(write, ['same'] * 6 + ['other-1', 'other-2']))
        self.assertEqual(results.count('saved'), 3)
        self.assertEqual(state.resume(self.conn)['event_count'], 3)

    def test_structural_validation(self):
        for key, value in [('event_id', ''), ('mode', []), ('mode', 'Exam'), ('received', {}), ('repairs', 'bad')]:
            p = payload()
            p[key] = value
            with self.assertRaises(state.Invalid):
                state.save(self.conn, p)


if __name__ == '__main__':
    unittest.main()
