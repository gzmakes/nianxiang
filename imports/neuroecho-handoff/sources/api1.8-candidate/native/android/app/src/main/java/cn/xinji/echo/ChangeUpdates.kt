package cn.xinji.echo

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withTimeout
import org.json.JSONObject

/** Opaque invalidations only. No cursor decoding, writes, replay, or local draft merging. */
object ChangePolicy {
    val domains = setOf("conversation", "messages", "memories", "sources", "moods", "followups", "boundary", "actions", "turns")
    fun cursor(value: String) = value.length in 1..2048 && value.matches(Regex("[A-Za-z0-9_-]+"))
}
data class ChangeReceipt(val service: String, val conversationId: String, val cursor: String, val reset: Boolean, val domains: List<String>, val reason: String?) {
    val supported get() = domains.all { it in ChangePolicy.domains }
    fun stableAt(candidate: ChangeReceipt) = service == candidate.service && conversationId == candidate.conversationId && cursor == candidate.cursor && !reset && domains.isEmpty() && reason == null
}
fun changeReceipt(obj: JSONObject): ChangeReceipt {
    require(listOf("service_instance_id", "conversation_id", "cursor", "reset_required", "domains", "reset_reason").all { obj.has(it) })
    fun string(key: String) = (obj.opt(key) as? String)?.takeIf { it.isNotBlank() && it.length <= 200 && it.none(Char::isISOControl) } ?: error("更新身份尚不能核对。")
    val cursor = obj.opt("cursor") as? String ?: error("更新标记缺失。")
    require(ChangePolicy.cursor(cursor))
    val reset = obj.opt("reset_required") as? Boolean ?: error("更新状态尚不能核对。")
    val reason = if (obj.isNull("reset_reason")) null else obj.opt("reset_reason") as? String ?: error("更新原因无效。")
    require(if (reset) reason in setOf("initial", "identity_changed", "too_old", "ahead") else reason == null)
    val array = obj.optJSONArray("domains") ?: error("更新范围缺失。")
    val domains = (0 until array.length()).map { (array.opt(it) as? String)?.takeIf { d -> d.isNotBlank() && d.length <= 100 } ?: error("更新范围无效。") }
    require(domains.distinct().size == domains.size && (!reset || domains.containsAll(ChangePolicy.domains)))
    return ChangeReceipt(string("service_instance_id"), string("conversation_id"), cursor, reset, domains, reason)
}
enum class UpdateStatus { IDLE, CHECKING, PENDING, UPDATED, OFFLINE, UNSUPPORTED, IDENTITY_CHANGED }
data class UpdateContext(val scope: String, val conversationId: String, val service: String?, val foreground: Boolean,
    val blocked: Boolean, val supported: Boolean, val revision: Any, val moods: Boolean = false,
    val followups: Boolean = false, val boundary: Boolean = false, val localActions: Boolean = false)
data class UpdateSnapshot(val conversation: Conversation, val moods: List<MoodRecord>?, val followups: List<Followup>?, val boundary: CompanionBoundary?, val actions: List<SavedAction>?, val nextStep: String?)

