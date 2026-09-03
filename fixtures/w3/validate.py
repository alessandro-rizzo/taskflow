#!/usr/bin/env python3
"""Validate the pre-Gate-1 W3 JSON specification fixtures."""

from __future__ import annotations

import json
import posixpath
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

FIXTURE_ID = "w3-isolated-native-mobile-stack"
VERSION = "t1-w3-fixture-v1-experimental"
STATUS = "specification-only"


@dataclass(frozen=True, order=True)
class Diagnostic:
    filename: str
    field: str
    code: str
    detail: str

    def render(self) -> str:
        return f"{self.filename}: {self.field}: [{self.code}] {self.detail}"


@dataclass
class NamespaceRecord:
    path: Path
    namespace_id: str
    values: dict[str, Any]


def non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def add(
    diagnostics: list[Diagnostic],
    path: Path,
    field: str,
    code: str,
    namespace_id: str | None,
    detail: str,
) -> None:
    namespace = namespace_id if namespace_id is not None else "<unknown>"
    diagnostics.append(
        Diagnostic(path.name, field, code, f"namespace={namespace!r} {detail}")
    )


def field(
    container: dict[str, Any] | None,
    key: str,
    predicate: Callable[[Any], bool],
    expected: str,
    diagnostics: list[Diagnostic],
    path: Path,
    field_path: str,
    namespace_id: str | None,
) -> Any | None:
    if container is None or key not in container:
        add(
            diagnostics,
            path,
            field_path,
            "W3-REQUIRED",
            namespace_id,
            f"missing required field; expected {expected}",
        )
        return None
    value = container[key]
    if not predicate(value):
        add(
            diagnostics,
            path,
            field_path,
            "W3-TYPE",
            namespace_id,
            f"expected {expected}; got {type(value).__name__} value={value!r}",
        )
        return None
    return value


def string_field(
    container: dict[str, Any] | None,
    key: str,
    diagnostics: list[Diagnostic],
    path: Path,
    field_path: str,
    namespace_id: str | None,
) -> str | None:
    return field(
        container,
        key,
        non_empty_string,
        "a non-empty string",
        diagnostics,
        path,
        field_path,
        namespace_id,
    )


def object_field(
    container: dict[str, Any] | None,
    key: str,
    diagnostics: list[Diagnostic],
    path: Path,
    field_path: str,
    namespace_id: str | None,
) -> dict[str, Any] | None:
    return field(
        container,
        key,
        lambda value: isinstance(value, dict),
        "an object",
        diagnostics,
        path,
        field_path,
        namespace_id,
    )


def string_list_field(
    container: dict[str, Any] | None,
    key: str,
    diagnostics: list[Diagnostic],
    path: Path,
    field_path: str,
    namespace_id: str | None,
) -> list[str] | None:
    value = field(
        container,
        key,
        lambda item: isinstance(item, list),
        "a non-empty list of non-empty strings",
        diagnostics,
        path,
        field_path,
        namespace_id,
    )
    if value is None:
        return None
    if not value or not all(non_empty_string(item) for item in value):
        add(
            diagnostics,
            path,
            field_path,
            "W3-TYPE",
            namespace_id,
            f"expected a non-empty list of non-empty strings; got value={value!r}",
        )
        return None
    return value


def load(path: Path, diagnostics: list[Diagnostic]) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        diagnostics.append(
            Diagnostic(path.name, "$", "W3-JSON", f"namespace='<unknown>' {error}")
        )
        return None
    if not isinstance(document, dict):
        diagnostics.append(
            Diagnostic(
                path.name,
                "$",
                "W3-TYPE",
                f"namespace='<unknown>' expected an object; got {type(document).__name__}",
            )
        )
        return None
    return document


def validate_common(
    document: dict[str, Any], path: Path, diagnostics: list[Diagnostic]
) -> None:
    for name, expected in (
        ("fixture_id", FIXTURE_ID),
        ("version", VERSION),
        ("status", STATUS),
    ):
        value = string_field(document, name, diagnostics, path, name, None)
        if value is not None and value != expected:
            add(
                diagnostics,
                path,
                name,
                "W3-COMMON-VALUE",
                None,
                f"expected {expected!r}; got {value!r}",
            )


def normalized_path(
    value: str | None,
    diagnostics: list[Diagnostic],
    path: Path,
    field_path: str,
    namespace_id: str | None,
) -> str | None:
    if value is None:
        return None
    normalized = posixpath.normpath(value)
    if not value.startswith("/") or normalized != value:
        add(
            diagnostics,
            path,
            field_path,
            "W3-PATH",
            namespace_id,
            f"expected a normalized absolute POSIX path; got {value!r}",
        )
        return None
    return normalized


