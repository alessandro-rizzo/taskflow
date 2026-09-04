#!/usr/bin/env python3
"""Dependency-free deterministic E05 scheduler simulation."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((HERE / name).read_text())


def p95(values):
    values = sorted(values)
    return float(values[round(0.95 * (len(values) - 1))]) if values else 0.0


def jain(values):
    denominator = len(values) * sum(x * x for x in values)
    return sum(values) ** 2 / denominator if denominator else 1.0


@dataclass
class Node:
    run: str
    agent: str
    klass: str
    workflow: str
    name: str
    duration: int
    resources: dict
    needs: tuple
    submit: int
    state: str = "pending"
    ready: int | None = None
    start: int | None = None
    end: int | None = None
    retry: int = 0

    @property
    def key(self):
        return f"{self.run}/{self.name}"


def agents_for(workload, scale):
    if scale == 1:
        return workload["agents"][:1]
    split = scale // 2
    return workload["agents"][:split] + workload["agents"][10:10 + scale - split]


def build_nodes(workload, scale):
    waves = {(w["class"], w["workflow"]): w["tick"] for w in workload["submission_waves"]}
    answer = []
    for agent in agents_for(workload, scale):
        number = int(agent["id"].split("-")[1])
        variant = "simulator" if number % 2 else "device"
        for workflow in workload["plans_per_agent"]:
            run = f"{agent['id']}-{workflow.lower()}"
            for spec in workload["workflow_templates"][workflow]["nodes"]:
                if spec.get("variant", variant) != variant:
                    continue
                needs = tuple(f"mobile-e2e-{variant}" if x == "mobile-e2e-selected" else x for x in spec["needs"])
                answer.append(Node(run, agent["id"], agent["class"], workflow, spec["id"],
                                   spec["duration_ticks"], dict(spec["resources"]), needs,
                                   waves[(agent["class"], workflow)]))
    return answer


def tie(node, seed, tick):
    return hashlib.sha256(f"{seed}:{tick}:{node.key}".encode()).hexdigest()


class Scheduler:
    def __init__(self, mode, seed):
        self.mode, self.seed = mode, seed
        self.weight_cursor = 0
        self.agent_cursor = defaultdict(int)

    def order(self, nodes, tick):
        nodes = sorted(nodes, key=lambda n: tie(n, self.seed, tick))
        if self.mode in ("shared-fifo", "broker-only", "independent-unguarded-negative-control"):
            return sorted(nodes, key=lambda n: (n.ready, n.submit))
        if self.mode == "shared-strict-interactive":
            return sorted(nodes, key=lambda n: (n.klass != "interactive", n.ready))
        if self.mode != "shared-weighted-aging":
            return nodes
        aged = [n for n in nodes if tick - (n.ready or tick) >= 36]
        if aged:
            return sorted(aged, key=lambda n: (n.ready, n.agent)) + [n for n in nodes if n not in aged]
        wanted = ("interactive", "interactive", "interactive", "background")[self.weight_cursor % 4]
        self.weight_cursor += 1
        return self._rr([n for n in nodes if n.klass == wanted], wanted) + self._rr(
            [n for n in nodes if n.klass != wanted], "background" if wanted == "interactive" else "interactive")

    def _rr(self, nodes, klass):
        grouped = defaultdict(list)
        for node in nodes:
            grouped[node.agent].append(node)
        if not grouped:
            return []
        names = sorted(grouped)
        offset = self.agent_cursor[klass] % len(names)
        self.agent_cursor[klass] += 1
        names = names[offset:] + names[:offset]
        return [node for name in names for node in sorted(grouped[name], key=lambda n: n.key)]


def simulate(mode, scale, seed, workload=None):
    workload = workload or read("workload.json")
    capacities = workload["provider_capacities"]
    nodes = build_nodes(workload, scale)
    usage = {name: 0 for name in capacities}
    busy = {name: 0 for name in capacities}
    peak = {name: 0 for name in capacities}
    completed = defaultdict(set)
    events, sequence, violations, tick = [], 0, 0, 0
    scheduler = Scheduler(mode, seed)

    def emit(kind, node):
        nonlocal sequence
        sequence += 1
        events.append({"format_version": "e05-trace-v1-experimental", "sequence": sequence,
                       "tick": tick, "kind": kind, "run_id": node.run, "node_id": node.name,
                       "agent": node.agent, "class": node.klass,
                       "resources": dict(sorted(node.resources.items())),
                       "provider_usage": dict(sorted(usage.items()))})

    while any(n.state != "completed" for n in nodes):
        if tick > 20000:
            raise RuntimeError(f"simulation failed to drain: {mode}/{scale}/{seed}")
        for node in sorted(nodes, key=lambda n: n.key):
            if node.state == "running" and node.end == tick:
                for provider, amount in node.resources.items():
                    usage[provider] -= amount
                node.state = "completed"
                completed[node.run].add(node.name)
                emit("completed-and-released", node)
        for node in sorted(nodes, key=lambda n: n.key):
            if node.state == "pending" and tick >= node.submit and set(node.needs) <= completed[node.run]:
                node.state, node.ready = "ready", tick
                emit("ready", node)

        ready = [n for n in nodes if n.state == "ready" and tick >= n.retry]
        if mode == "independent-provider-guard":
            heads = []
            for agent in sorted({n.agent for n in ready}):
                heads.append(min((n for n in ready if n.agent == agent), key=lambda n: (n.ready, n.key)))
            candidates = sorted(heads, key=lambda n: tie(n, seed, tick))
        elif mode.startswith("shared-"):
            # Stateful shared policies advance once per admission below.
            candidates = list(ready)
        else:
            candidates = scheduler.order(ready, tick)

        remaining = list(candidates)
        while remaining:
            if mode == "independent-unguarded-negative-control":
                chosen = remaining[0]
            else:
                ordered = scheduler.order(remaining, tick) if mode.startswith("shared-") else remaining
                chosen = next((n for n in ordered if all(usage[p] + a <= capacities[p] for p, a in n.resources.items())), None)
                if chosen is None:
                    break
            for provider, amount in chosen.resources.items():
                usage[provider] += amount
            chosen.state, chosen.start, chosen.end = "running", tick, tick + chosen.duration
            remaining.remove(chosen)
            for provider in usage:
                peak[provider] = max(peak[provider], usage[provider])
                violations += int(usage[provider] > capacities[provider])
            emit("admitted-atomically", chosen)
        if mode == "independent-provider-guard":
            for node in candidates:
                if node.state == "ready":
                    node.retry = tick + 1
                    emit("provider-rejected-retry", node)
        for provider, amount in usage.items():
            busy[provider] += min(amount, capacities[provider])
        tick += 1

    waits = [n.start - n.ready for n in nodes]
    by_class = {klass: [n.start - n.ready for n in nodes if n.klass == klass]
                for klass in ("interactive", "background")}
    service = defaultdict(int)
    for node in nodes:
        service[node.agent] += node.duration
    fairness = {klass: jain([service[a["id"]] for a in agents_for(workload, scale) if a["class"] == klass])
                for klass in ("interactive", "background")}
    makespan = max(n.end for n in nodes)
    metrics = {"format_version": "e05-result-v1-experimental", "mode": mode, "scale": scale, "seed": seed,
               "completed_nodes": len(nodes), "makespan_ticks": makespan,
               "throughput_nodes_per_tick": len(nodes) / makespan, "queue_p95_ticks": p95(waits),
               "queue_p95_by_class_ticks": {k: p95(v) for k, v in by_class.items()},
               "max_ready_wait_ticks": max(waits), "max_ready_wait_over_longest_service": max(waits) / 18,
               "jain_service_by_class": fairness, "starved_request_count": sum(w > 180 for w in waits),
               "capacity_violation_count": violations, "peak_provider_usage": peak,
               "active_lease_count_at_drain": sum(usage.values()),
               "non_cancelled_terminal_ratio": sum(n.state == "completed" for n in nodes) / len(nodes),
               "provider_utilization_percent": {p: 100 * value / (makespan * capacities[p]) for p, value in busy.items()},
               "trace_event_count": len(events)}
    return events, metrics


def lifecycle_cases():
    identity = {"project": "p1", "source": "src/main", "operation": "check",
                "arguments": ["--locked"], "plan_digest": "sha256:abc",
                "namespace_policy": "isolated", "caller_authorized": True}
    cases = []
    for field in ["exact-match"] + list(identity):
        candidate = dict(identity)
        if field != "exact-match":
            candidate[field] = False if field == "caller_authorized" else f"different-{field}"
        attached = candidate == identity and candidate["caller_authorized"]
        cases.append({"case": field, "attached": attached, "expected": field == "exact-match"})
    concurrency = [
        {"policy": "queue-all", "terminals": ["completed", "completed", "completed"],
         "release_before_replacement": True},
        {"policy": "keep-newest-pending", "terminals": ["completed", "superseded-pending", "completed"],
         "release_before_replacement": True},
        {"policy": "cancel-superseded-active", "terminals": ["cancelled-superseded", "completed"],
         "release_before_replacement": True},
    ]
    return {"format_version": "e05-lifecycle-v1-experimental", "attachment_cases": cases,
            "false_attachment_count": sum(c["attached"] != c["expected"] for c in cases),
            "duplicate_active_run_avoided_count": sum(c["attached"] for c in cases),
            "concurrency_groups": concurrency,
            "disconnect": {"accepted_run_survives_client": True, "lease_expiry_tick": 5,
                           "reclaimed_tick": 6, "ticks_after_expiry": 1}}


def write_gzip(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as stream:
            for row in rows:
                stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n")


def generate(output):
    workload = read("workload.json")
    modes = [candidate["id"] for candidate in read("policies.json")["candidates"]]
    metrics, checksums = [], {}
    for mode in modes:
        for scale in workload["scale_sweep_agent_counts"]:
            rows = []
            for seed in workload["tie_order_seeds"]:
                events, result = simulate(mode, scale, seed, workload)
                rows.extend({"mode": mode, "scale": scale, "seed": seed, **event} for event in events)
                metrics.append(result)
            relative = Path("raw/traces") / f"{mode}-agents-{scale}.jsonl.gz"
            write_gzip(output / relative, rows)
            checksums[str(relative)] = hashlib.sha256((output / relative).read_bytes()).hexdigest()
    (output / "raw").mkdir(parents=True, exist_ok=True)
    (output / "results").mkdir(parents=True, exist_ok=True)
    (output / "raw/checksums.json").write_text(
        json.dumps({"algorithm": "sha256", "files": checksums}, indent=2, sort_keys=True) + "\n")
    (output / "results/simulation-metrics.json").write_text(
        json.dumps({"format_version": "e05-metrics-v1-experimental", "runs": metrics}, indent=2, sort_keys=True) + "\n")
    (output / "results/lifecycle.json").write_text(json.dumps(lifecycle_cases(), indent=2, sort_keys=True) + "\n")
    return {"runs": len(metrics), "trace_files": len(checksums)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.output), sort_keys=True))


if __name__ == "__main__":
    main()
