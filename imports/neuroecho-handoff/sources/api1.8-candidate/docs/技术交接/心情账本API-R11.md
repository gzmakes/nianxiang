# R11 Mood mutation ledger — frozen client contract

Additive API1.5.0, feature mood_operation_ledger=true. R10 daily_mood_entries/mood_self_report_suggestions, legacy PUT/DELETE and every F5/chat/CAS/stop API remain. Freeze a new request UUID, exact operation_json string, SHA256(exact UTF8 bytes), operation kind, endpoint and session before network; persist local cancelRequested before sending cancel. R10 pending without ID must remain legacy: never invent ID/hash or claim it can be cancelled.

## Apply
POST /api/mood-operations
{session_id:string,request_id:string,operation_json:string,confirmed:true}
request_id is 8..128 characters matching ^[A-Za-z0-9][A-Za-z0-9._:-]+$. operation_json is at most16384 UTF8 bytes (also at most16384 characters), a strict JSON object, no duplicate keys or nonfinite numbers, no extra/missing fields. Hash includes all original whitespace/escaping/key order; never reserialize an existing frozen string.

save inner exactly {kind:"save",date:"YYYY-MM-DD",expected_updated_at:ISO|null,x:finite[-1,1],y:finite[-1,1],note:string(0..1000 codepoints)}. All fields required. delete inner exactly {kind:"delete",date:"YYYY-MM-DD",expected_updated_at:nonempty exact ISO string}. Date must be valid; booleans or number strings are not coordinates. Version is exact prior token, never computed.

Apply and ledger commit are one SQLite write transaction, no async/running state. Same session/ID/exact raw hash returns its existing terminal receipt without executing again; a changed raw string (including only whitespace) returns HTTP409 error_code:mood_operation_identity_conflict. A previously cancelled raw hash never writes, even if its inner JSON was invalid. Validation failure before any ledger row returns400 invalid_mood_operation (outer shape/confirmed type/missing keys return422; confirmed:false400 confirmation_required). Existing terminal identity can be replayed without revalidating inner payload. Unknown/nonexistent session404.

## Query
GET /api/mood-operations/{request_id}?session_id=<sid>
200 always for a valid existing session, including state:not_found. Cache-Control:no-store. not_found is a current observation, not proof that an earlier apply cannot still arrive; do not resubmit apply automatically.

## Cancel / retire identity
POST /api/mood-operations/{request_id}/cancel
{session_id:string,operation_sha256:lowercase64hex,kind:"save"|"delete",confirmed:true}
No operation_json or date/content needed. Before first apply, transactionally insert a cancelled tombstone bound to the supplied hash/kind. A late same-hash apply returns cancelled without writing; different hash409. Repeat same cancel is idempotent. Existing applied/conflict returns that original terminal receipt: cancellation does not roll back an applied save/delete. A different hash or cancel kind for an existing identity is409 identity_conflict. Cancelling an invalid or never-applied raw JSON hash is allowed to retire that ID.

Once local cancelRequested=true, never issue apply again for that identity, including after relaunch/not_found/network errors: use only GET or the same metadata cancel until terminal. New editing uses an explicit new identity after the terminal state has been reviewed.

## Exact response (all six keys always present, no date/body)
{session_id,request_id,operation_sha256:64hex|null,kind:"save"|"delete"|null,state:"applied"|"conflict"|"cancelled"|"not_found",result_updated_at:ISO|null}
Mutating endpoints return200 for all terminal states including conflict/cancelled; HTTP409 means identity mismatch only, never silently adopt it. Query not_found echoes sid/id and has hash=null,kind=null,result_updated_at=null. Check all echoed identity/hash/kind/state fields strictly; an unknown/missing/mismatched field is UNKNOWN, not success or a reason to resend.

applied save result_updated_at is the issued saved version; applied delete is the exact deleted prior version. conflict result_updated_at is the version observed at the failed CAS (null if absent); it is historical metadata, not a current-state assertion. cancelled result_updated_at=null. GET moods separately to compare the current day/text/coordinates; an old applied receipt does not resurrect content and does not claim that content still exists. cancelled/conflict allows explicit new editing with a fresh ID and a newly reviewed expected version; never auto-retry.

Ledger stores only sid/id/hash/kind/state/result_updated_at/created_at. It never stores date/x/y/note/raw JSON or historical response bodies. Export includes this metadata; deleting a diary row preserves terminal identities, so old apply replay cannot restore it. Deleting the session removes its ledger and all diary rows atomically; later calls for that deleted session404. No model/chat/memory/proactive contact or external-device access is added.