/** Main-thread coordinator; injectable clock/transport and a single atomic publish boundary. */
class ChangeCoordinator(private val context: () -> UpdateContext?, private val now: () -> Long,
    private val publish: (UpdateContext, UpdateSnapshot) -> Boolean, private val status: (UpdateStatus) -> Unit) {
    var cursor: String? = null; private set
    private var service: String? = null
    private var scope: String? = null
    private var attempt = 0L
    private var inFlight: Long? = null
    private var nextAt = 0L
    private var failures = 0
    private var identityBlocked = false
    /** Invalidates callbacks immediately; the old transport may still be unwinding. */
    private fun invalidate() { attempt++; inFlight = null; cursor = null; service = null; scope = null; nextAt = 0; failures = 0; identityBlocked = false }
    fun background() { attempt++; nextAt = 0 }
    private fun same(start: UpdateContext, token: Long, includeRevision: Boolean = false): Boolean {
        val current = context() ?: return false
        return inFlight == token && attempt == token && current.foreground && current.scope == start.scope && current.conversationId == start.conversationId && current.service == start.service && (!includeRevision || (!current.blocked && current.revision == start.revision))
    }
    suspend fun poll(get: suspend (String) -> JSONObject, force: Boolean = false) {
        val start = context() ?: return
        if (!start.foreground || inFlight != null) return
        if (scope != start.scope) { invalidate(); scope = start.scope }
        if (!start.supported) { status(UpdateStatus.UNSUPPORTED); return }
        if (identityBlocked || (!force && now() < nextAt)) return
        val token = ++attempt; inFlight = token
        nextAt = now() + 10_000
        status(UpdateStatus.CHECKING)
        try {
            withTimeout(25_000) {
                val candidate = changeReceipt(get("/api/conversation/changes" + (cursor?.let { "?after=" + encoded(it) } ?: "")))
                if (!same(start, token)) return@withTimeout
                if (candidate.conversationId != start.conversationId || candidate.service != (start.service ?: service ?: candidate.service) || candidate.reason == "identity_changed") {
                    identityBlocked = true; status(UpdateStatus.IDENTITY_CHANGED); return@withTimeout
                }
                if (!candidate.supported) { status(UpdateStatus.UNSUPPORTED); return@withTimeout }
                if (!candidate.reset && candidate.domains.isEmpty() && cursor == candidate.cursor) { failures = 0; status(UpdateStatus.IDLE); return@withTimeout }
                if (!same(start, token, true)) { status(UpdateStatus.PENDING); return@withTimeout }
                val snapshot = readSnapshot(start, get)
                if (!same(start, token, true)) { if (same(start, token)) status(UpdateStatus.PENDING); return@withTimeout }
                val checked = changeReceipt(get("/api/conversation/changes?after=" + encoded(candidate.cursor)))
                if (!same(start, token, true)) { if (same(start, token)) status(UpdateStatus.PENDING); return@withTimeout }
                if (checked.service != candidate.service || checked.conversationId != candidate.conversationId || checked.reason == "identity_changed") {
                    identityBlocked = true; status(UpdateStatus.IDENTITY_CHANGED); return@withTimeout
                }
                if (!checked.supported || !checked.stableAt(candidate)) { status(UpdateStatus.PENDING); return@withTimeout }
                if (publish(start, snapshot)) {
                    cursor = candidate.cursor; service = candidate.service; failures = 0; status(UpdateStatus.UPDATED)
                } else status(UpdateStatus.PENDING)
            }
        } catch (error: Exception) {
            if (same(start, token)) {
                failures = (failures + 1).coerceAtMost(4)
                nextAt = now() + minOf(60_000L, 10_000L * (1L shl failures))
                status(if (error is ApiError && error.status == 403) UpdateStatus.UNSUPPORTED else UpdateStatus.OFFLINE)
            }
            if (error is CancellationException && error !is kotlinx.coroutines.TimeoutCancellationException) throw error
        } finally { if (inFlight == token) inFlight = null }
    }
}
private fun checkedRows(obj: JSONObject, key: String): List<JSONObject> {
    val rows = obj.optJSONArray(key) ?: error("更新列表不完整。")
    return (0 until rows.length()).map { rows.optJSONObject(it) ?: error("更新条目格式无效。") }
}
private fun distinctIds(ids: List<String>) { require(ids.all { it.isNotBlank() } && ids.distinct().size == ids.size) }
/** Full replacement reads. Absence/malformed collections must never look like deletion. */
suspend fun readSnapshot(plan: UpdateContext, get: suspend (String) -> JSONObject): UpdateSnapshot {
    val raw = get("/api/conversation")
    require(raw.optJSONArray("messages") != null && raw.optJSONArray("memories") != null && raw.has("context") && (raw.isNull("context") || raw.optJSONObject("context")?.optJSONArray("sources") != null))
    checkedRows(raw, "messages").forEach { require(it.opt("id") is String && it.opt("role") is String && it.opt("text") is String) }
    checkedRows(raw, "memories").forEach { require(it.opt("id") is String && it.opt("text") is String) }
    if (!raw.isNull("context")) checkedRows(raw.getJSONObject("context"), "sources")
    val conversation = conversation(raw)
    require(conversation.id == plan.conversationId)
    distinctIds(conversation.messages.map { it.id }); distinctIds(conversation.memories.map { it.id }); distinctIds(conversation.sources.map { it.id })
    val sid = encoded(plan.conversationId)
    val moods = if (plan.moods) moodRecords(get("/api/moods?session_id=$sid")) else null
    val followups = if (plan.followups) {
        val response = get("/api/followups?session_id=$sid"); checkedRows(response, "followups")
        followups(response).also { require(it.all { row -> row.sessionId == plan.conversationId }); distinctIds(it.map { row -> row.id }) }
    } else null
    val boundary = if (plan.boundary) companionBoundary(get("/api/companion-boundary?session_id=$sid")) else null
    val actions = if (plan.localActions) {
        val response = get("/api/actions?session_id=$sid"); checkedRows(response, "actions")
        savedActions(response).also { require(it.all { row -> row.sessionId == plan.conversationId }); distinctIds(it.map { row -> row.id }) }
    } else null
    val next = if (plan.localActions) get("/api/next-step?session_id=$sid").str("step") else null
    return UpdateSnapshot(conversation, moods, followups, boundary, actions, next)
}
