package cn.xinji.echo

import java.security.MessageDigest
import java.time.Instant
import java.util.UUID
import org.json.JSONObject

/** Frozen bytes are the identity of one consented diary mutation, never model context. */
data class MoodOperation(val requestId: String, val raw: String, val kind: String) {
    val sha256: String get() = MessageDigest.getInstance("SHA-256").digest(raw.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
    init {
        require(requestId.length in 8..128 && requestId.matches(Regex("^[A-Za-z0-9][A-Za-z0-9._:-]+$")))
        require(kind in listOf("save", "delete") && raw.length <= 16384 && raw.toByteArray(Charsets.UTF_8).size <= 16384)
    }
    fun applyBody(sessionId: String) = json("session_id" to sessionId, "request_id" to requestId, "operation_json" to raw, "confirmed" to true)
    fun cancelBody(sessionId: String) = json("session_id" to sessionId, "operation_sha256" to sha256, "kind" to kind, "confirmed" to true)
    companion object {
        fun capture(draft: MoodDraft, kind: String): MoodOperation {
            require(kind in listOf("save", "delete"))
            val inner = json("kind" to kind, "date" to draft.date, "expected_updated_at" to draft.expectedUpdatedAt)
            if (kind == "save") { draft.validate(); inner.put("x", draft.x).put("y", draft.y).put("note", draft.note) }
            else require(draft.expectedUpdatedAt != null)
            return MoodOperation(UUID.randomUUID().toString(), inner.toString(), kind)
        }
    }
}

data class MoodOperationReceipt(val state: String, val resultUpdatedAt: String?)
fun moodOperationReceipt(obj: JSONObject, sessionId: String, operation: MoodOperation): MoodOperationReceipt {
    require(obj.keys().asSequence().toSet() == setOf("session_id", "request_id", "operation_sha256", "kind", "state", "result_updated_at")) { "提交回执字段不完整，继续保留原请求。" }
    require(obj.opt("session_id") == sessionId && obj.opt("request_id") == operation.requestId) { "回执不属于这次提交。" }
    val state = obj.opt("state") as? String ?: error("回执缺少状态。")
    require(state in listOf("applied", "conflict", "cancelled", "not_found")) { "回执状态尚不能核对。" }
    val token = obj.opt("result_updated_at")
    val version = if (token === JSONObject.NULL) null else token as? String ?: error("回执版本无法核对。")
    require(version == null || runCatching { Instant.parse(version) }.isSuccess)
    if (state == "not_found") {
        require(obj.opt("operation_sha256") === JSONObject.NULL && obj.opt("kind") === JSONObject.NULL && version == null)
    } else {
        require(obj.opt("operation_sha256") == operation.sha256 && obj.opt("kind") == operation.kind) { "回执与原请求内容不同。" }
        if (state == "applied") {
            require(version != null) { "执行回执缺少版本。" }
            val expected = JSONObject(operation.raw).opt("expected_updated_at")
            require(if (operation.kind == "delete") version == expected else version != expected) { "执行回执版本与原请求不一致。" }
        }
        if (state == "cancelled") require(version == null)
    }
    return MoodOperationReceipt(state, version)
}

/** Only a terminal receipt plus a separate current GET can unlock the frozen request. */
fun MoodDraft.afterLedgerReceipt(receipt: MoodOperationReceipt, current: MoodRecord?): MoodDraft {
    require(ledgerOperation() != null)
    if (receipt.state == "not_found") return this // a late apply may still arrive
    if (receipt.state == "applied" && operation == "save" && matches(current) && current?.updatedAt == receipt.resultUpdatedAt)
        return MoodDraft.from(sessionId, date, current)
    if (receipt.state == "applied" && operation == "delete") {
        require(receipt.resultUpdatedAt == expectedUpdatedAt) { "删除回执与原版本不一致。" }
        if (current == null) return MoodDraft.from(sessionId, date, null)
    }
    // A cancelled/conflicted identity is retired. Keep the user's text for explicit fresh-version review.
    return copy(operation = null, operationId = null, operationJson = null, cancelRequested = false, conflict = true, dirty = true)
}
