"""念响 · PC Web MVP（FastAPI 控制层）。

运行：
    .venv/bin/python -m uvicorn server.main:app --reload --port 18787
"""
from __future__ import annotations

import os
import ipaddress
import secrets
import json
import sqlite3
import math
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Literal

from fastapi import FastAPI, Header, HTTPException, Path as ApiPath, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import apple_source, connectors, core, device_bridge, faults, gmail_source, insight_ai, lark, lark_auth, lark_search_auth, local_source, mindlink, model, model_settings, notion_source, plugin_bridge, real_sources, system_source
from .core import BudgetExceeded
from . import chat_turns, followups, moods, mood_operations, proactive_policy, companion_boundary, voice_clip, local_documents
from . import notion_cli_source, git_source, gmail_cli_source, connector_auth
from .runtime_lock import DatabaseLease
from . import api_contract as contract
from . import paired_access, conversation_changes

BASE = Path(__file__).resolve().parent
WEB = BASE.parent / "web"
DIST = BASE.parent / "dist"


def _latest(prefix: str) -> Path | None:
    files = sorted(DIST.glob(prefix), key=lambda p: p.stat().st_mtime, reverse=True) if DIST.exists() else []
    return files[0] if files else None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # uvicorn imports this module rather than running __main__; migrate before
    # serving existing sessions or bookmarks, including on a fresh install.
    with DatabaseLease(core.DB_PATH):
        core.init_db()
        paired_access.initialize(core.DB_PATH)
        _turn_store()
        core.conversation_id()  # Prepare identity before the read-only update feed is served.
        yield


app = FastAPI(title="念响 · 具身个人伙伴 PC MVP", version="0.1.0", lifespan=lifespan,
              responses=contract.ERROR_RESPONSES)


@app.exception_handler(StarletteHTTPException)
async def contract_http_error(request: Request, error: StarletteHTTPException):
    # Keep legacy detail and response headers. New clients use the stable code;
    # they must not parse localized text to decide whether to retry a write.
    return JSONResponse({"detail": error.detail,
                         "error_code": getattr(error, "error_code", contract.ERROR_CODES.get(error.status_code, "http_error")),
                        **getattr(error, "context", {})}, status_code=error.status_code,
                        headers={**(error.headers or {}),**({'Cache-Control':'no-store'} if request.url.path.startswith('/api/paired-device') or request.url.path=='/api/conversation/changes' else {})})


@app.exception_handler(RequestValidationError)
async def contract_validation_error(request: Request, error: RequestValidationError):
    if request.url.path.startswith('/api/paired-device'):
        return JSONResponse({'detail':'Invalid device request.','error_code':'validation_error'},status_code=422,
                            headers={'Cache-Control':'no-store'})
    try:
        response = await request_validation_exception_handler(request, error)
    except ValueError:
        # Pydantic rejects non-finite coordinates, but reflecting that input
        # in JSON would itself raise and turn the intended 422 into a 500.
        detail = jsonable_encoder([{key: value for key, value in item.items() if key != 'input'}
                                   for item in error.errors()], custom_encoder={
            float: lambda value: value if math.isfinite(value) else None})
        return JSONResponse({'detail': detail, 'error_code': 'validation_error'}, status_code=422)
    return JSONResponse({**json.loads(response.body), "error_code": "validation_error"}, status_code=422)


@app.exception_handler(core.MemoryVersionConflict)
async def memory_version_conflict(request: Request, error: core.MemoryVersionConflict):
    return JSONResponse({"detail": str(error), "error_code": "memory_version_conflict",
                         "expected_version": error.expected_version, "current_version": error.current_version},
                        status_code=409)


@app.middleware("http")
async def local_origin_guard(request: Request, call_next):
    """Protect the local-only service from browser cross-site requests.

    The server must still bind to loopback. Local native clients without Origin
    or Fetch Metadata remain allowed; this is not authentication between local
    processes. TestClient's synthetic host is only accepted for its own peer.
    """
    principal=paired_access.principal_from_scope(request.scope)
    if principal is not None:
        if str(principal.database)!=str(core.DB_PATH) or not paired_access.active(principal):
            return JSONResponse({'detail':'paired_authentication_required','error_code':'paired_authentication_required'},
                                status_code=401,headers={'Cache-Control':'no-store'})
        return await call_next(request)
    peer = request.client.host if request.client else ""
    try:
        local_peer = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        local_peer = False
    is_test = peer == "testclient"
    try:
        hostname = request.url.hostname
        host = request.headers.get("host", "")
    except ValueError:
        hostname, host = "", ""
    allowed_host = hostname in ("localhost", "127.0.0.1", "::1") or (is_test and hostname == "testserver")
    expected_origin = f"{request.url.scheme}://{host}"
    origin = request.headers.get("origin")
    fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if (not (local_peer or is_test) or not allowed_host or "@" in host
            or (origin is not None and origin != expected_origin)
            or fetch_site == "cross-site"
            or (fetch_site == "same-site" and request.method not in ("GET", "HEAD", "OPTIONS"))):
        return JSONResponse({"detail": "local same-origin requests only", "error_code": "local_origin_required"}, status_code=403,
                            headers={"Cache-Control": "no-store"})
    return await call_next(request)


class SessionIn(BaseModel):
    mode: str = Field(default="empty", pattern="^(sample|paste|empty)$")
    text: str = ""


class ChatIn(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=4000)
    memory_proposals: StrictBool = False
    time_zone: str | None = Field(default=None,min_length=1,max_length=128)
    request_id: str | None = Field(default=None, min_length=8, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$")


class VoiceClipIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)


class DeliveryStopIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Optional only for old clients: a missing identifier is a non-mutating no-op.
    message_id: str | None = Field(default=None, min_length=1, max_length=128)


class ChatCancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str


class MoodSaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)
    x: float = Field(ge=-1, le=1, strict=True, allow_inf_nan=False)
    y: float = Field(ge=-1, le=1, strict=True, allow_inf_nan=False)
    note: str = Field(default='', max_length=1000)
    confirmed: StrictBool
    expected_updated_at: str | None = Field(max_length=64)


class MoodSuggestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=1000)
    consent: StrictBool


class MoodOperationIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=8, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]+$')
    operation_json: str = Field(min_length=1, max_length=mood_operations.MAX_OPERATION_BYTES)
    confirmed: StrictBool


class MoodOperationCancelIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str = Field(min_length=1, max_length=128)
    operation_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    kind: Literal['save', 'delete']
    confirmed: StrictBool


class FollowupCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=1000)
    due_at: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$")
    confirmed: StrictBool
    repeat_rule: str = Field(default="once", pattern="^(once|daily)$")
    time_zone: str = Field(default="UTC", min_length=1, max_length=128)
    quiet_start: str | None = None
    quiet_end: str | None = None
    allow_contact: StrictBool = False
    contact_window_minutes: int = Field(default=30,ge=5,le=180,strict=True)
    contact_topic: str | None = Field(default=None,min_length=1,max_length=1000)


class FollowupChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)
    status: str = Field(pattern="^(done|cancelled|paused|resumed)$")
    occurrence_at: str | None = Field(default=None, max_length=64)


class NotificationSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0, strict=True)
    enabled: StrictBool
    time_zone: str = Field(min_length=1, max_length=128)
    quiet_start: str = Field(min_length=5, max_length=5)
    quiet_end: str = Field(min_length=5, max_length=5)
    cooldown_minutes: int = Field(ge=60, le=1440, strict=True)
    daily_limit: int = Field(ge=1, le=3, strict=True)
    pause_until: str | None = Field(default=None, max_length=64)


class NotificationClaimIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)
    occurrence_at: str = Field(min_length=1, max_length=64)


class NotificationRecheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)


