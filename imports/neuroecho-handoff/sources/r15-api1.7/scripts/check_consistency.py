#!/usr/bin/env python3
"""Dependency-free baseline checks, not a claim of full client parity or native build."""
from pathlib import Path
import argparse, ast, json, re, sys
from generate_shared import outputs
from sync_clients import runtime_adoption_issues, runtime_copy_issues, surfaces
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--require-response-models',action='store_true',help='Require typed successful responses for core operations.')
p.add_argument('--require-runtime-adoption',action='store_true',help='Require exact generated copies and real HTML/Swift/Kotlin adoption in every present client.')
a=p.parse_args();checks=0

def check(value,message):
    global checks
    if not value:raise SystemExit('FAIL: '+message)
    checks+=1

schema=json.loads((ROOT/'shared/api/openapi.json').read_text())
methods={'get','post','patch','put','delete','head','options'}
declared=set()
for node in ast.walk(ast.parse((ROOT/'server/main.py').read_text())):
    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
        for dec in node.decorator_list:
            if isinstance(dec,ast.Call) and isinstance(dec.func,ast.Attribute) and isinstance(dec.func.value,ast.Name) and dec.func.value.id=='app' and dec.func.attr in methods and dec.args and isinstance(dec.args[0],ast.Constant):
                declared.add((dec.func.attr,dec.args[0].value))
exported={(method,path) for path,item in schema['paths'].items() for method in item if method in methods}
check(declared==exported,'declared routes differ from the exported contract; regenerate and review client impact')
critical=[('get','/api/conversation/changes'),('get','/api/conversation'),('post','/api/chat'),('get','/api/chat/turn/{request_id}'),('post','/api/local-files/confirm'),('post','/api/lark/preview'),('post','/api/lark/attach'),('patch','/api/memory/{mid}'),('post','/api/source/revoke'),('post','/api/action/{aid}/commit')]
critical += [('get','/api/companion-boundary'),('put','/api/companion-boundary'),('post','/api/followups/{followup_id}/contact/claim'),('post','/api/followup-contacts/{claim_id}/recheck'),('post','/api/followup-contacts/{claim_id}/finish')]
check(set(critical)<=exported,'critical endpoints are missing')
behavior=json.loads((ROOT/'shared/product/behavior.json').read_text())
models=schema['components']['schemas']
check(models['ChatIn']['properties']['text']['maxLength']==4000,'chat limit changed')
check(models['FollowupCreateIn']['properties']['allow_contact'].get('default') is False,'proactive contact must default to no consent')
check(models['FollowupCreateIn']['properties']['contact_window_minutes'].get('minimum')==5 and models['FollowupCreateIn']['properties']['contact_window_minutes'].get('maximum')==180,'bounded followup contact window changed')
check(models['LocalFileIn']['properties']['text']['maxLength']==behavior['files']['preview_code_points'],'file prefix contract changed')
check(models['LocalFilesConfirmIn']['properties']['files']['maxItems']==behavior['files']['max_batch'],'file batch contract changed')
check(behavior['conversation']['display_session_id'] is False and behavior['conversation']['cloud_sync_implemented'] is False,'do not confuse canonical local conversation with cloud sync')
check(behavior['actions']['native_real'] is False and behavior['actions']['success_state']=='committed','native action safety contract changed')
design=json.loads((ROOT/'shared/design/tokens.json').read_text());spec=(ROOT/'design.md').read_text().upper()
check(all(value.upper() in spec for value in design['colors'].values() if value.startswith('#')),'design colors differ from design.md')
for name,content in outputs().items():check((ROOT/'shared/generated'/name).read_text()==content,'generated reference drift: '+name)
missing=[]
for method,path in critical:
    success=[response for code,response in schema['paths'][path][method].get('responses',{}).items() if str(code).startswith('2')]
    if not any(item.get('schema') for response in success for item in response.get('content',{}).values()):missing.append(method.upper()+' '+path)
if a.require_response_models and missing:raise SystemExit('RESPONSE_CONTRACT_NOT_READY: '+', '.join(missing))
runtime_issues=runtime_copy_issues(ROOT)+runtime_adoption_issues(ROOT)
if a.require_runtime_adoption and runtime_issues:raise SystemExit('RUNTIME_ADOPTION_NOT_READY: '+'; '.join(runtime_issues))
if a.require_runtime_adoption:checks+=1
print(f'PASS: {checks} shared baseline checks; routes, declared limits, and generated references match.')
if missing:print('OPEN GATE: successful response models not declared for '+str(len(missing))+' critical operations. SDK generation and full client parity are NOT validated.')
if runtime_issues:print('OPEN GATE: runtime adoption: '+'; '.join(runtime_issues))
else:print('RUNTIME_ADOPTION: '+', '.join(surfaces(ROOT))+' imports generated resources and first shared navigation/default bindings; this is a static gate.')
print('OPEN GATE: remaining handwritten copy/layouts and native builds/device/visual acceptance are separate; shared resources do not automatically adapt all interactions.')
