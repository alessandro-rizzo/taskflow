#!/usr/bin/env python3
"""Verify only the frozen E01 Phase A measurement contract."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


EXPERIMENT = Path(__file__).resolve().parents[1]
REPOSITORY = EXPERIMENT.parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"verify-phase-a: {message}")


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot read {path.relative_to(REPOSITORY)}: {error}")
    if not isinstance(value, dict):
        fail(f"{path.relative_to(REPOSITORY)} must contain a JSON object")
    return value


def repository_path(relative: str) -> Path:
    candidate = (REPOSITORY / relative).resolve()
    try:
        candidate.relative_to(REPOSITORY.resolve())
    except ValueError:
        fail(f"path escapes repository: {relative}")
    return candidate


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_w1_logical_shape() -> dict:
    return {
        "status": "experiment-only-not-plan-ir",
        "execution": "fake",
        "composition_rule": (
            "dependencies are authored by passing typed handles, "
            "not only string identifiers"
        ),
        "source": {"id": "source", "type": "Source"},
        "child_work": [
            {
                "id": "format",
                "type": "Check",
                "consumes": ["source"],
                "produces": [],
            },
            {
                "id": "test",
                "type": "Report[GoTests]",
                "consumes": ["source"],
                "produces": [
                    {
                        "id": "test-report",
                        "type": "Report[GoTests]",
                        "optional": False,
                    }
                ],
            },
            {
                "id": "lint",
                "type": "Check",
                "consumes": ["source"],
                "produces": [],
            },
        ],
        "aggregate": {
            "id": "check",
            "type": "Check",
            "depends_on": ["format", "test", "lint"],
            "exposes": [
                {
                    "id": "test-report",
                    "from": "test",
                    "type": "Report[GoTests]",
                    "optional": False,
                },
                {
                    "id": "diagnostics",
                    "from": "check",
                    "type": "Report[Diagnostics]",
                    "optional": True,
                },
            ],
        },
        "typed_handle_relations": [
            {"from": "source", "to": "format"},
            {"from": "source", "to": "test"},
            {"from": "source", "to": "lint"},
            {"from": "format", "to": "check"},
            {"from": "test", "to": "check"},
            {"from": "lint", "to": "check"},
        ],
    }


def verify_workflows(manifest: dict) -> None:
    workflows = manifest.get("workflows")
    if not isinstance(workflows, list) or len(workflows) != 3:
        fail("targets.json must bind exactly W1, W2, and W3")

    if [item.get("roadmap_workflow") for item in workflows] != ["W1", "W2", "W3"]:
        fail("workflow order and identities must be W1, W2, W3")

    for item in workflows:
        golden = repository_path(item["golden_path"])
        if not golden.is_file():
            fail(f"missing frozen golden: {item['golden_path']}")
        actual_hash = sha256(golden)
        if actual_hash != item.get("golden_sha256"):
            fail(
                f"frozen golden drift for {item['roadmap_workflow']}: "
                f"want {item.get('golden_sha256')}, got {actual_hash}"
            )

        document = load_json(golden)
        if document.get("document_kind") != "schema":
            fail(f"{item['golden_path']} is not a schema document")
        for field in ("fixture_id", "fixture_version"):
            if document.get(field) != item.get(field):
                fail(f"{item['roadmap_workflow']} {field} does not match its golden")
        operations = document.get("operations")
        if not isinstance(operations, list) or len(operations) != 1:
            fail(f"{item['roadmap_workflow']} must bind one operation")
        if operations[0].get("id") != item.get("operation_id"):
            fail(f"{item['roadmap_workflow']} operation id does not match its golden")
        if operations[0].get("required_effects") != []:
            fail(f"{item['roadmap_workflow']} unexpectedly contains a positive effect")

        logical_shape = item.get("logical_authoring_shape")
        if item["roadmap_workflow"] == "W1":
            expected_shape = expected_w1_logical_shape()
            if logical_shape != expected_shape:
                fail("W1 logical authoring shape changed")
            exposed_outputs = [
                {key: output[key] for key in ("id", "type", "optional")}
                for output in expected_shape["aggregate"]["exposes"]
            ]
            if operations[0].get("outputs") != exposed_outputs:
                fail("W1 logical outputs do not match the frozen schema golden")
        elif logical_shape is not None:
            fail(f"{item['roadmap_workflow']} has an unexpected logical authoring shape")

        source_bindings = item.get("fixture_source_bindings", [])
        if item["roadmap_workflow"] != "W3" and source_bindings:
            fail(f"{item['roadmap_workflow']} has unexpected fixture source bindings")
        if item["roadmap_workflow"] == "W3":
            expected_paths = [
                "fixtures/w3/spec.md",
                "fixtures/w3/examples/namespace-a.json",
                "fixtures/w3/examples/namespace-b.json",
            ]
            if [binding.get("path") for binding in source_bindings] != expected_paths:
                fail("W3 source bindings must cover spec.md and both namespace examples")
            for binding in source_bindings:
                source = repository_path(binding["path"])
                if not source.is_file():
                    fail(f"missing W3 source binding: {binding['path']}")
                actual_source_hash = sha256(source)
                if actual_source_hash != binding.get("sha256"):
                    fail(
                        f"W3 source drift for {binding['path']}: "
                        f"want {binding.get('sha256')}, got {actual_source_hash}"
                    )
            spec_text = repository_path(expected_paths[0]).read_text(encoding="utf-8")
            if item["fixture_version"] not in spec_text:
                fail("W3 spec does not declare the bound fixture version")
            for relative in expected_paths[1:]:
                source_document = load_json(repository_path(relative))
                if source_document.get("fixture_id") != item["fixture_id"]:
                    fail(f"{relative} fixture_id does not match the W3 binding")
                if source_document.get("version") != item["fixture_version"]:
                    fail(f"{relative} version does not match the W3 binding")


def verify_effect_probe(manifest: dict) -> None:
    declaration = manifest.get("synthetic_effect_probe", {})
    path = repository_path(declaration.get("path", ""))
    probe = load_json(path)

    expected_envelope = {
        "document_kind": "schema",
        "format_version": manifest.get("schema_format"),
        "fixture_id": declaration.get("fixture_id"),
        "fixture_version": declaration.get("fixture_version"),
        "status": declaration.get("status"),
    }
    for field, expected in expected_envelope.items():
        if probe.get(field) != expected:
            fail(f"effect probe {field}: want {expected!r}, got {probe.get(field)!r}")

    operations = probe.get("operations")
    if not isinstance(operations, list) or len(operations) != 1:
        fail("effect probe must contain exactly one operation")
    operation = operations[0]
    if operation.get("id") != declaration.get("operation_id"):
        fail("effect probe operation id does not match targets.json")

    arguments = {item.get("name"): item for item in operation.get("arguments", [])}
    environment = arguments.get("environment", {})
    if environment.get("required") is not True or environment.get("enum") != [
        "staging",
        "production",
    ]:
        fail("effect probe environment must be a required staging/production enum")
    channel = arguments.get("channel", {})
    if channel.get("default") != "beta" or channel.get("enum") != ["beta", "stable"]:
        fail("effect probe channel must be the defaulted beta/stable enum")

    if operation.get("outputs") != [
        {
            "id": "published-release",
            "type": "Effect[PublishedRelease]",
            "optional": False,
        }
    ]:
        fail("effect probe must expose the non-optional published release effect")
    if operation.get("required_effects") != ["publish-release"]:
        fail("effect probe must request publish-release")
    if operation.get("required_capabilities") != [
        "network:app-store-connect",
        "secret:app-store-signing",
    ]:
        fail("effect probe capabilities changed")


def verify_control(manifest: dict) -> None:
    control = manifest.get("low_level_control", {})
    path = repository_path(control.get("path", ""))
    if control.get("language") != "go" or control.get("syntax_must_parse") is not True:
        fail("low-level control must declare parseable Go syntax")
    expected_formatter = (
        "gofmt -d "
        "experiments/e01-authoring-schema/scope/w1-low-level-control.go.txt"
    )
    if control.get("formatter_command") != expected_formatter:
        fail("low-level control formatter command changed")
    if control.get("formatter_must_be_stable") is not True:
        fail("low-level control must require formatter stability")

    formatted = subprocess.run(
        ["gofmt", "-d", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if formatted.returncode != 0:
        fail(f"gofmt could not parse the low-level control: {formatted.stderr.strip()}")
    if formatted.stdout:
        fail("low-level control is not gofmt-stable:\n" + formatted.stdout)

    control_text = path.read_text(encoding="utf-8")
    lines = control_text.splitlines()

    required_control_fragments = {
        'typed source selection': 'source := ctx.SelectSource(',
        'format child': 'ID:     "format",',
        'test child': 'ID:      "test",',
        'lint child': 'ID:     "lint",',
        'aggregate check': 'ID:      "check",',
        'test report production': 'Outputs: []string{"test-report"},',
        'aggregate dependencies': 'Needs:   []LowLevelValue{format, tests, lint},',
        'aggregate outputs': 'Outputs: []string{"test-report", "diagnostics"},',
    }
    for label, fragment in required_control_fragments.items():
        if fragment not in control_text:
            fail(f"low-level control is missing {label}")
    if control_text.count("[]LowLevelValue{source},") != 3:
        fail("low-level control must pass source to exactly three child nodes")

    try:
        start = lines.index("// E01-COUNT-BEGIN") + 1
        end = lines.index("// E01-COUNT-END")
    except ValueError:
        fail("low-level control is missing unique count markers")
    if start >= end:
        fail("low-level control count markers are reversed")

    authored = sum(
        1
        for line in lines[start:end]
        if line.strip() and not line.lstrip().startswith("//")
    )
    if authored != control.get("authored_loc"):
        fail(f"control authored LOC: want {control.get('authored_loc')}, got {authored}")
    if control.get("maximum_passing_candidate_loc") != authored * 75 // 100:
        fail("maximum candidate LOC must be floor(control LOC * 0.75)")

    marker_prefix = "// E01-CONCEPT: "
    markers = [
        line.removeprefix(marker_prefix)
        for line in lines
        if line.startswith(marker_prefix)
    ]
    if markers != control.get("concepts"):
        fail("control concept markers do not match targets.json")
    if len(markers) != control.get("low_level_concept_count"):
        fail("control concept count does not match targets.json")
    if control.get("maximum_passing_candidate_concepts") != 7:
        fail("30% concept-reduction threshold must allow at most seven concepts")


def verify_phase_boundary() -> None:
    forbidden = EXPERIMENT / "candidates"
    if forbidden.exists():
        fail("candidate code exists before the Phase A review and commit")

    forbidden_names = {"go.mod", "go.work", "package.json", "bun.lock", "tsconfig.json"}
    found = sorted(
        path.relative_to(EXPERIMENT).as_posix()
        for path in EXPERIMENT.rglob("*")
        if path.is_file() and path.name in forbidden_names
    )
    if found:
        fail(f"candidate/module metadata exists in Phase A: {', '.join(found)}")


def main() -> None:
    manifest = load_json(EXPERIMENT / "scope" / "targets.json")
    if manifest.get("contract_version") != "e01-measurement-contract-v1":
        fail("unexpected contract_version")
    if manifest.get("roadmap_id") != "E01":
        fail("roadmap_id must be E01")
    if manifest.get("status") != "predeclared-phase-a":
        fail("status must remain predeclared-phase-a")
    typing = manifest.get("typed_composition_contract")
    if typing != {
        "applies_to_candidates": ["A", "B", "C", "D"],
        "positive_controls_must_type_check": True,
        "negative_cases": [
            "Artifact[BackendBinary]-as-Artifact[IOSApp]",
            "Endpoint[API]-as-distinct-endpoint",
        ],
        "typescript_requires_pinned_semantic_checker": True,
        "typescript_transpilation_only_is_accepted": False,
        "unavailable_checker_result": "reproducible-infeasibility",
    }:
        fail("typed composition contract must apply equally to A, B, C, and D")
    verify_workflows(manifest)
    verify_effect_probe(manifest)
    verify_control(manifest)
    verify_phase_boundary()
    print("verify-phase-a: PASS")


if __name__ == "__main__":
    main()