class NotificationFinishIn(NotificationRecheckIn):
    state: Literal['submitted', 'failed']


class NotificationSettingsResponse(BaseModel):
    enabled: bool
    time_zone: str
    quiet_start: str
    quiet_end: str
    cooldown_minutes: int
    daily_limit: int
    pause_until: str | None
    configured: bool
    revision: int


class NotificationClaimResponse(BaseModel):
    claimed: bool
    reason: str | None
    claim_id: str | None


class NotificationRecheckResponse(BaseModel):
    allowed: bool
    reason: str | None


class NotificationFinishResponse(BaseModel):
    state: str


class BoundaryIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str = Field(min_length=1,max_length=128)
    expected_revision: int = Field(ge=0,strict=True)
    confirmed: StrictBool
    mode: Literal['active','paused','until']
    until: str | None = Field(default=None,max_length=64)
    time_zone: str = Field(min_length=1,max_length=128)


class BoundaryResponse(contract.OpenResponse):
    revision: int
    mode: Literal['active','paused','until']
    until: str | None
    time_zone: str
    suppression_revision: int


class ContactClaimIn(NotificationClaimIn):
    channel: Literal['in_app','system']


class ContactClaimResponse(contract.OpenResponse):
    claimed: bool
    reason: str | None
    claim_id: str | None
    expires_at: str | None
    channel: Literal['in_app','system']
    followup_id: str
    occurrence_at: str


class ContactRecheckResponse(contract.OpenResponse):
    allowed: bool
    reason: str | None
    claim_id: str
    followup_id: str | None
    occurrence_at: str | None
    channel: str | None
    expires_at: str | None


class ContactFinishResponse(contract.OpenResponse):
    state: Literal['submitted','failed']
    claim_id: str
    channel: str



class MemoryProposalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    message_id: str
    confirm: StrictBool = False


class MemoryIn(BaseModel):
    session_id: str
    kind: str = Field(pattern="^(fact|inference|question)$")
    text: str = Field(min_length=1, max_length=2000)
    source: str = "用户手动添加"


class MemoryPatch(BaseModel):
    text: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[str] = Field(default=None, pattern="^(candidate|confirmed)$")
    expected_version: Optional[int] = Field(default=None, ge=1, strict=True,
                                           description="Optional compare-and-set version; stale edits return 409 without changing memory or history.")


class LarkIn(BaseModel):
    url: str
    preview_id: str = ""


class LarkSearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(min_length=1, max_length=200)


class LarkAttachIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    preview_id: str = Field(min_length=1, max_length=256)


class LocalFileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=4000)


class LocalFilesConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str | None = None
    files: list[LocalFileIn] = Field(min_length=1, max_length=3)


class LocalDocumentPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    data: str = Field(min_length=1, max_length=((local_documents.MAX_DOCUMENT_BYTES + 2) // 3) * 4)



class LocalDocumentPreviewResponse(contract.OpenResponse):
    name: str
    text: str
    truncated: bool
    length: int
    extracted_length: int
    notice: str


class ScenarioIn(BaseModel):
    scenario: str


class ConnectorIn(BaseModel):
    connector_id: str
    scenario: str | None = None


class ModelSettingsIn(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: float = 8


class FaultIn(BaseModel):
    kind: str
    enabled: bool = True


class ButtonIn(BaseModel):
    session_id: str = "demo"


class DisplayIn(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=200)
    color: str = "amber"


class MindLinkConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent: StrictBool


class MindLinkEmptyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CarryoverIn(BaseModel):
    session_id: str
    ids: list[str]
    expected_versions: dict[str, int] | None = None
    expected_target: dict[str, int] | None = None


class SourceIn(BaseModel):
    source_id: str
    preview_id: str = ""
    session_id: str | None = None
    path: str | None = Field(default=None, max_length=4096)


class GmailIn(BaseModel):
    address: str = ""
    password: str = ""
    method: str = Field(default="imap", pattern="^(imap|cli)$")


class NotionIn(BaseModel):
    token: str = ""
    url: str
    method: str = Field(default="token", pattern="^(token|cli)$")


class PreviewStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str = Field(min_length=1, max_length=256)
    session_id: str | None = None


class SessionRenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class ActionCommitIn(BaseModel):
    real: bool = False


class ActionIn(BaseModel):
    session_id: str
    kind: str
    title: str = Field(min_length=1, max_length=200)
    detail: str = ""
    when: str = ""


class SourceRevokeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    source_id: str | None = Field(default=None, min_length=1, max_length=128)


class BookmarkIn(BaseModel):
    session_id: str
    note: str = Field(min_length=1, max_length=2000)
    choice: str = ""
    next_step: str = ""
    source_memory_id: str = ""
    source_version: int = 0
    source_label: str = ""
    source_quote: str = ""
    source_attachment_id: str = Field(default="", max_length=128)


@app.get("/api/health")
def health():
    return {"ok": True, "product": "xinji-echo", "mode": "fastapi", "synthetic": True, "version": "0.1.0"}


@app.get("/api/config")
def config():
    return {"model": model.status(), "synthetic": True, "budget": core.CHAT_BUDGET,
            "budget_window_minutes": core.CHAT_BUDGET_WINDOW_MINUTES}


@app.post("/api/voice/clip", response_class=Response, responses={200: {"content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}}})
def make_voice_clip(body: VoiceClipIn):
    """Synthesize only a fully delivered assistant message on explicit request."""
    def current_message():
        if core.get_session(body.session_id) is None:
            return None
        return next((m for m in core.get_messages(body.session_id)
                     if m['id'] == body.message_id and m['role'] == 'assistant'), None)

    if core.get_session(body.session_id) is None:
        raise HTTPException(404, '找不到这条回复。')
    context_before = core._model_context_stamp(body.session_id)
    message = current_message()
    if message is None:
        raise HTTPException(404, '找不到这条回复。')
    if message.get('delivery_pending'):
        raise HTTPException(409, '请等这条回复发送完成。')
    try:
        audio = voice_clip.synthesize(message['text'])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except voice_clip.VoiceUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    # Recheck after synthesis so a deletion, truncation or source revocation
    # during the slow subprocess does not return a stale audio response.
    after = current_message()
    if (after is None or after.get('delivery_pending') or after['text'] != message['text']
            or core._model_context_stamp(body.session_id) != context_before):
        raise HTTPException(409, '这条回复已变化，请重新选择。')
    return Response(audio, media_type='audio/wav', headers={'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff'})


@app.get("/api/capabilities", response_model=contract.CapabilityResponse, response_model_exclude_unset=True)
def capabilities():
    return contract.capabilities(chat_budget=core.CHAT_BUDGET, budget_window_minutes=core.CHAT_BUDGET_WINDOW_MINUTES)


@app.get("/api/settings/model")
def get_model_settings():
    return model_settings.redacted()


class PairedDeviceDTO(BaseModel):
    id: str
    label: str
    created_at: str
    expires_at: str
    revoked_at: str | None


class PairedDeviceCheck(BaseModel):
    service_instance_id: str
    conversation_id: str
    scope: Literal['personal_core'] = 'personal_core'
    local_actions_allowed: Literal[False] = False
    device: PairedDeviceDTO


class PairedDeviceCreated(PairedDeviceCheck):
    token: str


class PairedDevicesList(BaseModel):
    service_instance_id: str
    conversation_id: str
    scope: Literal['personal_core'] = 'personal_core'
    local_actions_allowed: Literal[False] = False
    devices: list[PairedDeviceDTO]


class PairedCreateIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    label: str = Field(min_length=1,max_length=80)
    expires_in_seconds: int = Field(default=86400,ge=300,le=2592000,strict=True)
    confirmed: StrictBool


class PairedRevokeIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmed: StrictBool


class PairedRevokeResponse(BaseModel):
    service_instance_id: str
    device_id: str
    revoked: Literal[True]
    in_flight_may_have_committed: Literal[True]


@app.get('/api/paired-device',response_model=PairedDeviceCheck)
def paired_device_check(request: Request,response: Response):
    response.headers['Cache-Control']='no-store'
    principal=paired_access.principal_from_scope(request.scope)
    if principal is None:raise contract.ContractError(403,'paired_operation_forbidden','Use the paired TLS entrance.')
    value=paired_access.public_principal(principal)
    if value is None:raise contract.ContractError(401,'paired_authentication_required','Credential unavailable.')
    return value


@app.post('/api/paired-devices',response_model=PairedDeviceCreated,status_code=201)
def create_paired_device(body: PairedCreateIn,response: Response):
    response.headers['Cache-Control']='no-store'
    if body.confirmed is not True:raise contract.ContractError(400,'confirmation_required','Explicit approval required.')
    try:return paired_access.create(core.DB_PATH,core.conversation_id(),body.label,body.expires_in_seconds)
    except ValueError as error:raise contract.ContractError(400,'invalid_request',str(error)) from error


@app.get('/api/paired-devices',response_model=PairedDevicesList)
def list_paired_devices(response: Response):
    response.headers['Cache-Control']='no-store'
    return paired_access.list_devices(core.DB_PATH,core.conversation_id())


@app.post('/api/paired-devices/{device_id}/revoke',response_model=PairedRevokeResponse)
def revoke_paired_device(device_id: str,body: PairedRevokeIn,response: Response):
    response.headers['Cache-Control']='no-store'
    if body.confirmed is not True:raise contract.ContractError(400,'confirmation_required','Explicit approval required.')
    value=paired_access.revoke(core.DB_PATH,device_id)
    if value is None:raise HTTPException(404,'Device not found.')
    return value


@app.get("/api/onboarding/sources", response_model=contract.SourceCatalogResponse, response_model_exclude_unset=True)
def onboarding_sources(force: bool = False):
    return {"sources": real_sources.sources(force=force)}


def _enrich(read: dict) -> dict:
    try:
        return insight_ai.enrich(read)
    except Exception:
        return read


# Short-lived, single-use previews ensure that starting a session uses exactly
# the material the user reviewed, rather than silently reading the source again.
_source_previews: dict[str, tuple[float, str, dict]] = {}
_preview_lock = threading.Lock()
_PREVIEW_TTL = 600
_preview_timer: threading.Timer | None = None


def _schedule_preview_expiry_locked() -> None:
    """Keep one daemon timer for the earliest remaining preview; lock required."""
    global _preview_timer
    if _preview_timer is not None or not _source_previews:
        return
    earliest = min(created for created, _, _ in _source_previews.values())
    delay = max(0.01, earliest + _PREVIEW_TTL - time.monotonic())
    _preview_timer = threading.Timer(delay, _expire_source_previews)
    _preview_timer.daemon = True
    _preview_timer.start()


def _expire_source_previews() -> None:
    global _preview_timer
    with _preview_lock:
        _preview_timer = None
        now = time.monotonic()
        for key, (created, _, _) in list(_source_previews.items()):
            if now - created >= _PREVIEW_TTL:
                _source_previews.pop(key, None)
        _schedule_preview_expiry_locked()


def _save_preview(source: str, read: dict) -> str:
    preview_id = secrets.token_urlsafe(24)
    with _preview_lock:
        now = time.monotonic()
        for key, (created, _, _) in list(_source_previews.items()):
            if now - created > _PREVIEW_TTL:
                _source_previews.pop(key, None)
        if len(_source_previews) >= 20:
            _source_previews.pop(next(iter(_source_previews)))
        _source_previews[preview_id] = (now, source, read)
        _schedule_preview_expiry_locked()
    return preview_id


def _consume_preview(source: str, preview_id: str) -> dict:
    with _preview_lock:
        preview = _source_previews.pop(preview_id, None)
    if not preview or preview[1] != source or time.monotonic() - preview[0] > _PREVIEW_TTL:
        raise contract.ContractError(400, "source_preview_expired", "读取预览已失效，请重新选择并确认来源")
    return preview[2]


@app.post("/api/onboarding/real/read", response_model=contract.SourceReadResponse, response_model_exclude_unset=True)
def onboarding_real_read(body: SourceIn):
    source = git_source.read(path=body.path) if body.source_id == "git" and body.path is not None else real_sources.read(body.source_id)
    read = _enrich(source)
    if read.get("ok"):
        return {**read, "preview_id": _save_preview(body.source_id, read)}
    return {**read, "error_code": read.get("error_code", "source_unavailable")}


def _check_attachment_target(sid: str | None) -> None:
    if not sid:
        return
    sess = core.get_session(sid)
    if not sess:
        raise HTTPException(404, "session not found")
    if len(core.list_sources(sid)) >= 8:
        raise contract.ContractError(409, "source_limit", "当前对话已有 8 份来源。可先移除不再需要的一份，再接入新资料；原消息会保留。")


def _attach_reviewed_read(sid: str, read: dict, *, source_label: str | None = None,
                          source_text: str | None = None) -> dict:
    """Keep the user's conversation and manual memories when connecting a source."""
    c = read["connector"]
    try:
        core.attach_source_to_empty_session(
            sid, source_label or f"{c['name']} · 已连接",
            source_text if source_text is not None else "\n".join(read["understanding"]["facts"]),
            read["understanding"], read.get("items") or [], read.get("insights") or [],
            read.get("starters") or [], connector_id=c["id"])
    except LookupError:
        raise HTTPException(404, "session not found")
    except core.SourceConflict as e:
        raise contract.ContractError(409, "source_conflict", str(e))
    return {"session": core.get_session(sid), "messages": core.get_messages(sid),
            "memories": core.list_memories(sid), "context": core.get_session_context(sid),
            "bookmark": core.latest_bookmark(sid), "insights": read.get("insights") or [], "connector": c}


def _start_reviewed_read(read: dict, *, greeting: str | None = None,
                         source_label: str | None = None, source_text: str | None = None) -> dict:
    """New and existing conversations share the same source ownership contract."""
    first_item = (read.get("items") or [{}])[0]
    title = str(read.get("title") or first_item.get("title") or read["connector"]["name"])[:90]
    data = core.create_session("empty", greeting=greeting or read.get("greeting")
                               or f"我看到了你选择的「{title}」。你想先聊哪一部分？")
    sid = data["session"]["id"]
    try:
        result = _attach_reviewed_read(sid, read, source_label=source_label, source_text=source_text)
    except Exception:
        core.delete_session(sid)
        raise
    result["understanding"] = read["understanding"]
    return result


@app.post("/api/onboarding/real/start", response_model=contract.ConversationResponse, response_model_exclude_unset=True)
def onboarding_real_start(body: SourceIn):
    _check_attachment_target(body.session_id)
    with _preview_lock:
        preview = _source_previews.pop(body.preview_id, None)
    if not preview or preview[1] != body.source_id or time.monotonic() - preview[0] > _PREVIEW_TTL:
        raise contract.ContractError(400, "source_preview_expired", "读取预览已失效，请重新选择并确认来源")
    read = preview[2]
    if body.session_id:
        return _attach_reviewed_read(body.session_id, read)
    data = _start_reviewed_read(read)
    c = read["connector"]
    core.audit(data["session"]["id"], "real.read", f"{len(read['items'])} 条 · {c['id']}", "用户确认读取真实来源")
    return data


@app.post("/api/gmail/preview", response_model=contract.SourceReadResponse, response_model_exclude_unset=True)
def gmail_preview(body: GmailIn):
    out = gmail_cli_source.read() if body.method == "cli" else gmail_source.read(body.address, body.password)
    return {**out, "preview_id": _save_preview("gmail", out)} if out.get("ok") else {**out, "error_code": out.get("error_code", "source_unavailable")}


@app.post("/api/gmail/start", response_model=contract.ConversationResponse, response_model_exclude_unset=True)
def gmail_start(body: PreviewStartIn):
    _check_attachment_target(body.session_id)
    out = _enrich(_consume_preview("gmail", body.preview_id))
    if body.session_id:
        return _attach_reviewed_read(body.session_id, out)
    data = _start_reviewed_read(out)
    core.audit(data["session"]["id"], "gmail.read", f"{len(out['items'])} 封未读", "用户确认读取 Gmail 未读头")
    return data


@app.post("/api/lark/docs")
def lark_docs(body: LarkSearchIn):
    return lark.search_docs(body.q)


@app.post("/api/auth/lark/start")
def auth_lark_start():
    return lark_auth.start()


@app.post("/api/auth/lark/setup")
def auth_lark_setup():
    return lark_auth.setup_keychain()


@app.get("/api/auth/lark/status")
def auth_lark_status():
    return lark_auth.status()


@app.post("/api/auth/lark/search/start")
def auth_lark_search_start():
    return lark_search_auth.start()


@app.get("/api/auth/lark/search/status")
def auth_lark_search_status():
    return lark_search_auth.status()


@app.post("/api/notion/preview", response_model=contract.SourceReadResponse, response_model_exclude_unset=True)
def notion_preview(body: NotionIn):
    out = notion_cli_source.read(body.url) if body.method == "cli" else notion_source.read(body.token, body.url)
    return {**out, "preview_id": _save_preview("notion", out)} if out.get("ok") else {**out, "error_code": out.get("error_code", "source_unavailable")}


@app.post("/api/notion/start", response_model=contract.ConversationResponse, response_model_exclude_unset=True)
def notion_start(body: PreviewStartIn):
    _check_attachment_target(body.session_id)
    out = _enrich(_consume_preview("notion", body.preview_id))
    if body.session_id:
        return _attach_reviewed_read(body.session_id, out)
    data = _start_reviewed_read(out)
    core.audit(data["session"]["id"], "notion.read", f"{len(out['items'])} 条", "用户确认读取 Notion 页面")
    return data


@app.post("/api/settings/model")
def set_model_settings(body: ModelSettingsIn):
    if model_settings.environment_managed():
        raise HTTPException(409, "当前模型由本机启动环境提供。请先停止该服务，在启动环境中更改后重启；本次没有写入配置。")
    if not body.base_url.strip() or not body.model.strip():
        raise HTTPException(400, "base_url 与 model 必填")
    key = body.api_key.strip() or model_settings.load().get("api_key", "")
    out = model_settings.save(body.base_url, key, body.model, body.timeout)
    core.audit(None, "settings.model", f"model={out['model']}", "用户配置模型")
    return out


@app.post("/api/settings/model/test")
def test_model_settings():
    return model.test_connection()


@app.post("/api/settings/model/clear")
def clear_model_settings():
    if model_settings.environment_managed():
        raise HTTPException(409, "当前模型由本机启动环境提供，无法在页面清除。请先停止该服务并调整启动环境；本次没有删除配置。")
    return model_settings.clear()


@app.get("/api/debug/faults")
def get_faults():
    return faults.get_faults()


@app.post("/api/debug/faults")
def set_faults(body: FaultIn):
    try:
        return faults.set_faults(body.kind, body.enabled)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/debug/faults/clear")
def clear_faults():
    return faults.clear()


@app.get("/api/onboarding/catalog")
def onboarding_catalog():
    return connectors.catalog()


@app.post("/api/onboarding/recommend")
def onboarding_recommend(body: ScenarioIn):
    return {"scenario": body.scenario, "items": connectors.recommend(body.scenario)}


def _read_connector(connector_id: str) -> dict:
    if connector_id in ("apple_reminders", "apple_calendar"):
        return apple_source.read_reminders() if connector_id == "apple_reminders" else apple_source.read_calendar()
    if connector_id in ("windows_reminders", "windows_calendar"):
        return system_source.read_reminders() if connector_id == "windows_reminders" else system_source.read_calendar()
    if connector_id == "local_files":
        return local_source.read()
    return connectors.read(connector_id)


@app.post("/api/onboarding/read")
def onboarding_read(body: ConnectorIn):
    return _read_connector(body.connector_id)


@app.post("/api/onboarding/start")
def onboarding_start(body: ConnectorIn):
    read = _read_connector(body.connector_id)
    if not read.get("ok"):
        raise HTTPException(400, read.get("error", "读取失败"))
    c = read["connector"]
    mode_label = "只读" if not read.get("synthetic") else "演示读取"
    data = _start_reviewed_read(read, source_label=f"{c['name']} · {mode_label}",
                                greeting=connectors.greeting(body.connector_id) if read.get("synthetic") else None)
    sid = data["session"]["id"]
    core.audit(sid, "connector.read", f"{len(read['items'])} 条 · {c['id']}",
               "用户确认读取本地文件" if not read.get("synthetic") else "用户确认读取演示数据")
    return data


@app.get("/api/lark/status")
def lark_status():
    return lark.auth_status()


@app.post("/api/lark/preview", response_model=contract.SourceReadResponse, response_model_exclude_unset=True)
def lark_preview(body: LarkIn):
    out = lark.read_doc(body.url)
    if not out.get("ok"):
        return {**out, "error_code": out.get("error_code", "source_unavailable")}
    # Cache exactly the same bounded snapshot that is shown to the user. A
    # confirmation must never attach an unseen suffix from a later fetch.
    out = dict(out)
    original = out["text"]
    out["text"] = original[:lark.MAX_CHARS]
    out["length"] = len(out["text"])
    out["extracted_length"] = max(out.get("extracted_length", len(original)), len(original))
    out["truncated"] = bool(out.get("truncated")) or out["extracted_length"] > out["length"]
    preview_id = _save_preview("lark:" + body.url, out)
    return {k: v for k, v in out.items() if k != "text"} | {"preview": out["text"], "preview_id": preview_id}


@app.post("/api/lark/start", response_model=contract.ConversationResponse, response_model_exclude_unset=True)
def lark_start(body: LarkIn):
    with _preview_lock:
        preview = _source_previews.pop(body.preview_id, None)
    if not preview or preview[1] != "lark:" + body.url or time.monotonic() - preview[0] > _PREVIEW_TTL:
        raise contract.ContractError(400, "source_preview_expired", "文档预览已失效，请重新选择并确认")
    out = preview[2]
    pseudo = {
        "ok": True,
        "connector": {"id": "feishu", "name": "飞书文档", "category": "工作协作", "icon": "飞"},
        "items": [{"title": out["title"], "meta": "飞书文档", "summary": out["text"][:240]}],
        "understanding": core.build_understanding(out["text"], "paste"),
        "insights": [],
        "synthetic": False,
        "source": "feishu",
    }
    pseudo = _enrich(pseudo)
    data = _start_reviewed_read(pseudo, source_label=f"飞书文档 · {out['title']}", source_text=out['text'])
    core.audit(data["session"]["id"], "lark.read", f"identity={out['identity']} len={out['length']}", "用户选择的单篇文档")
    return data



@app.post("/api/local-files/preview-document", response_model=LocalDocumentPreviewResponse)
def local_document_preview(body: LocalDocumentPreviewIn):
    """Parse a selected Word file in memory; do not persist or call the model."""
    if ('/' in body.name or chr(92) in body.name or any(ord(c) < 32 for c in body.name)
            or Path(body.name).suffix.lower() != '.docx'):
        raise HTTPException(400, '文件名或类型无效。')
    try:
        result = local_documents.extract_docx(body.data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {**result, 'name': body.name, 'notice': '仅提取正文；图片、扫描内容和批注不包含在预览中。'}



@app.post("/api/local-files/confirm", response_model=contract.ConversationResponse, response_model_exclude_unset=True)
def local_files_confirm(body: LocalFilesConfirmIn):
    """Accept only content already previewed in the user's browser; no filesystem access."""
    for f in body.files:
        if ('/' in f.name or chr(92) in f.name or any(ord(c) < 32 for c in f.name)
                or f.name in ('.', '..') or Path(f.name).suffix.lower() not in local_source.EXTS):
            raise HTTPException(400, '文件名或类型无效')
        if not f.text.strip() or '\x00' in f.text or len(f.text.encode('utf-8')) > local_source.MAX_BYTES:
            raise HTTPException(400, '文件内容为空或无效')
    sources = [{'connector_id': 'local_files', 'label': f'本地文件 · {f.name}', 'text': f.text,
                'understanding': core.build_understanding(f.text, 'paste'),
                'items': [{'title': f.name, 'meta': '用户选择 · 文本片段', 'summary': f.text[:240]}],
                'insights': [], 'starters': []} for f in body.files]
    # The legacy no-session API remains supported. It creates a session first;
    # if the atomic batch fails, remove that otherwise-orphaned session.
    sid = body.session_id
    created = not sid
    if created:
        sid = core.create_session('empty', greeting=f'我看到了你选择的「{body.files[0].name}」。你想先聊哪一部分？')['session']['id']
    try:
        core.attach_sources_to_session(sid, sources)
    except Exception as error:
        if created:
            core.delete_session(sid)
        if isinstance(error, LookupError):
            raise HTTPException(404, 'session not found')
        if isinstance(error, core.SourceConflict):
            raise contract.ContractError(409, 'source_conflict', str(error))
        raise
    result = {'session': core.get_session(sid), 'messages': core.get_messages(sid),
              'memories': core.list_memories(sid), 'context': core.get_session_context(sid),
              'bookmark': core.latest_bookmark(sid), 'insights': []}
    if created:
        result['understanding'] = core.build_understanding('\n\n'.join(f.text for f in body.files), 'paste')
    return result


@app.post("/api/lark/attach", response_model=contract.ConversationResponse, response_model_exclude_unset=True)
def lark_attach(body: LarkAttachIn):
    sess = core.get_session(body.session_id)
    if not sess:
        raise HTTPException(404, 'session not found')
    _check_attachment_target(body.session_id)
    out = _consume_preview('lark:' + body.url, body.preview_id)
    pseudo = _enrich({
        'ok': True,
        'connector': {'id': 'feishu', 'name': '飞书文档', 'category': '工作协作', 'icon': '飞'},
        'items': [{'title': out['title'], 'meta': '飞书文档', 'summary': out['text'][:240]}],
        'understanding': core.build_understanding(out['text'], 'paste'),
        'insights': [], 'synthetic': False, 'source': 'feishu',
    })
    try:
        core.attach_source_to_empty_session(
            body.session_id, f"飞书文档 · {out['title']}", out['text'], pseudo['understanding'],
            pseudo.get('items') or [], pseudo.get('insights') or [], pseudo.get('starters') or [])
    except LookupError:
        raise HTTPException(404, 'session not found')
    except core.SourceConflict as e:
        raise contract.ContractError(409, "source_conflict", str(e))
    core.audit(body.session_id, 'lark.read', f"identity={out['identity']} len={out['length']}", '用户确认预览的单篇文档')
    return {'session': core.get_session(body.session_id), 'messages': core.get_messages(body.session_id),
            'memories': core.list_memories(body.session_id), 'context': core.get_session_context(body.session_id),
            'bookmark': core.latest_bookmark(body.session_id), 'insights': pseudo.get('insights') or []}


@app.post("/api/session", response_model=contract.ConversationResponse, response_model_exclude_unset=True)
def create_session(body: SessionIn):
    return core.create_session(mode=body.mode, text=body.text)


@app.get('/api/conversation/changes',response_model=contract.ConversationChangesResponse)
def conversation_change_feed(request: Request,response: Response,after: str | None = None):
    response.headers['Cache-Control']='no-store'
    if len(request.query_params.getlist('after'))>1:
        raise contract.ContractError(400,'invalid_changes_cursor','Invalid change cursor.')
    try:return conversation_changes.read(core.DB_PATH,after)
    except conversation_changes.InvalidCursor:
        raise contract.ContractError(400,'invalid_changes_cursor','Invalid change cursor.') from None
    except conversation_changes.ConversationNotInitialized:
        raise contract.ContractError(409,'conversation_not_initialized','Conversation is not initialized.') from None
    except (sqlite3.Error,ValueError):
        raise contract.ContractError(503,'changes_unavailable','Changes are temporarily unavailable.') from None


@app.get("/api/conversation", response_model=contract.ConversationResponse, response_model_exclude_unset=True)
def conversation():
    sid = core.conversation_id()
    return {"session": core.get_session(sid), "messages": core.get_messages(sid),
            "memories": core.list_memories(sid), "bookmark": core.latest_bookmark(sid),
            "context": core.get_session_context(sid)}


@app.get("/api/sessions")
def sessions():
    return {"sessions": core.list_sessions()}


def _mood_call(function, *args):
    try:
        return function(*args)
    except moods.MoodConflict as error:
        raise contract.ContractError(409, 'mood_conflict', str(error),
                                     current_updated_at=error.current_updated_at) from error
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@app.get('/api/moods', response_model=contract.MoodListResponse)
def get_moods(response: Response, session_id: str = Query(min_length=1, max_length=128)):
    response.headers['Cache-Control'] = 'no-store'
    return {'moods': _mood_call(moods.list_entries, core.DB_PATH, session_id)}


@app.put('/api/moods/{day}', response_model=contract.MoodEntryResponse)
def save_mood(day: str, body: MoodSaveIn):
    if not body.confirmed:
        raise contract.ContractError(400, 'confirmation_required', '请先确认这条心情记录。')
    return _mood_call(moods.save, core.DB_PATH, body.session_id, day, body.x, body.y, body.note, body.expected_updated_at)


@app.delete('/api/moods/{day}', response_model=contract.MoodDeleteResponse)
def delete_mood(day: str, session_id: str = Query(min_length=1, max_length=128),
                expected_updated_at: str = Query(min_length=1, max_length=64)):
    return {'deleted': _mood_call(moods.delete, core.DB_PATH, session_id, day, expected_updated_at)}


@app.post('/api/mood-suggestions', response_model=contract.MoodSuggestionResponse)
def suggest_mood(body: MoodSuggestionIn, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    if not body.consent:
        raise contract.ContractError(400, 'confirmation_required', '请先同意分析这次提供的文字。')
    return _mood_call(moods.suggestion, core.DB_PATH, body.session_id, body.text)


def _mood_operation_call(function, *args):
    try:
        return function(*args)
    except mood_operations.IdentityConflict as error:
        raise contract.ContractError(409, 'mood_operation_identity_conflict', str(error)) from error
    except mood_operations.InvalidOperation as error:
        raise contract.ContractError(400, 'invalid_mood_operation', str(error)) from error
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@app.post('/api/mood-operations', response_model=contract.MoodOperationResponse)
def apply_mood_operation(body: MoodOperationIn, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    if not body.confirmed:
        raise contract.ContractError(400, 'confirmation_required', '请先确认这次心情操作。')
    return _mood_operation_call(mood_operations.apply, core.DB_PATH, body.session_id,
                                body.request_id, body.operation_json)


@app.get('/api/mood-operations/{request_id}', response_model=contract.MoodOperationResponse)
def get_mood_operation(response: Response,
                       request_id: str = ApiPath(min_length=8, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]+$'),
                       session_id: str = Query(min_length=1, max_length=128)):
    response.headers['Cache-Control'] = 'no-store'
    return _mood_operation_call(mood_operations.get, core.DB_PATH, session_id, request_id)


@app.post('/api/mood-operations/{request_id}/cancel', response_model=contract.MoodOperationResponse)
def cancel_mood_operation(body: MoodOperationCancelIn, response: Response,
                          request_id: str = ApiPath(min_length=8, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]+$')):
    response.headers['Cache-Control'] = 'no-store'
    if not body.confirmed:
        raise contract.ContractError(400, 'confirmation_required', '请先确认停止这次心情操作。')
    return _mood_operation_call(mood_operations.cancel, core.DB_PATH, body.session_id,
                                request_id, body.operation_sha256, body.kind)


def _contact_policy_call(function,*args,**kwargs):
    try:
        return function(*args,**kwargs)
    except companion_boundary.BoundaryConflict as error:
        raise contract.ContractError(409,'boundary_conflict',str(error),current_revision=error.current_revision) from error
    except followups.FollowupConflict as error:
        raise contract.ContractError(409,'contact_conflict',str(error)) from error
    except LookupError as error:
        raise HTTPException(404,str(error)) from error
    except ValueError as error:
        raise HTTPException(400,str(error)) from error


@app.get('/api/companion-boundary',response_model=BoundaryResponse)
def get_companion_boundary(response:Response,session_id:str=Query(min_length=1,max_length=128)):
    response.headers['Cache-Control']='no-store'
    return _contact_policy_call(companion_boundary.get,core.DB_PATH,session_id)


@app.put('/api/companion-boundary',response_model=BoundaryResponse)
def put_companion_boundary(body:BoundaryIn):
    if not body.confirmed:raise contract.ContractError(400,'confirmation_required','请先确认这次陪伴边界。')
    return _contact_policy_call(companion_boundary.put,core.DB_PATH,body.session_id,
        expected_revision=body.expected_revision,mode=body.mode,until=body.until,time_zone=body.time_zone)


@app.post('/api/followups/{followup_id}/contact/claim',response_model=ContactClaimResponse)
def claim_contact(followup_id:str,body:ContactClaimIn):
    return _contact_policy_call(proactive_policy.claim,core.DB_PATH,body.session_id,followup_id,body.occurrence_at,channel=body.channel)


@app.post('/api/followup-contacts/{claim_id}/recheck',response_model=ContactRecheckResponse)
def recheck_contact(claim_id:str,body:NotificationRecheckIn):
    return _contact_policy_call(proactive_policy.recheck,core.DB_PATH,body.session_id,claim_id)


@app.post('/api/followup-contacts/{claim_id}/finish',response_model=ContactFinishResponse)
def finish_contact(claim_id:str,body:NotificationFinishIn):
    return _contact_policy_call(proactive_policy.finish,core.DB_PATH,body.session_id,claim_id,body.state)


def _notification_policy_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except followups.FollowupConflict as error:
        raise contract.ContractError(409, "notification_conflict", str(error)) from error
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@app.get('/api/followup-notification-settings', response_model=NotificationSettingsResponse)
def notification_settings(response: Response, session_id: str = Query(min_length=1, max_length=128)):
    response.headers['Cache-Control'] = 'no-store'
    return _notification_policy_call(proactive_policy.get_settings, core.DB_PATH, session_id)


@app.put('/api/followup-notification-settings', response_model=NotificationSettingsResponse)
def update_notification_settings(body: NotificationSettingsIn):
    return _notification_policy_call(proactive_policy.set_settings, core.DB_PATH, body.session_id,
        enabled=body.enabled, time_zone=body.time_zone, quiet_start=body.quiet_start, quiet_end=body.quiet_end,
        cooldown_minutes=body.cooldown_minutes, daily_limit=body.daily_limit, pause_until=body.pause_until,
        expected_revision=body.expected_revision)


@app.post('/api/followups/{followup_id}/desktop-notification/claim', response_model=NotificationClaimResponse)
def claim_followup_notification(followup_id: str, body: NotificationClaimIn):
    return _notification_policy_call(proactive_policy.claim, core.DB_PATH, body.session_id, followup_id, body.occurrence_at)


@app.post('/api/followup-notifications/{claim_id}/recheck', response_model=NotificationRecheckResponse)
def recheck_followup_notification(claim_id: str, body: NotificationRecheckIn):
    return _notification_policy_call(proactive_policy.recheck, core.DB_PATH, body.session_id, claim_id)


@app.post('/api/followup-notifications/{claim_id}/finish', response_model=NotificationFinishResponse)
def finish_followup_notification(claim_id: str, body: NotificationFinishIn):
    return _notification_policy_call(proactive_policy.finish, core.DB_PATH, body.session_id, claim_id, body.state)



@app.get("/api/followups", response_model=contract.FollowupListResponse, response_model_exclude_unset=True)
def get_followups(session_id: str = Query(min_length=1, max_length=128)):
    if not core.get_session(session_id):
        raise HTTPException(404, "对话不存在。")
    return {"followups": followups.list_for_session(core.DB_PATH, session_id)}


@app.post("/api/followups", response_model=contract.FollowupResponse, response_model_exclude_unset=True)
def create_followup(body: FollowupCreateIn):
    if not body.confirmed:
        raise contract.ContractError(400, "confirmation_required", "请先确认要保存这条跟进。")
    try:
        return followups.create(core.DB_PATH, body.session_id, body.content, body.due_at, body.request_id, repeat_rule=body.repeat_rule, time_zone=body.time_zone, quiet_start=body.quiet_start, quiet_end=body.quiet_end, allow_contact=body.allow_contact, contact_window_minutes=body.contact_window_minutes, contact_topic=body.contact_topic)
    except followups.FollowupConflict as error:
        raise contract.ContractError(409, "followup_conflict", str(error)) from error
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@app.post("/api/followups/{followup_id}/transition", response_model=contract.FollowupResponse, response_model_exclude_unset=True)
@app.patch("/api/followups/{followup_id}", response_model=contract.FollowupResponse, response_model_exclude_unset=True)
def change_followup(followup_id: str, body: FollowupChangeIn):
    try:
        return followups.transition(core.DB_PATH, body.session_id, followup_id, body.status, occurrence_at=body.occurrence_at)
    except followups.FollowupConflict as error:
        raise contract.ContractError(409, "followup_conflict", str(error)) from error
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@app.post("/api/session/{sid}/delivery/stop", response_model=contract.DeliveryStopResponse,
          response_model_exclude_unset=True)
def stop_message_delivery(sid: str, body: DeliveryStopIn | None = None):
    result = core.stop_message_delivery(sid, body.message_id if body else None)
    if result is None:
        raise HTTPException(404, "session not found")
    return result


@app.patch("/api/session/{sid}")
def rename_session(sid: str, body: SessionRenameIn):
    out = core.rename_session(sid, body.title)
    if not out:
        raise HTTPException(404, "session not found")
    return out


@app.get("/api/session/{sid}", response_model=contract.ConversationResponse, response_model_exclude_unset=True)
def get_session(sid: str):
    sess = core.get_session(sid)
    if not sess:
        raise HTTPException(404, "session not found")
    return {
        "session": sess,
        "messages": core.get_messages(sid),
        "memories": core.list_memories(sid),
        "bookmark": core.latest_bookmark(sid),
        "context": core.get_session_context(sid),
    }


_turn_stores = {}
_turn_stores_lock = threading.RLock()


def _turn_store():
    # Tests use a temporary DB per case; the live app uses one local process.
    with _turn_stores_lock:
        key = str(core.DB_PATH)
        if key not in _turn_stores:
            _turn_stores[key] = chat_turns.ChatTurnStore(key)
        return _turn_stores[key]


def _turn_response(record):
    out = record.public()
    result = record.outcome or {}
    if record.status in ("completed", "cancelled"):
        messages = core.get_messages(record.session_id)
        reply = next((m for m in messages if m["id"] == result.get("assistant_message_id")), None)
        out["result"] = {"request_id": record.request_id, "reply": reply["text"] if reply else "",
                         "action": result.get("action"), "state": result.get("state", "listening"),
                         "user_message_id": result.get("user_message_id"), "messages": messages,
                         "memories": core.list_memories(record.session_id),
                         "cancelled": record.status == "cancelled" or bool(result.get("suppressed"))}
    return out


@app.get("/api/chat/turn/{request_id}", response_model=contract.ChatTurnResponse, response_model_exclude_unset=True)
def chat_turn_status(request_id: str, session_id: str = Query(...)):
    try:
        return _turn_response(_turn_store().get(session_id, request_id))
    except chat_turns.TurnNotFound:
        raise HTTPException(404, "未找到这次请求，请核对当前对话。")


@app.post("/api/chat/turn/{request_id}/cancel", response_model=contract.ChatTurnResponse, response_model_exclude_unset=True)
def cancel_chat_turn(request_id: str, body: ChatCancelIn):
    try:
        store = _turn_store()
        with store.reply_lock(body.session_id, request_id):
            record = store.request_cancel(body.session_id, request_id)
            outcome = record.outcome or {}
            # The user can supplement a turn after the model commits but before
            # the browser receives it. Hide only this latest conversational
            # answer; never roll back a memory command, safety response or action.
            if record.status == "completed" and outcome.get("action") in ("model.reply", "context.reply", "capability.reply", None, "suggestion"):
                conn = core.get_db()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    latest = conn.execute("SELECT id FROM messages WHERE session_id=? AND suppressed=0 ORDER BY rowid DESC LIMIT 1", (body.session_id,)).fetchone()
                    if latest and latest["id"] == outcome.get("assistant_message_id"):
                        conn.execute("UPDATE messages SET suppressed=1 WHERE id=?", (latest["id"],))
                        outcome = {**outcome, "suppressed": True, "state": "listening"}
                        conn.execute("UPDATE chat_turns SET outcome_json=? WHERE request_id=? AND session_id=?",
                                     (json.dumps(outcome, ensure_ascii=False), request_id, body.session_id))
                    conn.commit()
                finally:
                    conn.close()
                record = store.get(body.session_id, request_id)
            return _turn_response(record)
    except chat_turns.TurnNotFound:
        raise HTTPException(404, "这次请求尚未到达服务端。")


@app.post("/api/chat", response_model=contract.ChatResponse, response_model_exclude_unset=True,
          responses={202: {"model": contract.ChatTurnResponse, "description": "Same request is running or requires outcome review; never silently re-execute."}})
def chat(body: ChatIn):
    if not core.get_session(body.session_id):
        raise HTTPException(404, "session not found")
    if body.time_zone is not None:
        try: followups._zone(body.time_zone)
        except ValueError as error: raise HTTPException(400,str(error)) from error
    store, claim = None, None
    if body.request_id:
        store = _turn_store()
        try:
            claim = store.claim(body.session_id, body.request_id, body.text,
                                options={"memory_proposals":body.memory_proposals, **({"time_zone":body.time_zone} if body.time_zone is not None else {})})
        except chat_turns.TurnConflict:
            raise contract.ContractError(409, "request_id_conflict", "请求标识已用于不同内容，请先核对对话。")
        except chat_turns.TurnNotFound:
            raise HTTPException(404, "session not found")
        if not claim.claimed:
            record = _turn_response(claim.record)
            if record.get("result"):
                return record["result"]
            return JSONResponse(record, status_code=202)
    try:
        result = core.generate_reply(
            body.session_id, body.text,
            **({"time_zone":body.time_zone} if body.time_zone is not None else {}),
            **({"should_cancel": store.cancel_check(body.session_id, body.request_id, claim.token),
                "reply_lock": store.reply_lock(body.session_id, body.request_id)} if store else {}))
        if body.memory_proposals and not result.get("cancelled") and result.get("action") != "safety":
            result["memory_proposal"] = core.propose_from_message(body.session_id, result["user_message_id"])
        if store:
            result["request_id"] = body.request_id
            if not core.get_session(body.session_id):
                return result
            if result.get("cancelled"):
                store.finish_cancelled(body.session_id, body.request_id, claim.token,
                                       outcome={"user_message_id": result["user_message_id"],
                                                "action": "cancelled", "state": "listening"})
            else:
                store.complete(body.session_id, body.request_id, claim.token,
                               {"user_message_id": result["user_message_id"],
                                "assistant_message_id": result.get("assistant_message_id"),
                                "action": result.get("action"), "state": result.get("state")})
        return result
    except BudgetExceeded as e:
        if store:
            store.mark_unknown(body.session_id, body.request_id, claim.token, error_code="budget_exceeded")
        raise contract.ContractError(429, "chat_budget_exceeded", str(e))
    except Exception:
        if store:
            try:
                store.mark_unknown(body.session_id, body.request_id, claim.token)
            except chat_turns.TurnLeaseLost:
                pass
        raise


@app.get("/api/carryover")
def carryover(session_id: str = Query(...)):
    if not core.get_session(session_id):
        raise HTTPException(404, "session not found")
    return {"memories": core.carryover_memories(session_id),
            "current_confirmed": [m for m in core.list_memories(session_id) if m['status'] == 'confirmed']}


@app.post("/api/carryover/import")
def carryover_import(body: CarryoverIn):
    try:
        return core.import_carryover(body.session_id, body.ids, body.expected_versions, body.expected_target)
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/api/memory", response_model=contract.MemoryListResponse, response_model_exclude_unset=True)
def list_memory(session_id: str = Query(...)):
    return {"memories": core.list_memories(session_id)}


@app.post("/api/memory", response_model=contract.MemoryResponse, response_model_exclude_unset=True)
def add_memory(body: MemoryIn):
    return core.add_memory(body.session_id, body.kind, body.text, source=body.source)


@app.post("/api/memory/proposal", response_model=contract.MemoryResponse, response_model_exclude_unset=True)
def save_memory_proposal(body: MemoryProposalIn):
    try:
        return core.save_proposed_memory(body.session_id, body.message_id, confirm=body.confirm)
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/api/memory/{mid}/history", response_model=contract.MemoryHistoryResponse, response_model_exclude_unset=True)
def mem_history(mid: str):
    return {"revisions": core.memory_history(mid)}


@app.patch("/api/memory/{mid}", response_model=contract.MemoryResponse, response_model_exclude_unset=True)
def patch_memory(mid: str, body: MemoryPatch):
    out = core.update_memory(mid, text=body.text, status=body.status, expected_version=body.expected_version)
    if not out:
        raise HTTPException(404, "memory not found")
    return out


@app.delete("/api/memory/{mid}", response_model=contract.OKResponse, response_model_exclude_unset=True)
def remove_memory(mid: str, expected_version: int | None = Query(default=None, ge=1)):
    if not core.delete_memory(mid, expected_version=expected_version):
        raise HTTPException(404, "memory not found")
    return {"ok": True}


@app.get("/api/export")
def export(session_id: str | None = Query(default=None)):
    return core.export_data(session_id)


@app.post("/api/bookmark")
def bookmark(body: BookmarkIn):
    try:
        return core.create_bookmark(body.session_id, body.note, body.choice, body.next_step,
                                    body.source_memory_id, body.source_version,
                                    body.source_label, body.source_quote, body.source_attachment_id)
    except LookupError:
        raise HTTPException(404, "session not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/bookmark/latest")
def bookmark_latest(session_id: str = Query(...)):
    return {"bookmark": core.latest_bookmark(session_id)}


@app.post("/api/bookmark/{bid}/commit")
def bookmark_commit(bid: str):
    out = core.commit_bookmark(bid)
    if not out:
        raise HTTPException(404, "bookmark not found")
    return out


@app.get("/api/device/presentation")
def device_presentation():
    return device_bridge.state()


# In-memory only: explicit opt-in grants expire and are invalidated on stop.
# The score is neither retained here nor added to conversations or memories.
_mindlink_grants: dict[str, float] = {}
_mindlink_lock = threading.Lock()
_MINDLINK_GRANT_TTL = 15 * 60
_MINDLINK_MAX_GRANTS = 64


def _mindlink_local_request(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    try:
        local_peer = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local_peer = False
    expected_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
    origin = request.headers.get("origin")
    if not local_peer or request.url.hostname not in ("127.0.0.1", "localhost", "::1") or (origin is not None and origin != expected_origin):
        raise HTTPException(403, "local same-origin requests only", headers={"Cache-Control": "no-store"})


def _mindlink_valid(token: str | None) -> bool:
    if not token or len(token) > 256:
        return False
    with _mindlink_lock:
        expires = _mindlink_grants.get(token)
        if expires is None:
            return False
        if expires <= time.monotonic():
            _mindlink_grants.pop(token, None)
            return False
        return True


@app.post("/api/mindlink/start")
def mindlink_start(body: MindLinkConsentIn, request: Request, response: Response):
    _mindlink_local_request(request, response)
    if body.consent is not True:
        raise HTTPException(400, "explicit consent required", headers={"Cache-Control": "no-store"})
    now = time.monotonic()
    with _mindlink_lock:
        for token, expires in list(_mindlink_grants.items()):
            if expires <= now:
                del _mindlink_grants[token]
        if len(_mindlink_grants) >= _MINDLINK_MAX_GRANTS:
            raise HTTPException(429, "too many active grants", headers={"Cache-Control": "no-store"})
        token = secrets.token_urlsafe(32)
        _mindlink_grants[token] = now + _MINDLINK_GRANT_TTL
    return {"enabled": True, "token": token, "expires_in_seconds": _MINDLINK_GRANT_TTL}


@app.post("/api/mindlink/state")
def mindlink_state(request: Request, response: Response, body: MindLinkEmptyIn | None = None,
                   x_mindlink_token: str | None = Header(default=None)):
    _mindlink_local_request(request, response)
    if not _mindlink_valid(x_mindlink_token):
        raise HTTPException(403, "MindLink authorization missing or expired", headers={"Cache-Control": "no-store"})
    result = mindlink.read_attention(enabled=True)
    # Stopping while a read is in flight must not return that reading.
    if not _mindlink_valid(x_mindlink_token):
        raise HTTPException(403, "MindLink authorization missing or expired", headers={"Cache-Control": "no-store"})
    return result


@app.post("/api/mindlink/stop")
def mindlink_stop(request: Request, response: Response, body: MindLinkEmptyIn | None = None,
                  x_mindlink_token: str | None = Header(default=None)):
    _mindlink_local_request(request, response)
    if not x_mindlink_token or len(x_mindlink_token) > 256:
        raise HTTPException(403, "MindLink authorization missing or expired", headers={"Cache-Control": "no-store"})
    with _mindlink_lock:
        expires = _mindlink_grants.pop(x_mindlink_token, None)
    if expires is None or expires <= time.monotonic():
        raise HTTPException(403, "MindLink authorization missing or expired", headers={"Cache-Control": "no-store"})
    return {"enabled": False}


@app.post("/api/device/button")
def device_button(body: ButtonIn | None = None):
    sid = body.session_id if body else "demo"
    evt = device_bridge.button_press(sid)
    core.audit(sid, "device.button", evt["id"], "模拟实体按钮按下")
    return evt


@app.post("/api/device/display")
def device_display(body: DisplayIn):
    cmd = device_bridge.display(body.session_id, body.text, body.color)
    core.audit(body.session_id, "device.display", f'{cmd["id"]} {cmd["text"][:40]}', "显示命令 + ACK")
    return cmd


@app.post("/api/device/{action}")
def device(action: str):
    if action == "start":
        return core.device_start()
    if action == "stop":
        return core.device_stop()
    raise HTTPException(400, "action must be start|stop")


@app.get("/api/device/frame")
def device_frame():
    return core.device_frame()


@app.delete("/api/session/{sid}")
def delete_session(sid: str):
    if not core.get_session(sid):
        raise HTTPException(404, "session not found")
    return core.delete_session(sid)


@app.get("/api/next-step")
def next_step(session_id: str = Query(...)):
    return core.suggest_next_step(session_id)


@app.post("/api/source/revoke", response_model=contract.SourceRevokeResponse, response_model_exclude_unset=True)
def source_revoke(body: SourceRevokeIn):
    if not core.get_session(body.session_id):
        raise HTTPException(404, "session not found")
    result = core.revoke_source(body.session_id, body.source_id)
    if not result.get("ok"):
        raise HTTPException(404, result.get("reason", "source not found"))
    return result


@app.post("/api/action", response_model=contract.ActionResponse, response_model_exclude_unset=True)
def action_preview(body: ActionIn):
    try:
        return core.create_action(body.session_id, body.kind, body.title, body.detail, body.when)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/action/{aid}/commit", response_model=contract.ActionResponse, response_model_exclude_unset=True)
def action_commit(aid: str, body: ActionCommitIn | None = None):
    out = core.commit_action(aid, real=bool(body and body.real))
    if not out:
        raise HTTPException(404, "action not found")
    return out


@app.get("/api/actions", response_model=contract.ActionListResponse, response_model_exclude_unset=True)
def actions(session_id: str | None = Query(default=None)):
    return {"actions": core.list_actions(session_id)}


@app.get("/api/metrics")
def get_metrics(session_id: str | None = Query(default=None)):
    return core.metrics(session_id)


@app.get("/api/audit")
def audit(session_id: str | None = Query(default=None)):
    return {"events": core.audit_list(session_id)}


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/m")
def mobile():
    return FileResponse(WEB / "m.html")


@app.get("/api/plugins")
def plugins():
    return {"meme": plugin_bridge.memes(), "pet": plugin_bridge.pet()}


@app.get("/plugin-memes/{pack}/{tag}/{name}")
def plugin_meme(pack: str, tag: str, name: str):
    f = plugin_bridge.meme_file(pack, tag, name)
    if not f:
        raise HTTPException(404, "meme not found")
    return FileResponse(f)


@app.get("/download/desktop")
def download_desktop():
    f = _latest("xinji-echo-desktop-*.zip")
    if not f:
        raise HTTPException(404, "桌面包尚未生成：运行 scripts/package-desktop.sh")
    return FileResponse(f, media_type="application/zip", filename=f.name)


@app.get("/download/source")
def download_source():
    f = _latest("xinji-echo-source-*.zip")
    if not f:
        raise HTTPException(404, "源码包尚未生成：运行 scripts/package.sh")
    return FileResponse(f, media_type="application/zip", filename=f.name)


app.mount("/static", StaticFiles(directory=WEB), name="static")


if __name__ == "__main__":
    import uvicorn

    core.init_db()
    uvicorn.run("server.main:app", host="127.0.0.1", port=int(os.getenv("PORT", "18787")), reload=False)


# Local-only adapters; not registered on the paired remote application.
@app.post("/api/connector-auth/{provider}/start", response_model=connector_auth.LoginStatus)
def connector_login_start(provider: str):
    return connector_auth.login_start(provider)


@app.get("/api/connector-auth/{provider}/status", response_model=connector_auth.LoginStatus)
def connector_login_status(provider: str):
    return connector_auth.login_status(provider)
