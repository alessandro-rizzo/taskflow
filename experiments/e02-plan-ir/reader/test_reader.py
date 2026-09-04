import importlib.util, json, unittest
from pathlib import Path
SCRIPT=Path(__file__).with_name("e02_reader.py");SPEC=importlib.util.spec_from_file_location("reader",SCRIPT);READER=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(READER)
class ReaderTests(unittest.TestCase):
    def test_duplicate_and_numbers_rejected(self):
        for raw in (b'{"a":1,"a":2}',b'{"a":-0}',b'{"a":1.5}'):
            with self.assertRaises(READER.PlanError):READER.loads(raw)
    def test_unicode_canonical(self):
        doc={"z":"<>&\u2028","a":"é"};self.assertEqual(READER.canonical(doc).decode(),'{"a":"é","z":"<>&\u2028"}')
    def test_diff_uses_semantic_ids(self):
        before={"nodes":[{"id":"test","value":"a"}]};after={"nodes":[{"id":"test","value":"b"}]};result=READER.report(before,after);self.assertEqual(result["differences"][0]["path"],"$.nodes[id=test].value")
    def test_rejects_invalid_profile_value(self):
        document={"document_kind":"plan","format_version":READER.FORMAT_VERSION,"fixture_id":"test","fixture_version":"v1","status":"experimental","nodes":[{"id":"test","needs":[],"consumes":["source"],"produces":[],"planning_condition":{"type":"always"},"outcome_condition":{"type":"always"},"resources":{"cpu_millicores":0,"memory_mib":0},"execution_profile":{"os":"any","toolchain":"none","profile_id":False},"cache_policy":{"mode":"none"}}],"artifacts":[{"id":"source","type":"Tree","optional":False}]}
        with self.assertRaises(READER.PlanError):READER.validate(document)
if __name__=="__main__":unittest.main()
