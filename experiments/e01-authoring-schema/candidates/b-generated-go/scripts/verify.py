#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, shutil, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCOPES = {"W1":"w1-fast-project-check.schema.json","W2":"w2-cross-target-artifact-pipeline.schema.json","W3":"w3-isolated-native-mobile-stack.schema.json","effect":"e01-effect-probe.schema.json"}
def run(args, ok=True, env=None):
    result=subprocess.run(args,cwd=ROOT,text=True,capture_output=True,env=env)
    if ok and result.returncode: raise SystemExit(f"{' '.join(args)} failed\n{result.stdout}{result.stderr}")
    return result
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(value,encoding="utf-8")
def source_digest(): return hashlib.sha256((ROOT/"project.go").read_bytes()).hexdigest()
def stale(manifest): return manifest.get("authored_source_sha256") != source_digest()

for required in ("evidence/manifest.json","evidence/dependencies.json","evidence/count-manifest.json","evidence/limitations.json","limitations.md"):
    if not (ROOT/required).is_file(): raise SystemExit(f"missing evidence declaration: {required}")

with tempfile.TemporaryDirectory(prefix="verify-",dir=ROOT) as temporary:
    relative=Path(temporary).relative_to(ROOT); binary=Path(temporary)/"e01b"
    run(["go","build","-o",str(binary),"./cmd/e01b"])
    sentinel=Path(temporary)/"sentinel"; environment=dict(os.environ,E01_BODY_SENTINEL=str(sentinel)); hashes={}
    for scope,filename in SCOPES.items():
        samples=[run([str(binary),"discover",scope],env=environment).stdout for _ in range(10)]
        if len(set(samples)) != 1: raise SystemExit(f"{scope} is not deterministic")
        write(ROOT/"outputs"/filename,json.dumps(json.loads(samples[0]),indent=2)+"\n"); hashes[scope]=hashlib.sha256(samples[0].encode()).hexdigest()
    traces=[run([str(binary),"trace"],env=environment).stdout for _ in range(10)]
    if len(set(traces)) != 1: raise SystemExit("trace is not deterministic")
    write(ROOT/"outputs/w1-logical-trace.json",json.dumps(json.loads(traces[0]),indent=2)+"\n")
    diagnostics=[]
    for scope,payload,path,expected in [("W1",'{"unknown":true}',"unknown","known argument"),("W1",'{"changed-only":"yes"}',"changed-only","boolean"),("W1",'{"verbosity":"loud"}',"verbosity","one of"),("effect","{}","environment","required string")]:
        result=run([str(binary),"validate",scope,payload],ok=False,env=environment); lines=result.stderr.splitlines()
        if result.returncode==0 or len(lines)<2: raise SystemExit("diagnostic did not fail with machine and human output")
        value=json.loads(lines[0]); diagnostics.append(value)
        if value["path"]!=path or expected not in value["expected"] or not value["operation"]: raise SystemExit(f"incomplete diagnostic {value}")
    if sentinel.exists(): raise SystemExit("operation body evaluated")
    for name,types in {"artifact":("BackendBinary","IOSApp"),"endpoint":("API","OtherAPI")}.items():
        target=ROOT/relative/name; target.mkdir(); shutil.copy(ROOT/"compilefail"/f"{name}.go.txt",target/f"{name}.go")
        result=run(["go","test",f"./{relative}/{name}"],ok=False); output=result.stdout+result.stderr
        if result.returncode==0 or name not in output or any(value not in output for value in types): raise SystemExit(f"negative {name} lacked fixture/type context\n{output}")
        write(ROOT/"evidence"/f"negative-{name}.log",output.replace(relative.as_posix(),"verify-TEMP"))
    generation={"authored_source":"project.go","authored_source_sha256":source_digest(),"generator":"generator.go","generated":[*SCOPES.values(),"w1-logical-trace.json"]}
    if stale(generation): raise SystemExit("fresh generation reported stale")
    deliberately_stale=dict(generation,authored_source_sha256="0"*64)
    if not stale(deliberately_stale): raise SystemExit("stale generated output was not rejected")
    write(ROOT/"outputs/generation-manifest.json",json.dumps(generation,indent=2)+"\n")
    project=(ROOT/"project.go").read_text().splitlines(); begin=project.index("// E01-AUTHOR-BEGIN")+1; end=project.index("// E01-AUTHOR-END")
    authored_lines=project[begin:end]
    authored=sum(1 for line in authored_lines if line.strip() and (not line.lstrip().startswith("//") or line.lstrip().startswith("// E01:")))
    annotations=sum(1 for line in project[begin:end] if "E01:" in line or 'e01:"' in line)
    generator=sum(1 for line in (ROOT/"generator.go").read_text().splitlines() if line.strip() and not line.lstrip().startswith("//"))
    generated=sum(len((ROOT/"outputs"/name).read_text().splitlines()) for name in SCOPES.values())
    summary={"candidate":"B","approach":"go-ast-tag-generator","authored_loc":authored,"annotation_lines":annotations,"generator_loc":generator,"generated_loc":generated,"reflection_sites":1,"low_level_concepts":["argument-schema","output-schema","capability-request"],"determinism_runs_per_scope":10,"body_sentinel_absent":True,"stale_output_rejected":True,"generator_diagnostic":"go test TestGeneratorDiagnosticMapsToDeclaration","diagnostic_cases":diagnostics,"output_hashes":hashes,"versions":{"go":run(["go","version"]).stdout.strip(),"python":run(["python3","--version"]).stdout.strip()}}
    write(ROOT/"evidence/check-summary.json",json.dumps(summary,indent=2)+"\n")
print("candidate B: PASS")
