import contextlib
import io
import json
import unittest
import runner

class ProgramTest(unittest.TestCase):
    def execute(self, source, mode='inventory', before=None, after=None, pin=None):
        program=runner.build_program(source,mode,before or {},after or {},pin)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):exec(compile(program,'<guarded-remote>','exec'),{})
        return json.loads(output.getvalue())
    def test_inventory_uses_read_only_api(self):
        self.assertEqual(self.execute('def inventory():return {"status":"ready","read_only":True}'),{'status':'ready','read_only':True})
    def test_apply_passes_exact_pins_without_interpolation(self):
        out=self.execute('def apply(pin,before,after):return {"pin":pin,"before":before,"after":after}', 'apply',{'app/static/app.js':'a'*64},{'app/static/app.js':'b'*64},'c'*64)
        self.assertEqual(out['pin'],'c'*64);self.assertEqual(out['before']['app/static/app.js'],'a'*64);self.assertEqual(out['after']['app/static/app.js'],'b'*64)
    def test_error_body_is_never_emitted(self):
        out=self.execute('def inventory():raise RuntimeError("private environment secret must not print")')
        self.assertEqual(out,{'status':'error','error_code':'RuntimeError'})
    def test_fixed_guard_code_survives(self):
        out=self.execute('class GuardError(Exception):code="source_changed"\ndef inventory():raise GuardError("private")')
        self.assertEqual(out,{'status':'error','error_code':'source_changed'})
    def test_code_containing_result_text_does_not_break_wrapper(self):
        self.assertEqual(self.execute('literal="result=never split code"\ndef inventory():return {"text":literal}')['text'],'result=never split code')
    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(RuntimeError):runner.build_program('', 'restart',{}, {})