def validate_namespace(
    document: dict[str, Any], path: Path, diagnostics: list[Diagnostic]
) -> NamespaceRecord | None:
    namespace_id = string_field(
        document, "namespace_id", diagnostics, path, "namespace_id", None
    )
    string_field(document, "owner", diagnostics, path, "owner", namespace_id)
    writable_root = normalized_path(
        string_field(
            document,
            "writable_root",
            diagnostics,
            path,
            "writable_root",
            namespace_id,
        ),
        diagnostics,
        path,
        "writable_root",
        namespace_id,
    )

    source = object_field(document, "source", diagnostics, path, "source", namespace_id)
    source_id = string_field(source, "id", diagnostics, path, "source.id", namespace_id)
    string_field(source, "description", diagnostics, path, "source.description", namespace_id)

    service = object_field(
        document, "linux_api_service", diagnostics, path, "linux_api_service", namespace_id
    )
    service_name = string_field(
        service, "name", diagnostics, path, "linux_api_service.name", namespace_id
    )
    database_path = normalized_path(
        string_field(
            service,
            "database_path",
            diagnostics,
            path,
            "linux_api_service.database_path",
            namespace_id,
        ),
        diagnostics,
        path,
        "linux_api_service.database_path",
        namespace_id,
    )
    port = field(
        service,
        "port",
        positive_integer,
        "a positive integer (boolean is not an integer)",
        diagnostics,
        path,
        "linux_api_service.port",
        namespace_id,
    )
    service_endpoint_id = string_field(
        service, "endpoint_id", diagnostics, path, "linux_api_service.endpoint_id", namespace_id
    )
    service_producer = object_field(
        service,
        "produced_by",
        diagnostics,
        path,
        "linux_api_service.produced_by",
        namespace_id,
    )
    string_field(
        service_producer,
        "node",
        diagnostics,
        path,
        "linux_api_service.produced_by.node",
        namespace_id,
    )
    service_consumes = string_field(
        service_producer,
        "consumes",
        diagnostics,
        path,
        "linux_api_service.produced_by.consumes",
        namespace_id,
    )

    endpoint = object_field(document, "endpoint", diagnostics, path, "endpoint", namespace_id)
    endpoint_id = string_field(endpoint, "id", diagnostics, path, "endpoint.id", namespace_id)
    target_namespace = string_field(
        endpoint,
        "target_namespace",
        diagnostics,
        path,
        "endpoint.target_namespace",
        namespace_id,
    )
    authorized_consumers = string_list_field(
        endpoint,
        "authorized_consumers",
        diagnostics,
        path,
        "endpoint.authorized_consumers",
        namespace_id,
    )
    route = string_field(endpoint, "route", diagnostics, path, "endpoint.route", namespace_id)

    artifact = object_field(
        document, "macos_artifact", diagnostics, path, "macos_artifact", namespace_id
    )
    artifact_id = string_field(
        artifact, "id", diagnostics, path, "macos_artifact.id", namespace_id
    )
    artifact_producer = object_field(
        artifact,
        "produced_by",
        diagnostics,
        path,
        "macos_artifact.produced_by",
        namespace_id,
    )
    string_field(
        artifact_producer,
        "node",
        diagnostics,
        path,
        "macos_artifact.produced_by.node",
        namespace_id,
    )
    artifact_consumes = string_field(
        artifact_producer,
        "consumes",
        diagnostics,
        path,
        "macos_artifact.produced_by.consumes",
        namespace_id,
    )
    object_field(
        artifact,
        "profile_attestation",
        diagnostics,
        path,
        "macos_artifact.profile_attestation",
        namespace_id,
    )

    simulator = object_field(
        document, "simulator_session", diagnostics, path, "simulator_session", namespace_id
    )
    simulator_id = string_field(
        simulator, "id", diagnostics, path, "simulator_session.id", namespace_id
    )
    lease = object_field(
        simulator,
        "lease",
        diagnostics,
        path,
        "simulator_session.lease",
        namespace_id,
    )
    lease_id = string_field(
        lease, "id", diagnostics, path, "simulator_session.lease.id", namespace_id
    )
    lease_holder = string_field(
        lease, "holder", diagnostics, path, "simulator_session.lease.holder", namespace_id
    )
    string_field(
        lease,
        "acquired_at",
        diagnostics,
        path,
        "simulator_session.lease.acquired_at",
        namespace_id,
    )
    field(
        lease,
        "ttl_seconds",
        positive_integer,
        "a positive integer (boolean is not an integer)",
        diagnostics,
        path,
        "simulator_session.lease.ttl_seconds",
        namespace_id,
    )

    report = object_field(
        document, "mobile_e2e_report", diagnostics, path, "mobile_e2e_report", namespace_id
    )
    report_id = string_field(report, "id", diagnostics, path, "mobile_e2e_report.id", namespace_id)
    consumer_id = string_field(
        report,
        "consumer_id",
        diagnostics,
        path,
        "mobile_e2e_report.consumer_id",
        namespace_id,
    )
    report_consumes = string_list_field(
        report, "consumes", diagnostics, path, "mobile_e2e_report.consumes", namespace_id
    )

    for field_path, consumed in (
        ("linux_api_service.produced_by.consumes", service_consumes),
        ("macos_artifact.produced_by.consumes", artifact_consumes),
    ):
        if source_id is not None and consumed is not None and consumed != source_id:
            add(
                diagnostics,
                path,
                field_path,
                "W3-REFERENCE",
                namespace_id,
                f"must equal local source.id={source_id!r}; got {consumed!r}",
            )

    if service_endpoint_id is not None and endpoint_id is not None and service_endpoint_id != endpoint_id:
        add(
            diagnostics,
            path,
            "linux_api_service.endpoint_id",
            "W3-REFERENCE",
            namespace_id,
            f"must equal local endpoint.id={endpoint_id!r}; got {service_endpoint_id!r}",
        )
    if namespace_id is not None and target_namespace is not None and target_namespace != namespace_id:
        add(
            diagnostics,
            path,
            "endpoint.target_namespace",
            "W3-OWNERSHIP",
            namespace_id,
            f"must equal owning namespace_id={namespace_id!r}; got {target_namespace!r}",
        )
    if namespace_id is not None and lease_holder is not None and lease_holder != namespace_id:
        add(
            diagnostics,
            path,
            "simulator_session.lease.holder",
            "W3-OWNERSHIP",
            namespace_id,
            f"must equal owning namespace_id={namespace_id!r}; got {lease_holder!r}",
        )
    if route is not None and route != "namespace-private":
        add(
            diagnostics,
            path,
            "endpoint.route",
            "W3-ROUTE",
            namespace_id,
            f"must be 'namespace-private'; got {route!r}",
        )
    if consumer_id is not None and authorized_consumers is not None:
        if len(authorized_consumers) != len(set(authorized_consumers)) or set(authorized_consumers) != {consumer_id}:
            add(
                diagnostics,
                path,
                "endpoint.authorized_consumers",
                "W3-AUTHORIZATION",
                namespace_id,
                f"must resolve exactly once to local mobile_e2e_report.consumer_id={consumer_id!r}; "
                f"got {authorized_consumers!r}",
            )

    expected_inputs = [endpoint_id, artifact_id, simulator_id]
    if report_consumes is not None and all(item is not None for item in expected_inputs):
        expected = sorted(expected_inputs)
        if len(report_consumes) != len(set(report_consumes)) or sorted(report_consumes) != expected:
            add(
                diagnostics,
                path,
                "mobile_e2e_report.consumes",
                "W3-REPORT-INPUTS",
                namespace_id,
                f"must contain exactly once each local endpoint/artifact/simulator id={expected!r}; "
                f"got {report_consumes!r}",
            )
    if writable_root is not None and database_path is not None:
        if database_path == writable_root or posixpath.commonpath([writable_root, database_path]) != writable_root:
            add(
                diagnostics,
                path,
                "linux_api_service.database_path",
                "W3-PATH-CONFINEMENT",
                namespace_id,
                f"must be a strict descendant of writable_root={writable_root!r}; got {database_path!r}",
            )

    if namespace_id is None:
        return None
    return NamespaceRecord(
        path,
        namespace_id,
        {
            "namespace_id": namespace_id,
            "writable_root": writable_root,
            "linux_api_service.name": service_name,
            "linux_api_service.port": port,
            "linux_api_service.database_path": database_path,
            "source.id": source_id,
            "endpoint.id": endpoint_id,
            "macos_artifact.id": artifact_id,
            "simulator_session.id": simulator_id,
            "simulator_session.lease.id": lease_id,
            "mobile_e2e_report.id": report_id,
            "mobile_e2e_report.consumer_id": consumer_id,
        },
    )


