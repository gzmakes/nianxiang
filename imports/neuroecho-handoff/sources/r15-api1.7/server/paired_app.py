"""TLS-only, default-deny ASGI entrance; no listener or database lifespan here."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs

from starlette.responses import JSONResponse

from . import api_contract, paired_access

MAX_REQUEST_BYTES = 3 * 1024 * 1024
# A 4 MiB image expands to ~5.34 MiB in base64; preserve the smaller limit for all other routes.
MAX_CHAT_REQUEST_BYTES = 6 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
ID = r'[A-Za-z0-9_.:-]{1,128}'
# Modes: no SID, body SID, query SID, path SID, memory ownership, followup ownership.
ROUTES = [
    ('GET',rf'/api/session/({ID})/auto-memory','path'), ('PUT',rf'/api/session/({ID})/auto-memory','path'),
    ('GET',r'/api/conversation','none'), ('GET',r'/api/conversation/changes','none'), ('GET',rf'/api/session/({ID})','path'),
    ('POST',r'/api/chat','body'), ('GET',rf'/api/chat/turn/{ID}','query'),
    ('POST',rf'/api/chat/turn/{ID}/cancel','body'), ('POST',rf'/api/session/({ID})/delivery/stop','path'),
    ('GET',r'/api/memory','query'), ('POST',r'/api/memory','body'), ('POST',r'/api/memory/proposal','body'),
    ('GET',rf'/api/memory/({ID})/history','memory'), ('PATCH',rf'/api/memory/({ID})','memory'), ('DELETE',rf'/api/memory/({ID})','memory'),
    ('GET',r'/api/moods','query'), ('PUT',r'/api/moods/[0-9]{4}-[0-9]{2}-[0-9]{2}','body'), ('DELETE',r'/api/moods/[0-9]{4}-[0-9]{2}-[0-9]{2}','query'),
    ('POST',r'/api/mood-suggestions','body'), ('POST',r'/api/mood-operations','body'),
    ('GET',rf'/api/mood-operations/{ID}','query'), ('POST',rf'/api/mood-operations/{ID}/cancel','body'),
    ('POST',r'/api/local-files/preview-document','none'), ('POST',r'/api/local-files/confirm','body'),
    ('POST',r'/api/source/revoke','body'), ('GET',r'/api/followups','query'), ('POST',r'/api/followups','body'),
    ('POST',rf'/api/followups/({ID})/transition','followup'), ('PATCH',rf'/api/followups/({ID})','followup'),
    ('GET',r'/api/companion-boundary','query'), ('PUT',r'/api/companion-boundary','body'),
]


def error(status, code):
    return JSONResponse({'detail':code,'error_code':code},status_code=status,
                        headers={'Cache-Control':'no-store',**({'WWW-Authenticate':'Bearer'} if status==401 else {})})


def remote_capabilities():
    # No calls into source probes, model settings, CLI or OS adapters.
    from . import core
    out = api_contract.capabilities(chat_budget=core.CHAT_BUDGET,budget_window_minutes=core.CHAT_BUDGET_WINDOW_MINUTES)
    out['deployment_mode'] = 'paired_single_owner'
    out['request_context'] = 'paired_device'
    out['scope'] = 'personal_core'; out['local_actions_allowed'] = False
    out['features'].update(remote_user_authentication=True,source_cli_read=False,owner_management=False,paired_device_management=False,
        source_content_upload=True,source_preview_confirmation=True,action_preview_confirmation=False,
        service_apple_calendar_reminders=False,voice_clip_from_assistant_message=False,
        bounded_followup_contact=False,unified_contact_claim=False)
    out['limitations'].append('Paired devices cannot invoke owner management, CLI, hardware, model settings, system actions or background contact delivery.')
    out['platform_status'].update(apple_calendar='owner_local_only',apple_reminders='owner_local_only',voice_clip='owner_local_only')
    return out


def safe_sources():
    return {'sources':[{'id':'local_files','name':'手机选择的文件','status':'ready','available':True,
                        'icon':'⌂','blurb':'只上传本人选择并确认的内容','hint':'不会读取电脑目录或调用电脑CLI',
                        'kind':'可连接','reads':['仅你选择并确认的内容'],'mode':'real',
                        'description':'只上传你明确选择并预览确认的内容；不能读取电脑路径或调用电脑CLI。',
                        'capability':'content_upload','local_actions_allowed':False}]}


def _json_object(raw):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out: raise ValueError('duplicate key')
            out[key]=value
        return out
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
    if not isinstance(value,dict): raise ValueError('object required')
    return value


class PairedApp:
    def __init__(self, app, database, *, allowed_origins):
        self.app=app; self.database=database; self.allowed_origins=frozenset(allowed_origins)

    async def __call__(self, scope, receive, send):
        if scope['type']!='http':
            if scope['type']=='websocket':await send({'type':'websocket.close','code':1008})
            if scope['type']=='lifespan':
                while True:
                    message=await receive()
                    if message['type']=='lifespan.startup':await send({'type':'lifespan.startup.complete'})
                    elif message['type']=='lifespan.shutdown':
                        await send({'type':'lifespan.shutdown.complete'});break
            return
        headers={key.decode('latin1').lower():value.decode('latin1') for key,value in scope.get('headers',[])}
        async def reject(status,code):await error(status,code)(scope,receive,send)
        if scope.get('scheme')!='https':return await reject(400,'paired_https_required')
        if any(sum(k.lower()==name for k,_ in scope.get('headers',[]))>1 for name in (b'host',b'origin',b'x-echo-service-instance')):
            return await reject(403,'paired_operation_forbidden')
        host=headers.get('host','');origin='https://'+host
        if (origin not in self.allowed_origins or headers.get('origin',origin)!=origin
                or headers.get('sec-fetch-site','').lower()=='cross-site'
                or any(k=='forwarded' or k.startswith('x-forwarded-') for k in headers)):
            return await reject(403,'paired_operation_forbidden')
        if sum(k.lower()==b'authorization' for k,_ in scope.get('headers',[]))!=1:
            return await reject(401,'paired_authentication_required')
        principal=paired_access.authenticate(self.database(),headers.get('authorization'))
        if principal is None:return await reject(401,'paired_authentication_required')
        path=scope.get('path','');rawpath=scope.get('raw_path',path.encode())
        if b'%' in rawpath or '\\' in path or '//' in path or any(p in ('.','..') for p in path.split('/')):
            return await reject(403,'paired_operation_forbidden')
        expected=headers.get('x-echo-service-instance')
        if expected is not None and expected!=principal.service_instance_id:
            return await reject(409,'service_instance_mismatch')
        verify=scope['method']=='GET' and path=='/api/paired-device'
        query=parse_qs(scope.get('query_string',b'').decode('ascii',errors='replace'),keep_blank_values=True)
        if any(k.lower() in ('token','authorization','access_token') for k in query):
            return await reject(403,'paired_operation_forbidden')
        if any(v!=[principal.conversation_id] for k,v in query.items() if k in ('sid','session_id')):
            return await reject(403,'paired_operation_forbidden')
        if not verify and expected is None:return await reject(428,'service_instance_required')
        if verify:
            value=paired_access.public_principal(principal)
            if value is None:return await reject(401,'paired_authentication_required')
            return await JSONResponse(value,headers={'Cache-Control':'no-store'})(scope,receive,send)
        if scope['method']=='GET' and path in ('/api/capabilities','/api/onboarding/sources'):
            value=remote_capabilities() if path.endswith('capabilities') else safe_sources()
            if not paired_access.active(principal):return await reject(401,'paired_authentication_required')
            return await JSONResponse(value,headers={'Cache-Control':'no-store'})(scope,receive,send)
        selected=None
        for method,pattern,mode in ROUTES:
            match=re.fullmatch(pattern,path)
            if method==scope['method'] and match:
                selected=(mode,match);break
        if selected is None:return await reject(403,'paired_operation_forbidden')
        request_limit = MAX_CHAT_REQUEST_BYTES if path == '/api/chat' and scope['method'] == 'POST' else MAX_REQUEST_BYTES
        try:
            if int(headers.get('content-length','0'))>request_limit:return await reject(413,'paired_request_too_large')
        except ValueError:return await reject(400,'paired_invalid_request')
        raw=bytearray()
        while True:
            message=await receive()
            if message['type']=='http.disconnect':return
            raw.extend(message.get('body',b''))
            if len(raw)>request_limit:return await reject(413,'paired_request_too_large')
            if not message.get('more_body',False):break
        try:body=_json_object(raw) if raw else {}
        except (ValueError,UnicodeError,RecursionError):return await reject(400,'paired_invalid_request')
        sid=principal.conversation_id
        # Reject every provided SID, even an otherwise ignored extra parameter.
        if any(v!=[sid] for k,v in query.items() if k in ('sid','session_id')) or any(v!=sid for k,v in body.items() if k in ('sid','session_id')):
            return await reject(403,'paired_operation_forbidden')
        mode,match=selected
        if ((mode=='body' and body.get('session_id')!=sid) or (mode=='query' and query.get('session_id')!=[sid])
                or (mode=='path' and match.group(1)!=sid)):
            return await reject(403,'paired_operation_forbidden')
        if mode=='memory' and not paired_access.resource_belongs(principal,'memories',match.group(1)):
            return await reject(403,'paired_operation_forbidden')
        if mode=='followup' and (body.get('session_id')!=sid or not paired_access.resource_belongs(principal,'followups',match.group(1))):
            return await reject(403,'paired_operation_forbidden')
        if path=='/api/chat' and not body.get('request_id'):return await reject(400,'paired_invalid_request')
        if not paired_access.active(principal):return await reject(401,'paired_authentication_required')
        inner=dict(scope);paired_access.stamp_scope(inner,principal)
        delivered=False
        async def replay():
            nonlocal delivered
            if not delivered:delivered=True;return {'type':'http.request','body':bytes(raw),'more_body':False}
            return await receive()
        messages=[];size=0
        async def buffer(message):
            nonlocal size
            size+=len(message.get('body',b''))
            if size>MAX_RESPONSE_BYTES:raise ValueError('paired response too large')
            messages.append(message)
        try:await self.app(inner,replay,buffer)
        except Exception:
            if not paired_access.active(principal):return await reject(401,'paired_authentication_required')
            return await reject(503,'paired_operation_unavailable')
        # Buffering prevents a revoked credential receiving a late model result.
        # This is not rollback of work committed before the final check.
        if not paired_access.active(principal):return await reject(401,'paired_authentication_required')
        for message in messages:
            if message['type']=='http.response.start':
                message={**message,'headers':[(k,v) for k,v in message.get('headers',[]) if k.lower()!=b'cache-control']+[(b'cache-control',b'no-store')]}
            await send(message)


def create_remote_app(app, database, *, allowed_origins):
    return PairedApp(app,database,allowed_origins=allowed_origins)
