import copy
import importlib.util
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SPEC = importlib.util.spec_from_file_location("e03_validator", HERE / "e03_validator.py")
V = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(V)
POLICY = json.loads((HERE.parent / "policies/untrusted-plan-policy.json").read_text())
GOOD = json.loads((ROOT / "experiments/e02-plan-ir/evidence/raw/plans/w1.json").read_text())


class ValidatorTest(unittest.TestCase):
    def reject(self, raw, path):
        with self.assertRaises(V.Rejection) as caught:
            V.validate(raw, POLICY)
        self.assertEqual(path, caught.exception.path)

    def encoded(self, value):
        return json.dumps(value, separators=(",", ":")).encode()

    def test_known_good(self):
        self.assertTrue(V.validate(self.encoded(GOOD), POLICY)["accepted"])

    def test_parser_boundaries(self):
        self.reject(b'{"a":1,"a":2}', "$")
        self.reject(self.encoded(GOOD) + b' {}', "$")
        self.reject(b'\xff', "$")
        doc = copy.deepcopy(GOOD); del doc["format_version"]
        self.reject(self.encoded(doc), "$.format_version")
        doc = copy.deepcopy(GOOD); doc["format_version"] = "v999"
        self.reject(self.encoded(doc), "$.format_version")
        doc = copy.deepcopy(GOOD); doc["planner_approval"] = True
        self.reject(self.encoded(doc), "$.planner_approval")
        self.reject(b" " * (POLICY["maximums"]["document_bytes"] + 1), "$")
        deep = b'{"document_kind":"plan","x":' + b"[" * 40 + b"0" + b"]" * 40 + b"}"
        self.reject(deep, "$")

        doc = copy.deepcopy(GOOD)
        doc["nodes"] = [copy.deepcopy(GOOD["nodes"][0]) for _ in range(POLICY["maximums"]["nodes"] + 1)]
        for index, node in enumerate(doc["nodes"]):
            node["id"] = f"node-{index}"
            node["needs"] = []
        self.reject(self.encoded(doc), "$.nodes")

    def test_authority_and_paths(self):
        cases = []
        doc = copy.deepcopy(GOOD); doc["nodes"][1]["execution_profile"]["os"] = "linux"
        cases.append((doc, "$.nodes[id=test].execution_profile.os"))
        doc = copy.deepcopy(GOOD); doc["services"] = [{"id":"internal","route":"tcp://127.0.0.1"}]
        cases.append((doc, "$.services[id=internal].route"))
        doc = copy.deepcopy(GOOD); doc["secrets"] = [{"id":"signing-key","capability":"read"}]
        cases.append((doc, "$.secrets[id=signing-key].capability"))
        doc = copy.deepcopy(GOOD); doc["services"] = [{"id":"release","route":"none"}]; doc["effects"] = [{"id":"publish","kind":"publish","target":"release"}]
        cases.append((doc, "$.effects[id=publish].kind"))
        doc = copy.deepcopy(GOOD); doc["effects"] = [{"id":"publish","kind":"publish","target":"missing"}]
        cases.append((doc, "$.effects[id=publish].target"))
        for unsafe in ("/private/e03", "../e03"):
            doc = copy.deepcopy(GOOD); doc["nodes"][2]["planning_condition"]["patterns"][0] = unsafe
            cases.append((doc, "$.nodes[id=lint].planning_condition.patterns[0]"))
        doc = copy.deepcopy(GOOD); doc["nodes"][1]["resources"]["memory_mib"] = 4097
        cases.append((doc, "$.nodes[id=test].resources.memory_mib"))
        doc = copy.deepcopy(GOOD); doc["policy"] = {"approved": True}
        cases.append((doc, "$.policy"))
        for doc, path in cases:
            self.reject(self.encoded(doc), path)

    def test_total_and_count_limits(self):
        doc = copy.deepcopy(GOOD); doc["nodes"][0]["resources"]["cpu_millicores"] = 2000; doc["nodes"][1]["resources"]["cpu_millicores"] = 2000; doc["nodes"][2]["resources"]["cpu_millicores"] = 2000
        self.reject(self.encoded(doc), "$.nodes")
        policy = copy.deepcopy(POLICY); policy["maximums"]["nodes"] = 3
        with self.assertRaises(V.Rejection) as caught:
            V.validate(self.encoded(GOOD), policy)
        self.assertEqual("$.nodes", caught.exception.path)


if __name__ == "__main__":
    unittest.main()
