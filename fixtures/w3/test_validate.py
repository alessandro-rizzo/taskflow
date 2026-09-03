#!/usr/bin/env python3
"""Deterministic negative-mutation tests for the W3 fixture validator."""

from __future__ import annotations

import copy
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

import validate

EXAMPLES = Path(__file__).parent / "examples"


def delete(path: list[str]) -> Callable[[dict[str, Any]], None]:
    def mutate(document: dict[str, Any]) -> None:
        target = document
        for component in path[:-1]:
            target = target[component]
        del target[path[-1]]

    return mutate


def replace(path: list[str], value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(document: dict[str, Any]) -> None:
        target = document
        for component in path[:-1]:
            target = target[component]
        target[path[-1]] = copy.deepcopy(value)

    return mutate


class ValidatorTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.documents = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(EXAMPLES.glob("*.json"))
        }

    def diagnostics_for(
        self, filename: str, mutate: Callable[[dict[str, Any]], None]
    ) -> tuple[int, list[str]]:
        documents = copy.deepcopy(self.documents)
        mutate(documents[filename])
        with tempfile.TemporaryDirectory(prefix="taskflow-w3-mutation-") as temporary:
            directory = Path(temporary)
            for name, document in documents.items():
                (directory / name).write_text(
                    json.dumps(document, indent=2) + "\n", encoding="utf-8"
                )
            stderr = io.StringIO()
            stdout = io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
                exit_code = validate.main(["validate.py", str(directory)])
            diagnostics = [item.render() for item in validate.validate_directory(directory)]
            return exit_code, diagnostics

    def assert_mutation(
        self,
        filename: str,
        mutate: Callable[[dict[str, Any]], None],
        expected: str,
    ) -> None:
        exit_code, diagnostics = self.diagnostics_for(filename, mutate)
        self.assertEqual(exit_code, 1, "mutated fixture did not return validation failure")
        self.assertTrue(diagnostics, "mutated fixture unexpectedly passed")
        self.assertIn(expected, diagnostics)

    def test_canonical_examples_pass(self) -> None:
        self.assertEqual(validate.validate_directory(EXAMPLES), [])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(validate.main(["validate.py", str(EXAMPLES)]), 0)

    def test_multiple_diagnostics_are_deterministically_sorted(self) -> None:
        first_exit, first = self.diagnostics_for(
            "namespace-a.json", replace(["endpoint"], [])
        )
        second_exit, second = self.diagnostics_for(
            "namespace-a.json", replace(["endpoint"], [])
        )
        self.assertEqual((first_exit, second_exit), (1, 1))
        self.assertGreater(len(first), 1)
        self.assertEqual(first, sorted(first))
        self.assertEqual(first, second)

    def test_unrecognized_json_example_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="taskflow-w3-fileset-") as temporary:
            directory = Path(temporary)
            for name, document in self.documents.items():
                (directory / name).write_text(
                    json.dumps(document, indent=2) + "\n", encoding="utf-8"
                )
            (directory / "unrecognized.json").write_text("{}\n", encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                exit_code = validate.main(["validate.py", str(directory)])
            self.assertEqual(exit_code, 1)
            self.assertIn(
                "unrecognized.json: $: [W3-FILESET] namespace='<unknown>' "
                "unrecognized example filename; expected namespace-*.json or scenario-*.json",
                stderr.getvalue().splitlines(),
            )

    def test_required_and_type_diagnostics(self) -> None:
        cases = (
            (
                "missing owner",
                "namespace-a.json",
                delete(["owner"]),
                "namespace-a.json: owner: [W3-REQUIRED] namespace='ns-a' missing required field; expected a non-empty string",
            ),
            (
                "boolean port",
                "namespace-a.json",
                replace(["linux_api_service", "port"], True),
                "namespace-a.json: linux_api_service.port: [W3-TYPE] namespace='ns-a' expected a positive integer (boolean is not an integer); got bool value=True",
            ),
            (
                "endpoint wrong shape",
                "namespace-a.json",
                replace(["endpoint"], []),
                "namespace-a.json: endpoint: [W3-TYPE] namespace='ns-a' expected an object; got list value=[]",
            ),
            (
                "scenario events wrong shape",
                "scenario-cancellation.json",
                replace(["expected_events"], {}),
                "scenario-cancellation.json: expected_events: [W3-TYPE] namespace='<unknown>' expected a non-empty list of objects; got dict value={}",
            ),
            (
                "missing consumer identity",
                "namespace-a.json",
                delete(["mobile_e2e_report", "consumer_id"]),
                "namespace-a.json: mobile_e2e_report.consumer_id: [W3-REQUIRED] namespace='ns-a' missing required field; expected a non-empty string",
            ),
        )
        for name, filename, mutate, expected in cases:
            with self.subTest(name=name):
                self.assert_mutation(filename, mutate, expected)

    def test_relationship_and_authorization_diagnostics(self) -> None:
        cases = (
            (
                "dangling service source",
                replace(["linux_api_service", "produced_by", "consumes"], "missing-source"),
                "namespace-a.json: linux_api_service.produced_by.consumes: [W3-REFERENCE] namespace='ns-a' must equal local source.id='source-ns-a'; got 'missing-source'",
            ),
            (
                "dangling artifact source",
                replace(["macos_artifact", "produced_by", "consumes"], "missing-source"),
                "namespace-a.json: macos_artifact.produced_by.consumes: [W3-REFERENCE] namespace='ns-a' must equal local source.id='source-ns-a'; got 'missing-source'",
            ),
            (
                "service endpoint link",
                replace(["linux_api_service", "endpoint_id"], "missing-endpoint"),
                "namespace-a.json: linux_api_service.endpoint_id: [W3-REFERENCE] namespace='ns-a' must equal local endpoint.id='endpoint-ns-a-api'; got 'missing-endpoint'",
            ),
            (
                "foreign endpoint owner",
                replace(["endpoint", "target_namespace"], "ns-b"),
                "namespace-a.json: endpoint.target_namespace: [W3-OWNERSHIP] namespace='ns-a' must equal owning namespace_id='ns-a'; got 'ns-b'",
            ),
            (
                "foreign lease holder",
                replace(["simulator_session", "lease", "holder"], "ns-b"),
                "namespace-a.json: simulator_session.lease.holder: [W3-OWNERSHIP] namespace='ns-a' must equal owning namespace_id='ns-a'; got 'ns-b'",
            ),
            (
                "foreign consumer",
                replace(["endpoint", "authorized_consumers"], ["ns-b-ios-e2e"]),
                "namespace-a.json: endpoint.authorized_consumers: [W3-AUTHORIZATION] namespace='ns-a' must resolve exactly once to local mobile_e2e_report.consumer_id='ns-a-ios-e2e'; got ['ns-b-ios-e2e']",
            ),
            (
                "undeclared consumer",
                replace(["endpoint", "authorized_consumers"], ["unknown-consumer"]),
                "namespace-a.json: endpoint.authorized_consumers: [W3-AUTHORIZATION] namespace='ns-a' must resolve exactly once to local mobile_e2e_report.consumer_id='ns-a-ios-e2e'; got ['unknown-consumer']",
            ),
            (
                "duplicate authorized consumer",
                replace(["endpoint", "authorized_consumers"], ["ns-a-ios-e2e", "ns-a-ios-e2e"]),
                "namespace-a.json: endpoint.authorized_consumers: [W3-AUTHORIZATION] namespace='ns-a' must resolve exactly once to local mobile_e2e_report.consumer_id='ns-a-ios-e2e'; got ['ns-a-ios-e2e', 'ns-a-ios-e2e']",
            ),
            (
                "duplicate report input",
                replace(
                    ["mobile_e2e_report", "consumes"],
                    ["endpoint-ns-a-api", "artifact-ns-a-iosapp", "sim-ns-a", "sim-ns-a"],
                ),
                "namespace-a.json: mobile_e2e_report.consumes: [W3-REPORT-INPUTS] namespace='ns-a' must contain exactly once each local endpoint/artifact/simulator id=['artifact-ns-a-iosapp', 'endpoint-ns-a-api', 'sim-ns-a']; got ['endpoint-ns-a-api', 'artifact-ns-a-iosapp', 'sim-ns-a', 'sim-ns-a']",
            ),
            (
                "missing report input",
                replace(
                    ["mobile_e2e_report", "consumes"],
                    ["endpoint-ns-a-api", "artifact-ns-a-iosapp"],
                ),
                "namespace-a.json: mobile_e2e_report.consumes: [W3-REPORT-INPUTS] namespace='ns-a' must contain exactly once each local endpoint/artifact/simulator id=['artifact-ns-a-iosapp', 'endpoint-ns-a-api', 'sim-ns-a']; got ['endpoint-ns-a-api', 'artifact-ns-a-iosapp']",
            ),
            (
                "public route",
                replace(["endpoint", "route"], "public"),
                "namespace-a.json: endpoint.route: [W3-ROUTE] namespace='ns-a' must be 'namespace-private'; got 'public'",
            ),
            (
                "database escape",
                replace(["linux_api_service", "database_path"], "/var/lib/taskflow/shared/db"),
                "namespace-a.json: linux_api_service.database_path: [W3-PATH-CONFINEMENT] namespace='ns-a' must be a strict descendant of writable_root='/var/lib/taskflow/namespaces/ns-a'; got '/var/lib/taskflow/shared/db'",
            ),
        )
        for name, mutate, expected in cases:
            with self.subTest(name=name):
                self.assert_mutation("namespace-a.json", mutate, expected)

    def test_cross_namespace_collision_diagnostics(self) -> None:
        cases = (
            ("namespace", ["namespace_id"], "ns-a", "namespace_id", "ns-a"),
            ("service", ["linux_api_service", "name"], "ns-a-api", "linux_api_service.name", "ns-b"),
            ("port", ["linux_api_service", "port"], 41001, "linux_api_service.port", "ns-b"),
            ("source", ["source", "id"], "source-ns-a", "source.id", "ns-b"),
            ("endpoint", ["endpoint", "id"], "endpoint-ns-a-api", "endpoint.id", "ns-b"),
            ("artifact", ["macos_artifact", "id"], "artifact-ns-a-iosapp", "macos_artifact.id", "ns-b"),
            ("simulator", ["simulator_session", "id"], "sim-ns-a", "simulator_session.id", "ns-b"),
            ("lease", ["simulator_session", "lease", "id"], "lease-sim-ns-a", "simulator_session.lease.id", "ns-b"),
            ("report", ["mobile_e2e_report", "id"], "report-ns-a-mobile-e2e", "mobile_e2e_report.id", "ns-b"),
            ("consumer", ["mobile_e2e_report", "consumer_id"], "ns-a-ios-e2e", "mobile_e2e_report.consumer_id", "ns-b"),
        )
        for name, path, value, field_path, current_namespace in cases:
            expected = (
                f"namespace-b.json: {field_path}: [W3-COLLISION] namespace={current_namespace!r} "
                f"value={value!r} conflicts with field={field_path!r} "
                "namespace='ns-a' file='namespace-a.json'"
            )
            with self.subTest(name=name):
                self.assert_mutation("namespace-b.json", replace(path, value), expected)

    def test_path_and_cross_kind_collision_diagnostics(self) -> None:
        cases = (
            (
                replace(["writable_root"], "/var/lib/taskflow/namespaces/ns-a/child"),
                "namespace-b.json: writable_root: [W3-COLLISION] namespace='ns-b' value='/var/lib/taskflow/namespaces/ns-a/child' conflicts with field='writable_root' namespace='ns-a' file='namespace-a.json'",
            ),
            (
                replace(["linux_api_service", "database_path"], "/var/lib/taskflow/namespaces/ns-a/db"),
                "namespace-b.json: linux_api_service.database_path: [W3-COLLISION] namespace='ns-b' value='/var/lib/taskflow/namespaces/ns-a/db' conflicts with field='writable_root' namespace='ns-a' file='namespace-a.json'",
            ),
            (
                replace(["macos_artifact", "id"], "endpoint-ns-b-api"),
                "namespace-b.json: macos_artifact.id: [W3-COLLISION] namespace='ns-b' value='endpoint-ns-b-api' conflicts with field='endpoint.id' namespace='ns-b' file='namespace-b.json'",
            ),
        )
        for mutate, expected in cases:
            with self.subTest(expected=expected):
                self.assert_mutation("namespace-b.json", mutate, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
