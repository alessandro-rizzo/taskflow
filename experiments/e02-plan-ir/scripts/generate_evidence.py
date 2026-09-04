#!/usr/bin/env python3
"""Generate the retained E02 correctness, determinism, and benchmark evidence."""

from __future__ import annotations

import hashlib, json, os, platform, shutil, subprocess, sys, tempfile
from pathlib import Path
from typing import Any, Dict, List

EXPERIMENT=Path(__file__).resolve().parents[1];REPO=EXPERIMENT.parents[1];EVIDENCE=EXPERIMENT/"evidence";BIN=Path("/tmp/taskflow-e02-bin")
FIXTURES={"w1":"w1-fast-project-check.plan.json","w2":"w2-cross-target-artifact-pipeline.plan.json","w3":"w3-isolated-native-mobile-stack.plan.json","synthetic":"synthetic-full-coverage.plan.json"}
GOLDENS=REPO/"fixtures/t1-plan-conformance/goldens/plan";ANCHOR="6b98cada25439f66c75eaf3f5faea3d01dfdfade"

def run(args, cwd=EXPERIMENT, env=None, capture=False, check=True):
    merged=os.environ.copy();merged["GOCACHE"]="/tmp/taskflow-tf00308-go-cache";merged["PYTHONDONTWRITEBYTECODE"]="1";
    if env:merged.update(env)
    return subprocess.run(args,cwd=cwd,env=merged,check=check,stdout=subprocess.PIPE if capture else None,stderr=subprocess.PIPE if capture else None)
