#!/usr/bin/env python3
"""E06 VM acquisition proposal and measurement contract; no execution backend.

All actions returned here are review data. Installing, booting and measuring
are distinct stages. The native runner is deliberately not imported.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


HERE = Path(__file__).resolve().parent
PHASE_A = HERE.parents[1]
ROOT = "/private/tmp/taskflow-e06-vm-a"
RELEASE = "https://github.com/openai/tart/releases/download/2.36.0/tart.tar.gz"
TART_SHA = "c72a8ab8d78a6498a1e42688b1a1ec6c512ce46ca35a3a3be130c3de1440c7e8"
IMAGE_SHA = "61f6e857a3d65dd2f8daf9c51c7b837fa458bcc9181ae8556e645b534dab6bf6"
IMAGE = "ghcr.io/cirruslabs/macos-tahoe-xcode@sha256:" + IMAGE_SHA
TART = ROOT + "/tools/tart-2.36.0/tart.app/Contents/MacOS/tart"
INPUTS = {
    "measurement-plan.json": "50fd5713f014a85b671ee1a89e58604b7518e9df2fad31cb49401c5112a9001f",
    "execution-manifest.schema.json": "396ad8f5ebad541c2144f0db1e5578e11a4c2872f37e72766231911d1c801ea2",
    "phase-b/execution/contract.json": "04801dc0837e2a970c4ca28c2dbe402ece7a030ada0613a6bc73927dfbbd3c69",
}


class ContractError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ContractError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load(name):
    return json.loads((HERE / name).read_text())


def owned_path(value, root=ROOT):
    require(isinstance(value, str) and value.startswith(root + "/"), "path outside owned root")
    require(str(PurePosixPath(value)) == value and ".." not in PurePosixPath(value).parts,
            "noncanonical path")
    require(not any(c in value for c in "\n\r\x00*?[]"), "unsafe path characters")
    return value


def require_absent_root(path=Path(ROOT)):
    """Read-only acquisition precondition, including broken symlinks."""
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), "symlink in acquisition path")
    require(not path.exists(), "acquisition root already exists; inspect, never overwrite")


def verify(contract, pins):
    require(contract["experiment_id"] == "E06" and contract["task_id"] == "TF-003.14", "wrong ticket")
    require(contract["status"] == "acquisition-proposal-awaiting-approval", "proposal status changed")
    require(contract["anchor_commit"] == "e794e615f5147e08c2ef16cb59937d11f1e3161e", "anchor changed")
    require(contract["inputs"] == INPUTS, "frozen inputs omitted or changed")
    require(contract["candidate_order"] == ["warm-vm-apfs-workspaces", "warm-immutable-vm-restore", "vm-per-namespace"],
            "candidate order changed")
    require(type(contract["execution_count"]) is int and contract["execution_count"] == 0,
            "proposal cannot contain execution results")
    require(pins["controller"]["version"] == "2.36.0" and pins["controller"]["sha256"] == TART_SHA
            and pins["controller"]["url"] == RELEASE, "controller pin drift")
    require(pins["controller"]["size_bytes"] == 22905967, "controller size drift")
    require(pins["controller"]["installed"] is False, "acquisition state claimed prematurely")
    image = pins["image"]
    require(image["reference"] == IMAGE and image["manifest_sha256"] == IMAGE_SHA, "image pin drift")
    require(image["tag"] == "26.5" and image["repository"] == "cirruslabs/macos-tahoe-xcode", "image name drift")
    require(image["profile_approved"] is False and image["disk_downloaded"] is False,
            "metadata is not image acquisition or approval")
    require(image["compressed_layer_bytes"] == 68828940474
            and image["annotations"]["org.cirruslabs.tart.uncompressed-disk-size"] == "140000000000",
            "image size drift")
    profile = pins["guest_profile"]
    require(profile["expected_xcode_version"] == "26.5" and profile["expected_architecture"] == "arm64",
            "alternative guest profile changed")
    require(profile["attested"] is False and profile["native_profile_equivalent"] is False,
            "guest profile is not live attestation")
    for key in ("macos_version", "macos_build", "xcode_build", "sdk_version", "sdk_build",
                "simulator_runtime_version", "simulator_runtime_build"):
        require(profile[key] is None, "invented guest identity: " + key)
    paths = contract["storage"]
    require(paths["host_root"] == ROOT and paths["guest_root"] == ROOT, "root drift")
    require(paths["tart_home"] == ROOT + "/tart", "Tart storage drift")
    require(paths["controller_directory"] == ROOT + "/tools/tart-2.36.0", "controller location drift")
    require(paths["evidence_root"] == "experiments/e06-macos-feasibility/evidence/taskflow-e06-vm-a",
            "evidence root drift")
    require(paths["immutable_base_vm_name"] == "taskflow-e06-vm-a-base"
            and paths["preflight_vm_name"] == "taskflow-e06-vm-a-preflight", "VM name drift")
    resource = contract["resources"]
    require(resource == {"initial_vm_cpu": 6, "initial_vm_memory_mib": 16384, "initial_vm_count": 1,
                         "host_min_free_ram_gib": 16, "host_min_free_disk_gib": 200,
                         "thermal_stop": "serious", "concurrency_levels": [1, 2, 3, 4],
                         "concurrency_repetitions": 5, "namespace_count_is_not_vm_count": True},
            "resource contract changed")
    policy = contract["policies"]
    for key in ("automatic_pruning", "clipboard", "audio", "host_privilege_changes",
                "simulated_records_are_measurements"):
        require(policy[key] is False, "unsafe policy: " + key)
    for key in ("host_root_must_be_absent", "simulator_in_guest_only", "host_CoreSimulator_forbidden",
                "vm_and_image_delete_requires_separate_approval"):
        require(policy[key] is True, "missing boundary: " + key)
    require(policy["shares"] == [], "host directory sharing is forbidden")
    require([x["id"] for x in contract["stages"]] == ["acquire", "guest-preflight", "implementation", "smoke", "matrix"],
            "stage order changed")
    for relative, expected in contract["inputs"].items():
        require(".." not in PurePosixPath(relative).parts and not relative.startswith("/"), "input path escaped")
        require(hashlib.sha256((PHASE_A / relative).read_bytes()).hexdigest() == expected,
                "frozen input changed: " + relative)


def acquisition_ledger():
    """Exact command proposals and explicit checks for the acquisition stage."""
    archive = ROOT + "/downloads/tart-2.36.0.tar.gz"
    bundle = ROOT + "/tools/tart-2.36.0/tart.app"
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C", "LC_ALL": "C",
           "CFFIXED_USER_HOME": ROOT,
           "TART_HOME": ROOT + "/tart", "TART_NO_AUTO_PRUNE": "1", "TMPDIR": ROOT + "/tmp"}
    rows = []

    def add(kind, args, targets=(), timeout=900, result="exit zero"):
        i = len(rows) + 1
        rows.append({"id": "acquire-%02d" % i, "kind": kind, "arguments": args,
                     "targets": list(targets), "mutates": bool(targets), "timeout_seconds": timeout,
                     "requires": [] if i == 1 else ["acquire-%02d" % (i - 1)],
                     "acceptance": result, "cleanup": "retain; separate removal approval required",
                     "receipt": ROOT + "/receipts/acquire-%02d.json" % i})

    add("check", ["explicit acquisition approval binds pins, contract and ledger digests",
                  "approval accepts Xcode 26.5 as a candidate guest profile; not a native-profile match",
                  "host root absent and no symlink parents", "host free disk >= 600 GiB",
                  "400 GiB maximum task allocation including archive, image and import; retain >= 200 GiB free"])
    add("command", ["/bin/mkdir", "-m", "700", ROOT], [ROOT])
    dirs = [ROOT + x for x in ("/downloads", "/tools/tart-2.36.0", "/tart", "/tmp", "/receipts")]
    add("command", ["/bin/mkdir", "-p", *dirs], dirs)
    add("command", ["/usr/bin/curl", "--disable", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https",
                    "--connect-timeout", "30", "--max-time", "900", "--output", archive, RELEASE], [archive])
    add("check", ["archive bytes == 22905967", "archive SHA-256 == " + TART_SHA])
    add("check", ["inspect tar member paths and link graph before extraction",
                  "allow only tart.app descendants and one regular top-level LICENSE file",
                  "allow only files, directories and relative in-bundle symlinks",
                  "reject traversal, absolute paths, hard links, special files, symlink escapes and cycles"])
    add("command", ["/usr/bin/tar", "-xzf", archive, "-C", ROOT + "/tools/tart-2.36.0"],
        [bundle, ROOT + "/tools/tart-2.36.0/LICENSE"])
    add("command", ["/usr/bin/codesign", "--verify", "--deep", "--strict", bundle])
    add("command", ["/usr/bin/codesign", "--display", "--verbose=4", bundle], result="record signed identity; retain embedded provisioning profile")
    add("command", ["/usr/sbin/spctl", "--assess", "--type", "execute", "--verbose=2", bundle],
        result="Gatekeeper accepts; never bypass quarantine or alter policy")
    add("tart-command", [TART, "--version"], [ROOT + "/tart", ROOT + "/tmp"], result="version is 2.36.0")
    # Pull only: no VM clone, boot, simctl or credentials on the host.
    add("tart-command", [TART, "pull", IMAGE], [ROOT + "/tart", ROOT + "/tmp"], timeout=14400,
        result="OCI manifest and all layers verify; keep >= 200 GiB host free and <= 400 GiB task allocation")
    add("check", ["record imported config/NVRAM/disk hashes and allocated bytes",
                  "compare imported OCI manifest against pinned SHA-256",
                  "record actual acquisition bytes and duration separately from warm measurement",
                  "verify zero running experiment VMs; stop before guest preflight"])
    return {"stage": "acquire", "execution_supported": False, "controller_environment": env,
            "inherit_environment": False, "environment_applies_to": "all commands; TMPDIR after acquire-03",
            "receipt_write_root": ROOT + "/receipts", "operations": rows,
            "incidental_host_effects": ["macOS signature/Gatekeeper cache and security checks",
                                       "Tart internal GC and transient files only in the new TART_HOME/tmp",
                                       "HTTPS public-registry token and release/CDN transfers"],
            "failure_rule": "Stop and retain exact paths/partial import. No automatic deletion, retry with changed pins, or scope expansion."}


def verify_ledger(ledger):
    # Exact comparison binds all targets, checks, flags, environments and timeouts.
    require(ledger == acquisition_ledger(), "acquisition ledger differs from reviewed schedule")


def measurement_contract():
    # Reuse the owning experiment's frozen counts/boundaries without inventing
    # a second measurement schema or importing the native execution backend.
    measurement = json.loads((PHASE_A / "measurement-plan.json").read_text())
    return {"stage": "matrix", "execution_supported": False, "source": "measurement-plan.json",
            "contract": measurement, "namespace_levels": [1, 2, 3, 4],
            "required_vm_specific_evidence": ["15 cold boots", "5 VM-loss recoveries",
                                             "15 local image imports", "one actual image update/rollback",
                                             "immutable base integrity before and after sample sets"],
            "admission": "Only after live guest attestation, exact VM/guest operation ledger, implementation review and execution approval.",
            "unsupported_rule": "Record an unmeasured/rejected mechanism explicitly; never manufacture VM samples from native recordings."}


def record_plan(contract, pins):
    verify(contract, pins)
    ledger = acquisition_ledger()
    verify_ledger(ledger)
    return {"status": contract["status"], "contract_sha256": digest(contract), "pins_sha256": digest(pins),
            "ledger_sha256": digest(ledger), "operations_recorded": len(ledger["operations"]),
            "execution_count": 0, "benchmark_samples": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["verify", "describe", "record-plan", "check-acquisition-readiness"])
    args = parser.parse_args()
    contract, pins = load("contract.json"), load("pins.json")
    summary = record_plan(contract, pins)
    verify_ledger(load("acquisition-ledger.json"))
    if args.mode == "check-acquisition-readiness":
        require_absent_root()
    if args.mode == "describe":
        summary.update(acquisition=acquisition_ledger(), measurement=measurement_contract())
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ContractError, KeyError, OSError, ValueError) as exc:
        raise SystemExit("e06-vm-contract: " + str(exc))
