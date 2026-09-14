"""Durable study sections and evidence-linked gap ledger."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'interview-coach/scripts'
spec = importlib.util.spec_from_file_location('coach_state', SCRIPTS / 'coach_state.py')
state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)
from test_coach_state import payload


def section(section_id='news-feed:nfr:v1'):
    return {
        'section_id': section_id,
        'occurred_at': '2026-01-01T13:00:00Z',
        'track': 'SystemDesign',
        'topic': 'News Feed',
        'stage': 'Non-functional Requirements',
        'breakdown': 'latency and durability',
        'status': 'complete',
        'confirmed_points': ['Feed read p95 is below 500 ms.'],
        'core_ideas': ['A success acknowledgement requires durable storage.'],
        'learner_shortages': ['Initially selected a database before defining access patterns.'],
        'interview_script': 'I would prioritize low latency and durable post creation.',
        'source_event_ids': ['source-1:turn-1'],
        'context': {'language': 'English'},
    }


def debrief(debrief_id='news-feed:mock-1:debrief', status='open'):
    gap = {
        'gap_event_id': debrief_id + ':gap-cursor',
        'gap_key': 'cursor-composite-boundary',
        'stage': 'API / System Interface',
        'breakdown': 'feed pagination',
        'observed_shortage': 'Used offset while new posts can arrive.',
        'core_idea': 'Use the last row complete ordering key as the cursor.',
        'standard_points': ['Use created_at and post_id as a stable boundary.'],
        'interview_script': 'I would use cursor pagination to avoid shifting offsets.',
        'repair_target': 'Explain stable cursor pagination',
        'status': status,
    }
    if status == 'open':
        gap['due_at'] = '2026-01-03T12:00:00Z'
    return {
        'debrief_id': debrief_id,
        'occurred_at': '2026-01-01T14:00:00Z',
        'mode': 'Mock',
        'track': 'SystemDesign',
        'topic': 'News Feed',
        'summary_points': ['Covered requirements through high-level design.'],
        'strengths': ['Separated post durability from feed freshness.'],
        'source_event_ids': ['source-1:turn-1'],
        'gaps': [gap],
        'context': {'language': 'English'},
    }


class CoachLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / 'private'
        self.conn = state.connect(self.root)
        evidence = payload()
        evidence.update(track='SystemDesign', competency='feed pagination')
        state.save(self.conn, evidence)
        import coach_library
        self.library = coach_library

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_section_is_idempotent_and_latest_revision_resumes(self):
        first = section()
        self.assertEqual(self.library.save_section(self.conn, first)['status'], 'saved')
        self.assertEqual(self.library.save_section(self.conn, first)['status'], 'already_saved')
        conflict = copy.deepcopy(first)
        conflict['interview_script'] = 'Different content.'
        with self.assertRaises(ValueError):
            self.library.save_section(self.conn, conflict)
        revised = section('news-feed:nfr:v2')
        revised['confirmed_points'].append('Feed freshness is below one minute.')
        self.library.save_section(self.conn, revised)
        resumed = state.resume(self.conn)
        self.assertEqual(resumed['section_count'], 2)
        self.assertEqual(len(resumed['study_sections']), 1)
        self.assertEqual(resumed['latest_section']['section_id'], revised['section_id'])
        self.assertEqual(resumed['event_count'], 1)

    def test_completed_section_requires_material_but_partial_can_resume(self):
        bad = section()
        bad['interview_script'] = ''
        with self.assertRaises(ValueError):
            self.library.save_section(self.conn, bad)
        partial = section('news-feed:entities:partial')
        partial.update(status='in_progress', confirmed_points=[], core_ideas=[],
                       interview_script='', source_event_ids=[])
        partial['learner_shortages'] = []
        self.library.save_section(self.conn, partial)
        self.assertEqual(state.resume(self.conn)['latest_section']['status'], 'in_progress')

    def test_debrief_requires_evidence_and_gap_resolution_is_append_only(self):
        first = debrief()
        self.assertEqual(self.library.save_debrief(self.conn, first)['status'], 'saved')
        self.assertEqual(self.library.save_debrief(self.conn, first)['status'], 'already_saved')
        resumed = state.resume(self.conn)
        self.assertEqual(resumed['debrief_count'], 1)
        self.assertEqual(resumed['debriefs'][0]['debrief_id'], first['debrief_id'])
        self.assertEqual(resumed['open_gaps'][0]['gap_key'], 'cursor-composite-boundary')
        resolved = debrief('news-feed:review-1:debrief', status='resolved')
        resolved['occurred_at'] = '2026-01-04T14:00:00Z'
        self.library.save_debrief(self.conn, resolved)
        resumed = state.resume(self.conn)
        self.assertEqual(resumed['open_gaps'], [])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM gap_items').fetchone()[0], 2)
        missing = debrief('missing:debrief')
        missing['source_event_ids'] = ['absent']
        with self.assertRaises(ValueError):
            self.library.save_debrief(self.conn, missing)
        self.assertEqual(state.resume(self.conn)['debrief_count'], 2)

    def test_debrief_rejects_duplicate_gap_id_without_partial_write(self):
        self.library.save_debrief(self.conn, debrief())
        second = debrief('news-feed:mock-2:debrief')
        second['gaps'][0]['gap_event_id'] = 'news-feed:mock-1:debrief:gap-cursor'
        with self.assertRaises(ValueError):
            self.library.save_debrief(self.conn, second)
        self.assertEqual(state.resume(self.conn)['debrief_count'], 1)

    def test_personal_shortage_requires_same_track_evidence(self):
        missing = section('missing-evidence')
        missing['source_event_ids'] = []
        with self.assertRaises(ValueError):
            self.library.save_section(self.conn, missing)
        wrong = payload('algorithm-evidence')
        state.save(self.conn, wrong)
        mismatched = section('wrong-track')
        mismatched['source_event_ids'] = [wrong['event_id']]
        with self.assertRaises(ValueError):
            self.library.save_section(self.conn, mismatched)


if __name__ == '__main__':
    unittest.main()