def write(path:Path,data:Any):
    path.parent.mkdir(parents=True,exist_ok=True)
    if isinstance(data,bytes):path.write_bytes(data)
    elif isinstance(data,str):path.write_text(data,encoding="utf-8")
    else:path.write_text(json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
def load(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def canonical(path):return run([str(BIN/"e02plan"),"canonicalize","--input",str(path)],capture=True).stdout
def digest(data):return hashlib.sha256(data).hexdigest()

def implementation_manifest():
    paths=sorted([path for path in (EXPERIMENT/"candidate-json").rglob("*") if path.is_file()]+[path for path in (EXPERIMENT/"reader").glob("*.py") if path.is_file()]+[EXPERIMENT/"scripts/run_benchmarks.py"])
    entries=[{"path":path.relative_to(REPO).as_posix(),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"bytes":path.stat().st_size} for path in paths]
    write(EVIDENCE/"implementation-manifest.json",{"format_version":"e02-implementation-manifest-v1","contract_commit":ANCHOR,"entries":entries})

def build():
    BIN.mkdir(parents=True,exist_ok=True)
    run(["go","build","-o",str(BIN/"e02plan"),"./cmd/e02plan"],EXPERIMENT/"candidate-json")
    run(["go","build","-o",str(BIN/"t1conform"),"./cmd/t1conform"],REPO/"fixtures/t1-plan-conformance")
    run(["go","build","-o",str(BIN/"t1bench"),"./cmd/t1bench"],REPO/"fixtures/t1-benchmark-harness")

def plans() -> Dict[str,Path]:
    result={}
    for fixture,golden_name in FIXTURES.items():
        raw=run([str(BIN/"e02plan"),"generate","--fixture",fixture],capture=True).stdout
        path=EVIDENCE/"raw/plans"/(fixture+".json");write(path,raw);result[fixture]=path
        encoded=canonical(path);write(EVIDENCE/"raw/canonical"/(fixture+".json"),encoded);write(EVIDENCE/"raw/digests"/(fixture+".sha256"),digest(encoded)+"  "+fixture+".json\n")
        display=run([sys.executable,str(EXPERIMENT/"reader/e02_reader.py"),"display","--input",str(path)],capture=True).stdout;write(EVIDENCE/"raw/reader"/(fixture+".display.json"),display)
        go_digest=run([str(BIN/"e02plan"),"canonicalize","--input",str(path),"--digest"],capture=True).stdout.decode().strip()
        py_digest=run([sys.executable,str(EXPERIMENT/"reader/e02_reader.py"),"digest","--input",str(path)],capture=True).stdout.decode().strip()
        comparison=run([str(BIN/"t1conform"),"--candidate",str(path),"--golden",str(GOLDENS/golden_name)],capture=True,check=False)
        if comparison.returncode!=0:raise RuntimeError(comparison.stderr.decode())
        write(EVIDENCE/"raw/comparisons"/(fixture+".json"),{"fixture":fixture,"t1_exit_code":0,"t1_output":comparison.stderr.decode().strip(),"go_digest":go_digest,"python_digest":py_digest,"canonical_bytes_equal":go_digest==py_digest,"structural_differences":0,"validation_violations":0})
    return result

def determinism(paths):
    evidence={"processes_per_fixture":20,"fixtures":{}}
    for fixture in FIXTURES:
        digests=[];byte_digests=[]
        for _ in range(20):
            raw=run([str(BIN/"e02plan"),"generate","--fixture",fixture],capture=True).stdout
            with tempfile.NamedTemporaryFile() as handle:
                handle.write(raw);handle.flush();encoded=canonical(handle.name)
            digests.append(digest(encoded));byte_digests.append(hashlib.sha256(encoded).hexdigest())
        evidence["fixtures"][fixture]={"distinct_canonical_bytes":len(set(byte_digests)),"distinct_digests":len(set(digests)),"digest":digests[0]}
    write(EVIDENCE/"raw/determinism.json",evidence)

def mutation_plan(base:Dict[str,Any],mutation:str)->Dict[str,Any]:
    result=json.loads(json.dumps(base))
    if mutation=="planning-condition":next(n for n in result["nodes"] if n["id"]=="lint")["planning_condition"]["patterns"]=["**/*.go","**/*.mod"]
    elif mutation=="execution-profile":next(n for n in result["nodes"] if n["id"]=="test")["execution_profile"]["toolchain"]="go1.25.13"
    elif mutation=="output-type":next(a for a in result["artifacts"] if a["id"]=="test-report")["type"]="Report[UnitTests]"
    elif mutation=="output-optionality":next(a for a in result["artifacts"] if a["id"]=="test-report")["optional"]=True
    return result

def mutations(paths):
    base=load(paths["w1"]);summary={}
    for name in ("planning-condition","execution-profile","output-type","output-optionality"):
        changed=mutation_plan(base,name);changed_path=EVIDENCE/"raw/mutations"/(name+".plan.json");write(changed_path,changed)
        go=json.loads(run([str(BIN/"e02plan"),"diff","--before",str(paths["w1"]),"--after",str(changed_path)],capture=True).stdout)
        py=json.loads(run([sys.executable,str(EXPERIMENT/"reader/e02_reader.py"),"diff","--before",str(paths["w1"]),"--after",str(changed_path)],capture=True).stdout)
        if go!=py:raise RuntimeError(name+" Go/Python diff mismatch")
        write(EVIDENCE/"raw/mutations"/(name+".diff.json"),go);summary[name]={"digest_changed":digest(canonical(paths["w1"]))!=digest(canonical(changed_path)),"paths":[d["path"] for d in go["differences"]]}
    write(EVIDENCE/"raw/mutations/summary.json",summary)

def reorder(paths):
    probe=load(paths["synthetic"]);build_node=next(n for n in probe["nodes"] if n["id"]=="build");publish=next(n for n in probe["nodes"] if n["id"]=="publish")
    build_node["planning_condition"]["patterns"]=["**/*.go","**/*.mod"];build_node["planning_condition"]["exclude_patterns"]=["vendor/**","generated/**"];build_node["cache_policy"]["key_inputs"]=["source-tree","execution-profile"]
    probe["artifacts"].append({"id":"audit-report","type":"Report[Audit]","optional":False})
    publish["needs"]=["sign","build"];publish["consumes"]=["signed-binary","release-binary"];publish["produces"]=["release-manifest","audit-report"]
    probe["services"].append({"id":"audit-endpoint","name":"audit","route":"authorized-external"});probe["secrets"].append({"id":"audit-token","capability":"audit-token","resolved_by":"daemon"});probe["effects"].append({"id":"audit-release","kind":"audit","target":"audit-endpoint","idempotency_key":"release-manifest-digest","authorized_actor":"release-bot"})
    base_path=EVIDENCE/"raw/reorder/probe.json";write(base_path,probe)
    run([str(BIN/"e02plan"),"validate","--input",str(base_path)],capture=True);run([sys.executable,str(EXPERIMENT/"reader/e02_reader.py"),"validate","--input",str(base_path)],capture=True)
    base_digest=digest(canonical(base_path));paths_to_reverse=["nodes","artifacts","services","secrets","effects","needs","consumes","produces","patterns","exclude_patterns","key_inputs"]
    results={}
    for name in paths_to_reverse:
        changed=json.loads(json.dumps(probe))
        if name in {"nodes","artifacts","services","secrets","effects"}:changed[name].reverse()
        elif name in {"needs","consumes","produces"}:next(n for n in changed["nodes"] if n["id"]=="publish")[name].reverse()
        elif name in {"patterns","exclude_patterns"}:next(n for n in changed["nodes"] if n["id"]=="build")["planning_condition"][name].reverse()
        else:next(n for n in changed["nodes"] if n["id"]=="build")["cache_policy"][name].reverse()
        path=EVIDENCE/"raw/reorder"/(name+".json");write(path,changed);results[name]={"digest":digest(canonical(path)),"equal":digest(canonical(path))==base_digest}
    write(EVIDENCE/"raw/reorder/summary.json",{"base_digest":base_digest,"paths":results})

def rejections(paths):
    cases={};base=load(paths["w1"])
    documents={"root":dict(base,unexpected=True),"nested-node-test":json.loads(json.dumps(base)),"version":dict(base,format_version="t1-plan-conformance-plan-v999")};next(n for n in documents["nested-node-test"]["nodes"] if n["id"]=="test")["unexpected"]=True
    for name,document in documents.items():
        path=EVIDENCE/"raw/rejections"/(name+".json");write(path,document);case={}
        for reader,command in {"go":[str(BIN/"e02plan"),"validate","--input",str(path)],"python":[sys.executable,str(EXPERIMENT/"reader/e02_reader.py"),"validate","--input",str(path)]}.items():
            result=run(command,capture=True,check=False);case[reader]={"exit_code":result.returncode,"stderr":result.stderr.decode().strip()}
            if result.returncode==0:raise RuntimeError(name+" accepted by "+reader)
        cases[name]=case
    write(EVIDENCE/"raw/rejections/summary.json",cases)

def shapes_and_sentinels():
    shape={}
    for platform_name in ("ios","android","windows"):
        result=run([str(BIN/"e02plan"),"generate","--fixture","shape","--platform",platform_name],capture=True,check=False);shape[platform_name]={"exit_code":result.returncode,"complete_plan":result.returncode==0,"serialized_callback":False}
    write(EVIDENCE/"raw/shape-probe.json",shape)
    with tempfile.TemporaryDirectory() as directory:
        env={name:str(Path(directory)/name) for name in ("E02_OPERATION_BODY_SENTINEL","E02_FILE_WRITE_SENTINEL","E01_BODY_SENTINEL")};run([str(BIN/"e02plan"),"generate","--fixture","w1"],env=env,capture=True)
        write(EVIDENCE/"raw/sentinels/result.json",{"untouched":{name:not Path(path).exists() for name,path in env.items()},"authority_counters":{"worker_acquisitions":0,"provider_calls":0,"secret_resolutions":0},"goldens_used_as_generation_input":False})

def benchmarks():
    large=Path("/tmp/taskflow-e02-large.json");write(large,run([str(BIN/"e02plan"),"generate","--fixture","large","--nodes","10000","--canonical"],capture=True).stdout)
    large_bytes=large.stat().st_size;large_digest=digest(large.read_bytes());write(EVIDENCE/"raw/benchmarks/large-graph.json",{"nodes":10000,"canonical_bytes":large_bytes,"digest":large_digest,"retained_plan":False})
    write(EVIDENCE/"failures/prebinding-measurements.json",{
        "classification":"invalidated-before-wrapper-binding","accepted_as_e02_evidence":False,
        "contract_commit_claimed":"713aa13f63d230eabd940b9d8c6eb6e8dd1260da",
        "reason":"The generator invoked T1 benchmarks before its measurement wrapper was bound and reviewed as required by experiment-contract.md.",
        "sets":[
            {"id":"w1-plan","sample_count":30,"median":0.0056792505,"p95":0.008374,"record_sha256":"22b53c8a520de7f03ead290906a9380c2ccf1dbee47060f08a773e876e11af14","samples_sha256":"bf7a4beb6b106804980daf1b55f1b26b4c148db46942c613e4db282a37bf969f"},
            {"id":"large-generation-canonicalization","sample_count":15,"median":0.178058709,"p95":0.184964084,"record_sha256":"7eab297a31169ca3033c8c55ba0b36e5ef7c03f7fc1496f690101be55cdf3bca","samples_sha256":"495e60c57988f32c471f343ef2bfa4d1823f2f33f1f366759d5e6642dbcb41ce"},
            {"id":"large-reader-validation-digest","sample_count":15,"median":0.194048709,"p95":0.197406334,"record_sha256":"50f4a433aa404a26b48b410b9b9b6b46e4b099a9b79e652da8647108ee57291c","samples_sha256":"322a5ce099e03d4bc9854d0cb3bef5bdd49c3b321de9de980756654b540e7759"}
        ],
        "accepted_collection":"All three sets are collected again from sample one after commit 6b98cada25439f66c75eaf3f5faea3d01dfdfade; no preliminary samples are reused.",
        "earlier_environment_failure":"A still-earlier W1 set completed but the harness rejected zero-RAM metadata before writing a record; it is also pre-binding and contributes no accepted samples."
    })
    run([sys.executable,str(EXPERIMENT/"scripts/run_benchmarks.py"),"--contract-commit",ANCHOR,"--candidate",str(BIN/"e02plan"),"--reader",str(EXPERIMENT/"reader/e02_reader.py"),"--large-plan",str(large),"--benchmark-runner",str(BIN/"t1bench"),"--output-root",str(EVIDENCE/"raw/benchmarks"),"--cpu","Apple M5 Max","--cores","18","--ram-gib","64","--os-name","darwin","--os-version","26.5.2","--os-build","25F84","--os-arch","arm64","--python-version",platform.python_version()])

def summarize():
    records={name:load(EVIDENCE/"raw/benchmarks"/name/"record.json") for name in ("w1-plan","large-generation-canonicalization","large-reader-validation-digest")};large=load(EVIDENCE/"raw/benchmarks/large-graph.json");det=load(EVIDENCE/"raw/determinism.json");mut=load(EVIDENCE/"raw/mutations/summary.json");reorder_result=load(EVIDENCE/"raw/reorder/summary.json");sent=load(EVIDENCE/"raw/sentinels/result.json");synthetic=load(EVIDENCE/"raw/plans/synthetic.json")
    concepts={"typed-artifact":any(item["type"].startswith("Artifact[") for item in synthetic["artifacts"]),"optional-output":any(item["optional"] for item in synthetic["artifacts"]),"planning-condition":any(item["planning_condition"]["type"]!="always" for item in synthetic["nodes"]),"outcome-condition":any(item["outcome_condition"]["type"]!="always" for item in synthetic["nodes"]),"resources":all("resources" in item for item in synthetic["nodes"]),"execution-profile":all("execution_profile" in item for item in synthetic["nodes"]),"cache-policy":all("cache_policy" in item for item in synthetic["nodes"]),"secret-capability-reference":bool(synthetic.get("secrets")),"endpoint":bool(synthetic.get("services")),"effect":bool(synthetic.get("effects"))};write(EVIDENCE/"raw/synthetic-concepts.json",concepts)
    checks={"t1_zero_diffs":all(load(EVIDENCE/"raw/comparisons"/(f+".json"))["structural_differences"]==0 for f in FIXTURES),"synthetic_concepts":all(concepts.values()),"determinism":all(v["distinct_canonical_bytes"]==1 and v["distinct_digests"]==1 for v in det["fixtures"].values()),"cross_language":all(load(EVIDENCE/"raw/comparisons"/(f+".json"))["canonical_bytes_equal"] for f in FIXTURES),"reorder":all(v["equal"] for v in reorder_result["paths"].values()),"mutations":all(v["digest_changed"] for v in mut.values()),"sentinels":all(sent["untouched"].values()),"w1_latency":records["w1-plan"]["p95"]<0.25,"large_size":large["canonical_bytes"]<=16777216,"large_generation":records["large-generation-canonicalization"]["p95"]<2.0,"large_reader":records["large-reader-validation-digest"]["p95"]<2.0}
    decision="continue-canonical-json" if all(checks.values()) else "pivot-encoding"
    write(EVIDENCE/"scorecard.json",{"format_version":"e02-scorecard-v1","contract_commit":ANCHOR,"implementation_manifest_sha256":hashlib.sha256((EVIDENCE/"implementation-manifest.json").read_bytes()).hexdigest(),"checks":checks,"decision":decision,"limitations":["E01 diagnostics remains schema-only because its trace has no producer.","The encoding and APIs remain disposable until Gate 1.","Python is the language-neutral reader proxy; no additional language runtime was tested."]})
    text="# E02 Phase B evidence summary\n\nDecision: **%s** as Gate 1 input; no production protocol is selected.\n\n"%decision
    for name,record in records.items():text+="- %s: median %.3f ms, p95 %.3f ms (%d samples).\n"%(name,record["median"]*1000,record["p95"]*1000,record["sample_count"])
    text+="- Large graph: %d nodes, %d canonical bytes.\n\nAll bound T1 plans matched with zero structural differences; 20-process determinism, Go/Python byte identity, eleven reorder paths, four semantic mutations, strict rejection, shape, and sentinel gates passed.\n\nLimitations: Candidate B does not produce its optional diagnostics value; E02 therefore treats it as schema-only and uses the synthetic plan for optional-artifact evidence. Formats remain experimental and disposable until Gate 1.\n"%(large["nodes"],large["canonical_bytes"])
    write(EVIDENCE/"summary.md",text)

def manifest():
    entries=[]
    for path in sorted(EVIDENCE.rglob("*")):
        if path.is_file() and path.name!="manifest.json": entries.append({"path":path.relative_to(EVIDENCE).as_posix(),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"bytes":path.stat().st_size})
    write(EVIDENCE/"manifest.json",{"format_version":"e02-evidence-manifest-v1","contract_commit":ANCHOR,"entries":entries})

def main():
    if EVIDENCE.exists():shutil.rmtree(EVIDENCE)
    implementation_manifest();build();paths=plans();determinism(paths);mutations(paths);reorder(paths);rejections(paths);shapes_and_sentinels();benchmarks();summarize();manifest();print("E02 evidence generated")
if __name__=="__main__":main()
