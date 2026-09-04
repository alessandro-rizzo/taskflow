#!/usr/bin/env python3
"""Independent Python 3.9 reader for the disposable E02 plan grammar."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

FORMAT_VERSION = "t1-plan-conformance-plan-v2"
DIFF_VERSION = "e02-resume-diff-v1"
IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
SET_LIKE: Dict[str, str] = {
    "$.nodes": "id", "$.artifacts": "id", "$.services": "id", "$.secrets": "id", "$.effects": "id",
    "$.nodes[*].needs": "", "$.nodes[*].consumes": "", "$.nodes[*].produces": "",
    "$.nodes[*].planning_condition.patterns": "", "$.nodes[*].planning_condition.exclude_patterns": "",
    "$.nodes[*].cache_policy.key_inputs": "",
}

class PlanError(ValueError):
    pass

def pairs_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlanError("duplicate object member: " + key)
        result[key] = value
    return result

def integer(raw: str) -> int:
    if raw == "-0" or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", raw):
        raise PlanError("non-canonical integer: " + raw)
    value = int(raw)
    if not INT64_MIN <= value <= INT64_MAX:
        raise PlanError("integer outside signed 64-bit range: " + raw)
    return value

def reject_number(raw: str) -> Any:
    raise PlanError("non-integer or non-finite number: " + raw)

def loads(raw: bytes) -> Dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=pairs_object, parse_int=integer, parse_float=reject_number, parse_constant=reject_number)
    except (UnicodeDecodeError, json.JSONDecodeError, PlanError) as error:
        raise PlanError(str(error)) from error
    if not isinstance(value, dict):
        raise PlanError("$ must be an object")
    return value

def exact(value: Dict[str, Any], path: str, required: Sequence[str], allowed: Sequence[str]) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise PlanError(path + "." + unknown[0] + " unknown field")
    missing = [key for key in required if key not in value]
    if missing:
        raise PlanError(path + "." + missing[0] + " required")

def objects(parent: Dict[str, Any], key: str, required: bool) -> List[Dict[str, Any]]:
    if key not in parent:
        if required: raise PlanError("$." + key + " required")
        return []
    value = parent[key]
    if not isinstance(value, list): raise PlanError("$." + key + " must be an array")
    for index, item in enumerate(value):
        if not isinstance(item, dict): raise PlanError("$.%s[%d] must be an object" % (key,index))
    return value

def strings(parent: Dict[str, Any], key: str, path: str, required: bool = True) -> List[str]:
    if key not in parent:
        if required: raise PlanError(path + " required")
        return []
    value = parent[key]
    if not isinstance(value, list) or any(not isinstance(item,str) for item in value): raise PlanError(path + " must be a string array")
    if len(value) != len(set(value)): raise PlanError(path + " has duplicate members")
    return value

def declarations(items: List[Dict[str, Any]], path: str, kind: str) -> set:
    result = set()
    shapes = {
        "artifact": (["id","type","optional"], ["id","type","optional"]),
        "service": (["id","name","route"], ["id","name","route"]),
        "secret": (["id","capability","resolved_by"], ["id","capability","resolved_by"]),
        "effect": (["id","kind","target","idempotency_key","authorized_actor"], ["id","kind","target","idempotency_key","authorized_actor"]),
    }
    for index,item in enumerate(items):
        identifier = item.get("id")
        if not isinstance(identifier,str) or not IDENTIFIER.fullmatch(identifier): raise PlanError("%s[%d].id invalid"%(path,index))
        if identifier in result: raise PlanError(path + " duplicate id " + identifier)
        result.add(identifier)
        if kind in shapes: exact(item,path+"[id="+identifier+"]",*shapes[kind])
        if kind == "artifact" and (not isinstance(item["type"],str) or not item["type"] or not isinstance(item["optional"],bool)): raise PlanError(path+"[id="+identifier+"] artifact fields invalid")
        if kind == "secret" and item["resolved_by"] != "daemon": raise PlanError(path+"[id="+identifier+"].resolved_by must be daemon")
        string_fields={"service":["name","route"],"secret":["capability","resolved_by"],"effect":["kind","target","idempotency_key","authorized_actor"]}.get(kind,[])
        if any(not isinstance(item[key],str) or not item[key] for key in string_fields): raise PlanError(path+"[id="+identifier+"] string field invalid")
    return result

def condition(value: Any, path: str, planning: bool) -> None:
    if not isinstance(value,dict) or not isinstance(value.get("type"),str): raise PlanError(path+" must be a condition object")
    kind=value["type"]
    if planning and kind=="changed-paths": exact(value,path,["type","patterns"],["type","patterns","exclude_patterns"]);strings(value,"patterns",path+".patterns");strings(value,"exclude_patterns",path+".exclude_patterns",False);return
    allowed={"always"} if planning else {"always","all-upstream-pass","conditional"}
    if kind not in allowed: raise PlanError(path+".type invalid")
    exact(value,path,["type"],["type"])

def validate(document: Dict[str, Any]) -> None:
    exact(document,"$",["document_kind","format_version","fixture_id","fixture_version","status","nodes","artifacts"],["document_kind","format_version","fixture_id","fixture_version","status","nodes","artifacts","services","secrets","effects"])
    if document["document_kind"] != "plan": raise PlanError("$.document_kind must be plan")
    if document["format_version"] != FORMAT_VERSION: raise PlanError("$.format_version incompatible")
    for key in ("fixture_id","fixture_version","status"):
        if not isinstance(document[key],str) or not document[key]: raise PlanError("$."+key+" must be a non-empty string")
    nodes=objects(document,"nodes",True);artifacts=objects(document,"artifacts",True)
    node_ids=declarations(nodes,"$.nodes","node");artifact_ids=declarations(artifacts,"$.artifacts","artifact")
    declarations(objects(document,"services",False),"$.services","service");declarations(objects(document,"secrets",False),"$.secrets","secret");declarations(objects(document,"effects",False),"$.effects","effect")
    for node in nodes:
        node_id=node["id"];path="$.nodes[id="+node_id+"]"
        exact(node,path,["id","needs","consumes","produces","planning_condition","outcome_condition","resources","execution_profile","cache_policy"],["id","needs","consumes","produces","planning_condition","outcome_condition","resources","execution_profile","cache_policy"])
        for key,known in (("needs",node_ids),("consumes",artifact_ids),("produces",artifact_ids)):
            for reference in strings(node,key,path+"."+key):
                if reference not in known: raise PlanError(path+"."+key+" references unknown "+reference)
        condition(node["planning_condition"],path+".planning_condition",True);condition(node["outcome_condition"],path+".outcome_condition",False)
        resources=node["resources"];exact(resources,path+".resources",["cpu_millicores","memory_mib"],["cpu_millicores","memory_mib"])
        if any(isinstance(resources[key],bool) or not isinstance(resources[key],int) or resources[key]<0 for key in resources): raise PlanError(path+".resources values must be nonnegative integers")
        profile=node["execution_profile"];exact(profile,path+".execution_profile",["os","toolchain"],["os","toolchain","profile_digest","profile_id","target_role"])
        for key in profile:
            if not isinstance(profile[key],str) or not profile[key]: raise PlanError(path+".execution_profile."+key+" must be a non-empty string")
        cache=node["cache_policy"]
        if cache.get("mode")=="none": exact(cache,path+".cache_policy",["mode"],["mode"])
        elif cache.get("mode")=="content-addressed": exact(cache,path+".cache_policy",["mode","key_inputs"],["mode","key_inputs"]);strings(cache,"key_inputs",path+".cache_policy.key_inputs")
        else: raise PlanError(path+".cache_policy.mode invalid")

def normalize(value: Any, path: str) -> Any:
    if isinstance(value,dict): return {key:normalize(child,path+"."+key) for key,child in value.items()}
    if isinstance(value,list):
        result=[normalize(child,path+"[*]") for child in value]
        if path in SET_LIKE:
            field=SET_LIKE[path]
            keys=[item[field] if field else item for item in result]
            if len(keys)!=len(set(keys)): raise PlanError(path+" has duplicate set members")
            result=[item for _,item in sorted(zip(keys,result),key=lambda pair:pair[0].encode("utf-8"))]
        return result
    return value

def canonical(document: Dict[str, Any]) -> bytes:
    return json.dumps(normalize(document,"$"),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")

def digest(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()

def semantic_diff(before: Any, after: Any, path: str, output: List[Dict[str,Any]]) -> None:
    if before==after:return
    if isinstance(before,dict) and isinstance(after,dict):
        for key in sorted(set(before)|set(after)): semantic_diff(before.get(key),after.get(key),path+"."+key,output)
        return
    if isinstance(before,list) and isinstance(after,list) and path in {"$.nodes","$.artifacts","$.services","$.secrets","$.effects"}:
        left={item["id"]:item for item in before};right={item["id"]:item for item in after}
        for key in sorted(set(left)|set(right)):semantic_diff(left.get(key),right.get(key),path+"[id="+key+"]",output)
        return
    output.append({"path":path,"classification":"structural-incompatible","before":before,"after":after})

def report(before: Dict[str,Any],after: Dict[str,Any])->Dict[str,Any]:
    differences:List[Dict[str,Any]]=[];semantic_diff(normalize(before,"$"),normalize(after,"$"),"$",differences);differences.sort(key=lambda item:item["path"].encode("utf-8"));return {"format_version":DIFF_VERSION,"compatible":not differences,"differences":differences}

def read(path: str) -> bytes: return sys.stdin.buffer.read() if path=="-" else Path(path).read_bytes()
def main(argv: Sequence[str]=()) -> int:
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest="command",required=True)
    for name in ("validate","canonicalize","digest","display"):
        command=sub.add_parser(name);command.add_argument("--input",default="-")
    difference=sub.add_parser("diff");difference.add_argument("--before",required=True);difference.add_argument("--after",required=True)
    args=parser.parse_args(argv or None)
    try:
        if args.command=="diff": before=loads(read(args.before));after=loads(read(args.after));validate(before);validate(after);print(json.dumps(report(before,after),ensure_ascii=False,sort_keys=True,indent=2));return 0
        document=loads(read(args.input));validate(document);encoded=canonical(document)
        if args.command=="validate": print("valid")
        elif args.command=="canonicalize": sys.stdout.buffer.write(encoded)
        elif args.command=="digest": print(digest(encoded))
        else: print(json.dumps({"fixture_id":document["fixture_id"],"fixture_version":document["fixture_version"],"nodes":[item["id"] for item in normalize(document,"$")["nodes"]],"artifacts":[item["id"] for item in normalize(document,"$")["artifacts"]],"digest":digest(encoded)},ensure_ascii=False,sort_keys=True,indent=2))
        return 0
    except (OSError,PlanError) as error: print("e02-reader:",error,file=sys.stderr);return 1
if __name__=="__main__":raise SystemExit(main())
