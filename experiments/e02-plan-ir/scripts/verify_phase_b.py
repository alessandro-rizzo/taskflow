#!/usr/bin/env python3
"""Verify the corrected Phase A snapshot and all retained E02 Phase B evidence."""
import hashlib,io,json,subprocess,sys,tarfile,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];EXPERIMENT=ROOT/"experiments/e02-plan-ir";ANCHOR="6b98cada25439f66c75eaf3f5faea3d01dfdfade"
def require(value,message):
    if not value:raise SystemExit("verify-e02-phase-b: "+message)
def snapshot():
    archive=subprocess.run(["git","archive",ANCHOR],cwd=ROOT,check=True,stdout=subprocess.PIPE).stdout
    with tempfile.TemporaryDirectory() as directory:
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:bundle.extractall(directory)
        result=subprocess.run([sys.executable,str(Path(directory)/"experiments/e02-plan-ir/scripts/verify_contract.py"),"--phase-a-only"],cwd=directory,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        require(result.returncode==0,"corrected Phase A snapshot failed: "+result.stdout)
def load(path):return json.loads(path.read_text(encoding="utf-8"))
def benchmark(record):
    samples=record["samples"];require(record["sample_count"]==len(samples) and samples,"benchmark samples invalid")
    ordered=sorted(samples);middle=len(ordered)//2;median=ordered[middle] if len(ordered)%2 else (ordered[middle-1]+ordered[middle])/2
    index=round(0.95*(len(ordered)-1));require(abs(record["median"]-median)<1e-12 and abs(record["p95"]-ordered[index])<1e-12,"benchmark statistics inconsistent")
def implementation(evidence):
    document=load(evidence/"implementation-manifest.json");require(document["format_version"]=="e02-implementation-manifest-v1" and document["contract_commit"]==ANCHOR,"implementation manifest header changed")
    expected={path.relative_to(ROOT).as_posix() for path in (EXPERIMENT/"candidate-json").rglob("*") if path.is_file()}|{path.relative_to(ROOT).as_posix() for path in (EXPERIMENT/"reader").glob("*.py") if path.is_file()}|{"experiments/e02-plan-ir/scripts/run_benchmarks.py"}
    require({item["path"] for item in document["entries"]}==expected,"implementation manifest file set mismatch")
    require(all((ROOT/item["path"]).is_file() and hashlib.sha256((ROOT/item["path"]).read_bytes()).hexdigest()==item["sha256"] and (ROOT/item["path"]).stat().st_size==item["bytes"] for item in document["entries"]),"measured implementation differs from manifest")
def main():
    snapshot();evidence=EXPERIMENT/"evidence";implementation(evidence);manifest=load(evidence/"manifest.json");require(manifest["contract_commit"]==ANCHOR,"evidence manifest anchor changed")
    listed={item["path"] for item in manifest["entries"]};actual={path.relative_to(evidence).as_posix() for path in evidence.rglob("*") if path.is_file() and path.name!="manifest.json"};require(listed==actual,"evidence manifest file set mismatch")
    require(all((evidence/item["path"]).is_file() and hashlib.sha256((evidence/item["path"]).read_bytes()).hexdigest()==item["sha256"] and (evidence/item["path"]).stat().st_size==item["bytes"] for item in manifest["entries"]),"evidence manifest mismatch");score=load(evidence/"scorecard.json");require(score["contract_commit"]==ANCHOR,"wrong contract anchor");require(score["implementation_manifest_sha256"]==hashlib.sha256((evidence/"implementation-manifest.json").read_bytes()).hexdigest(),"scorecard implementation binding changed");require(score["decision"]=="continue-canonical-json","decision does not follow passing gates");require(all(score["checks"].values()),"one or more scorecard gates failed")
    for fixture in ("w1","w2","w3","synthetic"):
        comparison=load(evidence/"raw/comparisons"/(fixture+".json"));require(comparison["t1_exit_code"]==0 and comparison["structural_differences"]==0 and comparison["validation_violations"]==0,"T1 comparison failed: "+fixture);require(comparison["canonical_bytes_equal"],"cross-language mismatch: "+fixture)
    concepts=load(evidence/"raw/synthetic-concepts.json");require(set(concepts)=={"typed-artifact","optional-output","planning-condition","outcome-condition","resources","execution-profile","cache-policy","secret-capability-reference","endpoint","effect"} and all(concepts.values()),"synthetic concept coverage failed")
    deterministic=load(evidence/"raw/determinism.json");require(deterministic["processes_per_fixture"]==20,"determinism sample count changed");require(all(item["distinct_canonical_bytes"]==1 and item["distinct_digests"]==1 for item in deterministic["fixtures"].values()),"determinism failed")
    reorder=load(evidence/"raw/reorder/summary.json");require(len(reorder["paths"])==11 and all(item["equal"] for item in reorder["paths"].values()),"reorder gate failed")
    mutations=load(evidence/"raw/mutations/summary.json");expected={"planning-condition":["$.nodes[id=lint].planning_condition.patterns"],"execution-profile":["$.nodes[id=test].execution_profile.toolchain"],"output-type":["$.artifacts[id=test-report].type"],"output-optionality":["$.artifacts[id=test-report].optional"]};require({key:value["paths"] for key,value in mutations.items()}==expected,"mutation paths changed");require(all(value["digest_changed"] for value in mutations.values()),"mutation digest unchanged")
    rejections=load(evidence/"raw/rejections/summary.json");paths={"root":"$.unexpected","nested-node-test":"$.nodes[id=test].unexpected","version":"$.format_version"};require(all(case[reader]["exit_code"]!=0 and paths[name] in case[reader]["stderr"] for name,case in rejections.items() for reader in ("go","python")),"stable rejection path missing")
    shape=load(evidence/"raw/shape-probe.json");require(shape["ios"]["complete_plan"] and shape["android"]["complete_plan"] and shape["windows"]["exit_code"]!=0 and not any(value["serialized_callback"] for value in shape.values()),"bounded shape probe failed")
    sentinel=load(evidence/"raw/sentinels/result.json");require(all(sentinel["untouched"].values()),"sentinel touched");require(set(sentinel["authority_counters"].values())=={0},"authority accessed")
    records={name:load(evidence/"raw/benchmarks"/name/"record.json") for name in ("w1-plan","large-generation-canonicalization","large-reader-validation-digest")};[benchmark(record) for record in records.values()];require(records["w1-plan"]["sample_count"]==30 and records["w1-plan"]["p95"]<0.25,"W1 benchmark failed");require(records["large-generation-canonicalization"]["sample_count"]==15 and records["large-generation-canonicalization"]["p95"]<2.0,"large generation failed");require(records["large-reader-validation-digest"]["sample_count"]==15 and records["large-reader-validation-digest"]["p95"]<2.0,"large reader failed");large=load(evidence/"raw/benchmarks/large-graph.json");require(large["nodes"]==10000 and large["canonical_bytes"]<=16777216,"large graph failed")
    preliminary=load(evidence/"failures/prebinding-measurements.json");require(preliminary["classification"]=="invalidated-before-wrapper-binding" and not preliminary["accepted_as_e02_evidence"],"pre-binding audit classification changed");require([item["sample_count"] for item in preliminary["sets"]]==[30,15,15],"pre-binding audit set changed")
    print("verify-e02-phase-b: PASS decision=continue-canonical-json")
if __name__=="__main__":main()
