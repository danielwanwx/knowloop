"""Verify the distributed coach runs without a source checkout."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CoachPackageTests(unittest.TestCase):
    def test_installed_standalone_roundtrip_from_unrelated_working_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder).resolve()
            installed = temp / 'installed/interview-coach'
            shutil.copytree(ROOT / 'interview-coach', installed)
            workspace = temp / 'unrelated'
            workspace.mkdir()
            private = temp / 'private'
            script = installed / 'scripts/coach_state.py'
            payload = {
                'event_id': 'synthetic-introduction-1', 'occurred_at': '2026-01-01T12:00:00Z',
                'mode': 'Practice', 'track': 'Introduction', 'competency': 'state personal contribution',
                'received': {'transcript': 'Synthetic learner: I need to separate my contribution from the team result.'},
                'evaluation': {'evidence_type': 'prompted', 'scope': 'complete',
                               'state': 'needs_hint', 'dimensions': {'ownership': 'Needs a concrete personal action before assessment.'}},
                'repairs': [{'target': 'Explain one personal action without a model answer', 'due_at': '2026-01-03T12:00:00Z'}],
                'context': {'position': 'one introduction attempt', 'language': 'English'}
            }
            def run(command, data=None):
                args = [sys.executable, str(script), command, '--root', str(private)]
                if data is not None: args += ['--input', '-']
                result = subprocess.run(args, cwd=workspace, input=json.dumps(data) if data else None,
                                        text=True, capture_output=True, check=True)
                return json.loads(result.stdout)
            self.assertIsNone(run('resume')['latest_context'])
            self.assertEqual(run('save', payload)['status'], 'saved')
            self.assertEqual(run('save', payload)['status'], 'already_saved')
            resumed = run('resume')
            self.assertEqual(resumed['event_count'], 1)
            self.assertEqual(resumed['latest_context']['track'], 'Introduction')
            self.assertEqual(resumed['competencies'][0]['evaluation']['state'], 'needs_hint')
            self.assertEqual(len(resumed['due_retests']), 1)
            self.assertFalse(list(installed.rglob('*.sqlite3')))

    def test_plugin_coach_contains_exact_standalone_files(self):
        source = ROOT / 'interview-coach'
        packaged = ROOT / 'plugins/crack-system-interview-skill/skills/interview-coach'
        def files(path):
            return {p.relative_to(path): p.read_bytes() for p in path.rglob('*')
                    if p.is_file() and '__pycache__' not in p.parts}
        self.assertEqual(files(source), files(packaged))
        self.assertTrue((packaged / 'scripts/coach_state.py').exists())

    def test_checkpoint_lifecycle_is_explicit_in_both_installations(self):
        skill_docs = {
            'canonical': ROOT / 'interview-coach/SKILL.md',
            'plugin': ROOT / 'plugins/crack-system-interview-skill/skills/interview-coach/SKILL.md',
        }
        storage_docs = {
            'canonical': ROOT / 'interview-coach/references/storage.md',
            'plugin': ROOT / 'plugins/crack-system-interview-skill/skills/interview-coach/references/storage.md',
        }

        def assert_ordered(label, text, *anchors):
            positions = [text.index(anchor) for anchor in anchors]
            self.assertEqual(positions, sorted(positions), label)

        for installation, path in skill_docs.items():
            with self.subTest(document=f'{installation} skill'):
                text = path.read_text(encoding='utf-8')
                self.assertIn(
                    'The learner never prepares SQLite data, JSON payloads, terminal commands, or dashboard fields.',
                    text,
                )
                self.assertIn('This skill registers no end-of-turn callback or background listener', text)
                self.assertIn('does not depend on a host scheduler', text)
                self.assertIn('Successful saves write learner data only to the private SQLite database', text)
                self.assertIn('never generate or refresh a private HTML/JSON dashboard file', text)
                self.assertIn('dashboard --open', text)
                assert_ordered(
                    f'{installation} skill checkpoint order',
                    text,
                    'before sending the next learner-facing prompt',
                    'persist every newly received assessable attempt',
                    'persist its actual position as `status: in_progress` before acknowledging that pause',
                    'first checkpoint its actual attempt evidence',
                    'persist one `debrief`',
                )

        for installation, path in storage_docs.items():
            with self.subTest(document=f'{installation} storage reference'):
                text = path.read_text(encoding='utf-8')
                self.assertIn('These commands are a coach implementation reference, not a learner workflow.', text)
                self.assertIn('it never asks the learner to run a command, paste storage data, or create a payload file.', text)
                self.assertIn('This skill registers no end-of-turn callback or background listener', text)
                self.assertIn('does not use a host scheduler as a persistence trigger', text)
                self.assertIn('Learner payloads are not written to JSON, HTML, or another non-SQLite artifact.', text)
                self.assertIn('Automatic checkpoints never invoke a private report renderer', text)
                assert_ordered(
                    f'{installation} storage checkpoint order',
                    text,
                    'before its next learner-facing prompt',
                    'For each newly received assessable answer, retry, or actual Live transcript handoff',
                    'Before a named Learn component, article section, or design stage advances',
                    'When a bounded Mock stops, save every actual received Mock attempt first.',
                    'Then run one `debrief`',
                    'Treat `saved` and `already_saved` as the only successful checkpoint results',
                )

        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('the coach synchronously saves a', readme)
        self.assertIn('do not run storage commands', readme)
        self.assertIn('Learner records stay only in a local SQLite database', readme)
        self.assertIn('Only an explicit request opens a transient loopback', readme)
        self.assertIn('view at `127.0.0.1`', readme)
        self.assertIn('learner HTML or JSON report.', readme)
