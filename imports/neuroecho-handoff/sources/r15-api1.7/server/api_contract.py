"""Additive HTTP contracts for clients; never probe accounts, devices or credentials.

Unknown response fields are deliberately preserved. Routes use exclude_unset so
introducing a schema does not invent absent/null fields for legacy clients.
"""
from __future__ import annotations

from typing import Any, Literal
import sys

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field


CONTRACT_VERSION = "1.7.0"


class OpenResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class SessionResponse(OpenResponse):
    id: str
    created_at: str | None = None
    mode: str | None = None
    state: str | None = None
    source_label: str | None = None
    conversation_style: str | None = None


class MessageResponse(OpenResponse):
    id: str
    role: str
    text: str
    citations: list[dict[str, Any]] | None = None
    suggestions: list[str] | None = None
    created_at: str | None = None
    bubbles: list[str] | None = Field(default=None, description="Currently delivered parts of this reply, in order.")
    delivery_pending: bool | None = Field(default=None, description="Additional reply parts are still scheduled.")
    delivery_next_ms: int | None = Field(default=None, description="Suggested delay before refreshing pending parts.")
    action_proposal: dict[str, Any] | None = Field(default=None, description="Reviewable proposal only; no action has been performed.")


class MemoryResponse(OpenResponse):
    id: str
    session_id: str | None = None
    kind: str = Field(description="Known kinds: fact, inference, question; retain future values.")
    text: str
    status: str = Field(description="Known states: candidate, confirmed; unknown values are not confirmation.")
    version: int
    source: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryListResponse(OpenResponse):
    memories: list[MemoryResponse]


class MoodEntryResponse(OpenResponse):
    date: str
    x: float
    y: float
    note: str
    updated_at: str = Field(description="Exact ISO UTC CAS token; compare without modifying. Globally increasing across writes and deletion/recreation.")


class MoodListResponse(OpenResponse):
    moods: list[MoodEntryResponse]


class MoodDraftResponse(OpenResponse):
    x: float | None
    y: float | None
    evidence: list[str]
    explanation: str


class MoodSuggestionResponse(OpenResponse):
    suggestion: MoodDraftResponse | None
    limitations: list[str]


class MoodDeleteResponse(OpenResponse):
    deleted: bool


class MoodOperationResponse(OpenResponse):
    session_id: str
    request_id: str
    operation_sha256: str | None = Field(description="SHA256 of the exact original UTF8 JSON string; null only for not_found.")
    kind: Literal['save', 'delete'] | None
    state: Literal['applied', 'conflict', 'cancelled', 'not_found']
    result_updated_at: str | None = Field(description="Historical outcome version, not proof of current diary content. Query moods separately.")


class MemoryRevisionResponse(OpenResponse):
    id: str
    text: str
    status: str
    version: int
    source: str | None = None
    created_at: str | None = None


class MemoryHistoryResponse(OpenResponse):
    revisions: list[MemoryRevisionResponse]


class SourceResponse(OpenResponse):
    id: str
    connector_id: str | None = None
    label: str | None = None
    title: str | None = None
    items: list[dict[str, Any]] | None = None
    insights: list[dict[str, Any]] | None = None
    starters: list[str] | None = None
    stale: bool | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ContextResponse(OpenResponse):
    connector_id: str | None = None
    items: list[dict[str, Any]] | None = None
    insights: list[dict[str, Any]] | None = None
    starters: list[str] | None = None
    sources: list[SourceResponse] | None = None


class BookmarkResponse(OpenResponse):
    id: str
    note: str | None = None
    status: str | None = None
    next_step: str | None = None


class ConversationChangesResponse(OpenResponse):
    service_instance_id: str
    conversation_id: str
    cursor: str = Field(max_length=2048, description="Opaque invalidation cursor; retain exact bytes, not a write receipt.")
    reset_required: bool
    domains: list[Literal['conversation','messages','memories','sources','moods','followups','boundary','actions','turns']]
    reset_reason: Literal['initial','identity_changed','too_old','ahead'] | None


class ConversationResponse(OpenResponse):
    session: SessionResponse
    messages: list[MessageResponse]
    memories: list[MemoryResponse]
    bookmark: BookmarkResponse | None = None
    context: ContextResponse | None = None


class ConnectorResponse(OpenResponse):
    id: str
    name: str | None = None
    status: str | None = None
    reads: list[str] | None = None


class SourceCatalogResponse(OpenResponse):
    sources: list[ConnectorResponse]


class SourceReadResponse(OpenResponse):
    ok: bool
    preview_id: str | None = None
    connector: ConnectorResponse | None = None
    items: list[dict[str, Any]] | None = None
    insights: list[dict[str, Any]] | None = None
    starters: list[str] | None = None
    understanding: dict[str, Any] | None = None
    title: str | None = None
    preview: str | None = None
    length: int | None = None
    extracted_length: int | None = None
    truncated: bool | None = None
    error: str | None = None
    error_code: str | None = None
    hint: str | None = None


class SourceRevokeResponse(OpenResponse):
    ok: bool
    cleaned: int | None = None
    state: str | None = None
    review_required: int | None = None
    remaining_sources: int | None = None
    revoked_source_ids: list[str] | None = None


class ChatResponse(OpenResponse):
    reply: str
    messages: list[MessageResponse]
    memories: list[MemoryResponse]
    request_id: str | None = None
    action: str | None = None
    state: str | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    cancelled: bool | None = None


class ChatTurnResponse(OpenResponse):
    request_id: str
    session_id: str
    status: Literal["running", "completed", "cancelled", "unknown"]
    cancel_requested: bool
    outcome: dict[str, Any] | None = None
    error_code: str | None = None
    created_at: str
    updated_at: str
    result: ChatResponse | None = None