def collision(
    diagnostics: list[Diagnostic],
    field_path: str,
    value: Any,
    current: NamespaceRecord,
    previous: NamespaceRecord,
    previous_field: str,
) -> None:
    add(
        diagnostics,
        current.path,
        field_path,
        "W3-COLLISION",
        current.namespace_id,
        f"value={value!r} conflicts with field={previous_field!r} "
        f"namespace={previous.namespace_id!r} file={previous.path.name!r}",
    )


def validate_cross_namespace(
    records: list[NamespaceRecord], diagnostics: list[Diagnostic]
) -> None:
    for field_path in ("namespace_id", "linux_api_service.name", "linux_api_service.port"):
        seen: dict[Any, NamespaceRecord] = {}
        for record in records:
            value = record.values[field_path]
            if value is None:
                continue
            if value in seen:
                collision(diagnostics, field_path, value, record, seen[value], field_path)
            else:
                seen[value] = record

    id_fields = (
        "namespace_id",
        "source.id",
        "endpoint.id",
        "macos_artifact.id",
        "simulator_session.id",
        "simulator_session.lease.id",
        "mobile_e2e_report.id",
        "mobile_e2e_report.consumer_id",
    )
    seen_ids: dict[str, tuple[NamespaceRecord, str]] = {}
    for record in records:
        for field_path in id_fields:
            value = record.values[field_path]
            if value is None:
                continue
            if value in seen_ids:
                previous, previous_field = seen_ids[value]
                collision(diagnostics, field_path, value, record, previous, previous_field)
            else:
                seen_ids[value] = (record, field_path)

    prior_paths: list[tuple[str, NamespaceRecord, str]] = []
    for record in records:
        for field_path in ("writable_root", "linux_api_service.database_path"):
            value = record.values[field_path]
            if value is None:
                continue
            for previous_value, previous, previous_field in prior_paths:
                if previous.namespace_id == record.namespace_id:
                    continue
                common = posixpath.commonpath([value, previous_value])
                if value == previous_value or common in (value, previous_value):
                    collision(diagnostics, field_path, value, record, previous, previous_field)
            prior_paths.append((value, record, field_path))


