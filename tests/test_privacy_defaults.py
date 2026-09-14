from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import shutil
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_public_content as privacy

spec = importlib.util.spec_from_file_location('privacy_renderer', ROOT / 'scripts/render_interview_card.py')
renderer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = renderer
spec.loader.exec_module(renderer)


class PrivacyDefaultsTests(unittest.TestCase):
    def render(self, flags=()):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'content.json'
            source.write_text(json.dumps({'title': 'Test', 'talk_track': 'Synthetic practice text', 'blocks': [{'id':'a', 'title':'API', 'body':'Request', 'kind':'api'}]}))
            argv = ['render', '--content', str(source), '--out', str(root), *flags]
            with patch.object(sys, 'argv', argv), patch.object(renderer.shutil, 'which', return_value='node'), patch.object(renderer.subprocess, 'run') as share, patch.object(renderer, 'synthesize_elevenlabs_tts') as tts, contextlib.redirect_stdout(io.StringIO()) as stdout:
                share.return_value.stdout = '{"url":"https://example.com/test"}'
                tts.return_value = {'provider': 'elevenlabs'}
                renderer.main()
            result = json.loads(stdout.getvalue())
            self.assertTrue(Path(result['preview']).exists())
            self.assertTrue(Path(result['excalidraw']).exists())
            return result, share.call_count, tts.call_count

    def test_defaults_are_local_even_with_legacy_tts_environment(self):
        with patch.dict(os.environ, {'CARD_TTS':'elevenlabs'}):
            result, shares, speech = self.render()
        self.assertEqual((shares, speech), (0, 0))
        self.assertIsNone(result['share'])
        self.assertNotIn('tts', result)

    def test_share_opt_in_does_not_enable_speech(self):
        _, shares, speech = self.render(['--share'])
        self.assertEqual((shares, speech), (1, 0))

    def test_speech_opt_in_does_not_enable_sharing(self):
        _, shares, speech = self.render(['--tts','elevenlabs'])
        self.assertEqual((shares, speech), (0, 1))

    def test_conflicting_sharing_flags_fail_before_rendering(self):
        with patch.object(sys, 'argv', ['render','--content','unused','--share','--no-share']), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                renderer.parse_args()
        self.assertEqual(error.exception.code, 2)

    def test_provider_error_body_is_not_persisted(self):
        error = urllib.error.HTTPError('https://example.com', 400, 'bad', {}, io.BytesIO(b'PRIVATE INPUT ECHO'))
        with patch.dict(os.environ, {'ELEVENLABS_API_KEY': 'synthetic-test-key'}), patch.object(renderer.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                renderer.synthesize_elevenlabs_tts('example', Path('unused'), 'voice', 'model', 'mp3')
        self.assertNotIn('PRIVATE INPUT ECHO', str(caught.exception))
        self.assertIn('400', str(caught.exception))

    def test_share_error_does_not_expose_subprocess_payload(self):
        with patch.object(renderer.shutil, 'which', return_value='node'), patch.object(renderer.subprocess, 'run', side_effect=RuntimeError('PRIVATE INPUT ECHO')):
            result = renderer.maybe_share(Path('unused'), False)
        self.assertNotIn('PRIVATE INPUT ECHO', json.dumps(result))

    @unittest.skipUnless(shutil.which('node'), 'Node.js is not installed')
    def test_direct_share_helper_redacts_provider_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scene = root / 'scene.excalidraw'
            scene.write_text('{"elements": []}')
            for ok in (False, True):
                with self.subTest(ok=ok):
                    shim = root / 'offline.mjs'
                    shim.write_text("globalThis.fetch = async () => ({ok: " + str(ok).lower() + ", status: 400, statusText: 'PRIVATE INPUT ECHO', text: async () => JSON.stringify({echo:'PRIVATE INPUT ECHO'})});")
                    result = subprocess.run(['node','--import',str(shim),str(ROOT/'scripts/share_excalidraw.mjs'),'--input',str(scene)], capture_output=True, text=True, check=False)
                    self.assertEqual(result.returncode, 1)
                    self.assertNotIn('PRIVATE INPUT ECHO', result.stdout + result.stderr)
                    self.assertIn('Share upload failed', result.stderr)

    def test_all_distributed_renderers_match_reviewed_source(self):
        canonical = (ROOT / 'scripts/render_interview_card.py').read_bytes()
        copies = [ROOT / name / 'scripts/render_interview_card.py' for name in ('card','senior-sde-interview-script')]
        copies += [ROOT / 'plugins/crack-system-interview-skill/skills' / name / 'scripts/render_interview_card.py' for name in ('card','senior-sde-interview-script')]
        for copy in copies:
            with self.subTest(copy=copy): self.assertEqual(canonical, copy.read_bytes())
            self.assertEqual((ROOT/'scripts/share_excalidraw.mjs').read_bytes(), (copy.parent/'share_excalidraw.mjs').read_bytes())


class PublicationPrivacyTests(unittest.TestCase):
    def test_repository_publishable_files_pass_privacy_gate(self):
        self.assertEqual(privacy.check_current(ROOT), [])

    def test_scan_reports_location_without_sensitive_value(self):
        sensitive = '/' + 'Users' + '/sample-person/Desktop/note.txt'
        findings = privacy.scan_path('notes.md', sensitive.encode())
        self.assertEqual(findings[0]['rule'], 'personal-home-path')
        self.assertNotIn('sample-person', json.dumps(findings))

    def test_private_files_are_rejected_even_when_content_is_empty(self):
        for name in ['.interview-coach-data/sessions/raw.md', 'learner-state.md', '.env.local', 'sessions/raw.md', 'practice-transcript.txt', 'practice-share-link.txt', 'coach.sqlite3', 'coach.sqlite3-wal']:
            self.assertTrue(privacy.scan_path(name, b''))

    def test_tracked_files_are_scanned_despite_gitignore(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(['git','init','-q',str(root)],check=True)
            (root / 'learner-state.md').write_text('')
            subprocess.run(['git','-C',str(root),'add','learner-state.md'],check=True)
            (root / '.gitignore').write_text('learner-state.md\n')
            self.assertTrue(any(x['rule']=='private-runtime-file' for x in privacy.check_current(root)))

    def test_retired_public_page_path_is_rejected(self):
        findings = privacy.scan_path("docs/week1/day-1.html", b"")
        self.assertTrue(any(item["rule"] == "retired-public-calendar-file" for item in findings))

    def test_account_pages_url_is_rejected_without_echoing_it(self):
        value = "https://example" + ".github" + ".io/catalog"
        findings = privacy.scan_path("notes.md", value.encode())
        self.assertTrue(any(item["rule"] == "account-pages-url" for item in findings))

    def test_sensitive_body_is_rejected_before_any_public_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'source.html'; dest=root/'public'
            source.write_text('/' + 'Users' + '/sample-person/Desktop/note.txt')
            self.assertTrue(privacy.scan_path("source.html", source.read_bytes()))
            self.assertFalse(dest.exists())


if __name__ == '__main__':
    unittest.main()