class ActionResponse(OpenResponse):
    id: str
    session_id: str | None = None
    kind: str
    title: str
    detail: str | None = None
    status: str = Field(description="Known states: previewed, executing, committed, failed, unknown. Only committed proves success; future values require review.")
    receipt: str | None = None
    real: int | None = None
    when_text: str | None = None
    created_at: str | None = None
    committed_at: str | None = None
    error: str | None = None


class ActionListResponse(OpenResponse):
    actions: list[ActionResponse]


class FollowupResponse(OpenResponse):
    id: str
    session_id: str
    request_id: str
    content: str
    due_at: str
    status: str = Field(description="Known states: pending, done, cancelled. Due does not mean a notification was delivered.")
    due: bool
    repeat_rule: Literal["once", "daily"] = "once"
    time_zone: str = "UTC"
    quiet_start: str | None = None
    quiet_end: str | None = None
    quiet: bool = False
    paused: bool = False
    available: bool = False
    created_due_at: str | None = None
    last_occurrence_at: str | None = None
    last_completed_at: str | None = None
    allow_contact: bool = False
    contact_window_minutes: int = 30
    contact_topic: str | None = None
    contact_expires_at: str | None = None
    contact_eligible: bool = False
    contact_reason: str | None = None
    review_available: bool = False
    boundary_revision: int = 0
    created_at: str
    updated_at: str


class FollowupListResponse(OpenResponse):
    followups: list[FollowupResponse]


class OKResponse(OpenResponse):
    ok: bool


class DeliveryStopResponse(OpenResponse):
    ok: bool
    stopped: bool = Field(description="True only when the specified current pending reply was truncated.")
    message_id: str | None
    reason: Literal["stopped", "message_id_required", "not_current", "not_pending"]


class ErrorResponse(OpenResponse):
    detail: Any = Field(description="Legacy detail is preserved, including validation error arrays.")
    error_code: str
    expected_version: int | None = None
    current_version: int | None = None
    current_revision: int | None = None
    current_updated_at: str | None = Field(default=None, description="Current mood-entry CAS token on conflict, or null when the day is absent.")


ERROR_CODES = {
    400: "invalid_request", 401: "authentication_required", 403: "permission_denied",
    404: "not_found", 405: "method_not_allowed", 409: "conflict",
    422: "validation_error", 429: "rate_limited", 503: "service_unavailable",
}
ERROR_RESPONSES = {status: {"model": ErrorResponse} for status in ERROR_CODES}


class ContractError(HTTPException):
    def __init__(self, status_code: int, error_code: str, detail: str, **context: Any):
        super().__init__(status_code, detail)
        self.error_code = error_code
        self.context = context


class CapabilityResponse(OpenResponse):
    contract_version: str
    deployment_mode: Literal["local_single_user", "paired_single_owner"]
    service_platform: str
    features: dict[str, bool]
    platform_status: dict[str, str]
    limits: dict[str, int]
    connection_status: Literal["not_probed"]
    limitations: list[str]


def capabilities(*, chat_budget: int, budget_window_minutes: int) -> dict:
    """Implementation metadata, not proof of external authorization or hardware readiness."""
    return {
        "contract_version": CONTRACT_VERSION,
        "deployment_mode": "local_single_user",
        "service_platform": sys.platform,
        "features": {
            "paired_device_management": True,
            "conversation_change_cursor": True,
            "single_conversation_per_database": True,
            "daily_mood_entries": True,
            "mood_operation_ledger": True,
            "mood_self_report_suggestions": True,
            "chat_request_id_recovery": True,
            "chat_delivery_targeted_stop": True,
            "in_app_recurring_followups": True,
            "companion_boundaries": True,
            "bounded_followup_contact": True,
            "unified_contact_claim": True,
            "voice_clip_from_assistant_message": sys.platform == "darwin",
            "memory_expected_version_patch": True,
            "memory_expected_version_delete": True,
            "source_preview_confirmation": True,
            "source_individual_revoke": True,
            "action_preview_confirmation": True,
            "in_app_one_time_followups": True,
            "background_push_delivery": False,
            "remote_user_authentication": False,
            "realtime_multi_device_sync": False,
            "phone_system_calendar_adapter": False,
            "rokid_live_adapter": False,
            "eeg_emotion_decoding": False,
            "service_apple_calendar_reminders": sys.platform == "darwin",
            "service_windows_calendar_reminders": sys.platform == "win32",
        },
        "platform_status": {"apple_calendar": "conditions_required" if sys.platform == "darwin" else "platform_unsupported",
                            "apple_reminders": "conditions_required" if sys.platform == "darwin" else "platform_unsupported",
                            "windows_calendar": "conditions_required" if sys.platform == "win32" else "platform_unsupported",
                            "windows_reminders": "conditions_required" if sys.platform == "win32" else "platform_unsupported",
                            "voice_clip": "conditions_required" if sys.platform == "darwin" else "platform_unsupported"},
        "limits": {"chat_text_characters": 4000, "memory_text_characters": 2000,
                   "source_count": 8, "file_count_per_attach": 3,
                   "chat_turns_per_window": chat_budget, "chat_window_minutes": budget_window_minutes},
        "connection_status": "not_probed",
        "limitations": [
            "Capabilities describe implemented code, not source login, hardware or end-to-end acceptance.",
            "CLI, local files and system calendar/reminders execute on the computer running the service, not the phone.",
            "Loopback origin protection is not remote user authentication.",
            "Unknown action or turn results require review; do not silently retry system writes.",
            "Stopping reply delivery requires its current assistant message_id; missing or stale targets do not stop newer replies.",
            "Voice clips require an explicit request and installed platform speech tools/voice; metadata does not probe availability.",
        ],
    }