def validate_scenario(
    document: dict[str, Any], path: Path, diagnostics: list[Diagnostic]
) -> None:
    string_field(document, "scenario", diagnostics, path, "scenario", None)
    string_field(document, "description", diagnostics, path, "description", None)
    object_field(document, "given", diagnostics, path, "given", None)
    events = field(
        document,
        "expected_events",
        lambda value: isinstance(value, list),
        "a non-empty list of objects",
        diagnostics,
        path,
        "expected_events",
        None,
    )
    if events is not None:
        if not events:
            add(
                diagnostics,
                path,
                "expected_events",
                "W3-TYPE",
                None,
                "expected a non-empty list of objects; got value=[]",
            )
        for index, event in enumerate(events):
            event_path = f"expected_events[{index}]"
            if not isinstance(event, dict):
                add(
                    diagnostics,
                    path,
                    event_path,
                    "W3-TYPE",
                    None,
                    f"expected an object; got {type(event).__name__} value={event!r}",
                )
                continue
            string_field(event, "event", diagnostics, path, f"{event_path}.event", None)
    string_field(document, "expected_outcome", diagnostics, path, "expected_outcome", None)


def validate_directory(examples_dir: Path) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    all_paths = sorted(examples_dir.glob("*.json"))
    namespace_paths = sorted(examples_dir.glob("namespace-*.json"))
    scenario_paths = sorted(examples_dir.glob("scenario-*.json"))
    recognized_paths = set(namespace_paths) | set(scenario_paths)
    for path in all_paths:
        if path not in recognized_paths:
            diagnostics.append(
                Diagnostic(
                    path.name,
                    "$",
                    "W3-FILESET",
                    "namespace='<unknown>' unrecognized example filename; expected "
                    "namespace-*.json or scenario-*.json",
                )
            )
    if len(namespace_paths) < 2:
        diagnostics.append(
            Diagnostic(
                examples_dir.name,
                "$",
                "W3-FILESET",
                "namespace='<unknown>' expected at least two namespace examples",
            )
        )
    if not scenario_paths:
        diagnostics.append(
            Diagnostic(
                examples_dir.name,
                "$",
                "W3-FILESET",
                "namespace='<unknown>' expected at least one scenario example",
            )
        )

    records: list[NamespaceRecord] = []
    for path in namespace_paths:
        document = load(path, diagnostics)
        if document is not None:
            validate_common(document, path, diagnostics)
            record = validate_namespace(document, path, diagnostics)
            if record is not None:
                records.append(record)
    validate_cross_namespace(records, diagnostics)

    for path in scenario_paths:
        document = load(path, diagnostics)
        if document is not None:
            validate_common(document, path, diagnostics)
            validate_scenario(document, path, diagnostics)
    return sorted(set(diagnostics), key=lambda diagnostic: diagnostic.render())


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        print(f"usage: {Path(argv[0]).name} [examples-directory]", file=sys.stderr)
        return 2
    examples_dir = Path(argv[1]) if len(argv) == 2 else Path(__file__).parent / "examples"
    diagnostics = validate_directory(examples_dir)
    if diagnostics:
        for diagnostic in diagnostics:
            print(diagnostic.render(), file=sys.stderr)
        print(f"FAIL: {len(diagnostics)} W3 fixture invariant violation(s)", file=sys.stderr)
        return 1
    print("PASS: all fixtures/w3 examples satisfy the v1 specification invariants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
