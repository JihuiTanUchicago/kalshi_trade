"""Explicit interruption changes scheduling only; source/privacy gates remain."""
import contextlib
import io
import unittest
from unittest.mock import patch
import paper_release_remote as remote
import paper_release_runner as runner


class RestartAuthorizationTests(unittest.TestCase):
    def test_only_explicit_boolean_authorizes_interruption(self):
        for value, expected in ((True, True), (False, False), (1, False), ('true', False), (None, False)):
            with patch.dict(remote.__dict__, {'RESEARCH_INTERRUPTION_AUTHORIZED': value}):
                self.assertIs(remote.interruption_authorized(), expected)

    def test_source_conflict_never_delivers_credentials_or_stages_a_bundle(self):
        with patch.object(runner, 'module_program', return_value=''), \
             patch.object(runner, 'remote', return_value={'status': 'inspection_failed', 'error_code': 'production_source_conflict'}), \
             patch.object(runner, 'upload') as upload, patch.object(runner, 'envelope_module') as envelope, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                runner.run('activate')
        upload.assert_not_called()
        envelope.assert_not_called()


if __name__ == '__main__':
    unittest.main()
