package cn.xinji.echo

import java.util.UUID
import org.json.JSONObject

enum class SourceRevokeOutcome { CONFIRMED, UNRESOLVED, OBSOLETE }

/** Bind a single-source approval to its exact local request and origin. */
data class SourceRevocationAttempt(val endpoint: String, val sessionId: String, val source: Source, val token: String = UUID.randomUUID().toString()) {
    fun body() = json("session_id" to sessionId, "source_id" to source.id)
    fun canStart(currentEndpoint: String, current: Conversation?) = source.id.isNotEmpty() && currentEndpoint == endpoint && current?.id == sessionId && current.sources.any { it == source }
    fun isCurrent(currentEndpoint: String, currentSessionId: String?, currentToken: String?) = currentEndpoint == endpoint && currentSessionId == sessionId && currentToken == token
    fun receiptMatches(result: JSONObject?): Boolean {
        if (result == null || result.opt("ok") != true) return false
        if (result.has("session_id") && result.str("session_id") != sessionId) return false
        if (result.str("state") !in setOf("listening", "thinking", "responding", "quiet", "revoked", "failed")) return false
        val ids = result.optJSONArray("revoked_source_ids") ?: return false
        if (ids.length() != 1 || ids.opt(0) != source.id) return false
        return listOf("cleaned", "review_required", "remaining_sources").all { key ->
            val number = result.opt(key) as? Number ?: return@all false
            val value = number.toDouble()
            value.isFinite() && value >= 0 && value % 1.0 == 0.0
        }
    }
    fun outcome(result: JSONObject?, fresh: Conversation?, currentEndpoint: String, currentSessionId: String?, currentToken: String?): SourceRevokeOutcome {
        if (!isCurrent(currentEndpoint, currentSessionId, currentToken)) return SourceRevokeOutcome.OBSOLETE
        if (!receiptMatches(result) || fresh?.id != sessionId || fresh.sources.any { it.id == source.id }) return SourceRevokeOutcome.UNRESOLVED
        return SourceRevokeOutcome.CONFIRMED
    }
}
