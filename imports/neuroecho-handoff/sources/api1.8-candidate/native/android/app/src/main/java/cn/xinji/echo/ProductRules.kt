package cn.xinji.echo

import org.json.JSONObject
import cn.xinji.echo.shared.EchoSharedReference as Shared

data class Comfort(val reduceMotion: Boolean = Shared.DEFAULT_REDUCE_MOTION, val reduceTransparency: Boolean = Shared.DEFAULT_REDUCE_TRANSPARENCY, val lightIntensity: Float = Shared.DEFAULT_LIGHT_INTENSITY)

enum class SearchKind { MESSAGE, MEMORY }
data class SearchHit(val id: String, val kind: SearchKind, val text: String, val label: String)
fun searchConversation(conversation: Conversation?, query: String): List<SearchHit> {
    val term = query.trim()
    if (term.isEmpty() || conversation == null) return emptyList()
    return (conversation.messages.map { SearchHit(it.id, SearchKind.MESSAGE, it.text, if (it.role == "user") "你说过" else "回响") } +
        conversation.memories.filter { it.status != "deleted" }.map { SearchHit(it.id, SearchKind.MEMORY, it.text, if (it.status == "confirmed") "已确认记忆" else "待确认记忆") })
        .filter { it.text.contains(term, ignoreCase = true) }.take(60)
}

/** A topic is a device-only view; assigning one never creates a conversation. */
object TopicPolicy {
    fun label(assignments: Map<String, String>, id: String) = assignments[id] ?: "日常"
    fun labels(assignments: Map<String, String>) = listOf("全部", "日常") + assignments.values.filter { it != "日常" }.distinct().sorted()
    fun matches(assignments: Map<String, String>, id: String, selected: String) = selected == "全部" || label(assignments, id) == selected
    fun assign(assignments: Map<String, String>, id: String, input: String): Map<String, String> {
        val name = input.trim()
        require(id.isNotBlank() && !id.startsWith("local-") && name.isNotBlank() && name != "全部" && name.codePointCount(0, name.length) <= 20) { "话题填写 1–20 字，不能使用「全部」。" }
        return assignments + (id to name)
    }
    fun decode(value: String): Map<String, String> = runCatching {
        val json = JSONObject(value)
        json.keys().asSequence().mapNotNull { id -> runCatching { id to json.getString(id) }.getOrNull() }
            .filter { (id, name) -> id.isNotBlank() && name.isNotBlank() && name != "全部" && name.codePointCount(0, name.length) <= 20 }.toMap()
    }.getOrDefault(emptyMap())
}

data class SourceRequest(val path: String, val body: JSONObject)
fun memoryPatchRequest(memory: Memory, text: String? = null, confirm: Boolean = false): SourceRequest {
    val body = json("expected_version" to memory.version)
    if (text != null) body.put("text", text)
    if (confirm) body.put("status", "confirmed")
    return SourceRequest("/api/memory/${encoded(memory.id)}", body)
}
fun memoryDeletePath(memory: Memory) = "/api/memory/${encoded(memory.id)}?expected_version=${memory.version}"
object SourcePolicy {
    val supported = setOf("feishu", "notion", "git", "github", "apple_calendar", "apple_reminders")
    fun mayPreview(id: String, status: String, target: String): Boolean = when {
        id !in supported -> false
        id == "git" -> status in setOf("ready", "needs_config") && (target.startsWith("/") || target.startsWith("~/")) && '\u0000' !in target
        id == "notion" -> status in setOf("ready", "needs_config") && target.startsWith("https://")
        id == "feishu" -> status == "ready" && target.startsWith("https://")
        else -> status == "ready"
    }
    fun preview(id: String, target: String): SourceRequest = when (id) {
        "feishu" -> SourceRequest("/api/lark/preview", json("url" to target))
        "notion" -> SourceRequest("/api/notion/preview", json("url" to target, "method" to "cli"))
        "git" -> SourceRequest("/api/onboarding/real/read", json("source_id" to id, "path" to target))
        else -> { require(id in supported); SourceRequest("/api/onboarding/real/read", json("source_id" to id)) }
    }
    fun attach(id: String, target: String, previewId: String, sid: String): SourceRequest = when (id) {
        "feishu" -> SourceRequest("/api/lark/attach", json("url" to target, "preview_id" to previewId, "session_id" to sid))
        "notion" -> SourceRequest("/api/notion/start", json("preview_id" to previewId, "session_id" to sid))
        else -> { require(id in supported); SourceRequest("/api/onboarding/real/start", json("source_id" to id, "preview_id" to previewId, "session_id" to sid)) }
    }
}

/** The edited text and original version survive a refresh or a 409. */
data class MemoryDraft(val id: String? = null, val text: String = "", val kind: String = "fact", val expectedVersion: Int? = null, val serverText: String? = null, val serverVersion: Int? = null, val conflict: Boolean = false, val uncertain: Boolean = false, val sessionId: String = "") {
    fun withConflict(current: Memory?) = copy(serverText = current?.text, serverVersion = current?.version, conflict = true)
    fun rebase(): MemoryDraft { require(conflict && serverVersion != null) { "这条记忆已不存在，保留草稿后关闭即可。" }; return copy(expectedVersion = serverVersion, serverText = null, serverVersion = null, conflict = false) }
    fun encode() = json("id" to id, "text" to text, "kind" to kind, "expected_version" to expectedVersion, "conflict" to conflict, "uncertain" to uncertain, "server_text" to serverText, "server_version" to serverVersion, "session_id" to sessionId).toString()
    companion object {
        fun editing(memory: Memory) = MemoryDraft(memory.id, memory.text, memory.kind, memory.version)
        fun decode(value: String): MemoryDraft? = runCatching { val obj = JSONObject(value); MemoryDraft(obj.str("id").ifEmpty { null }, obj.str("text"), obj.str("kind", "fact"), if (obj.isNull("expected_version")) null else obj.optInt("expected_version"), obj.str("server_text").ifEmpty { null }, if (obj.isNull("server_version")) null else obj.optInt("server_version"), obj.optBoolean("conflict"), obj.optBoolean("uncertain"), obj.str("session_id")) }.getOrNull()
    }
}

fun presenceLabel(pending: PendingTurn?, busy: Boolean, draft: String, chatSending: Boolean = false) = when {
    pending?.cancelWanted == true -> "正在核对停止请求"
    pending != null && chatSending -> "正在整理回复"
    pending != null -> "发送结果待核对"
    draft.isNotBlank() -> "在听你说"
    busy -> "正在核对资料"
    else -> Shared.COPY_STATE_QUIET
}

/** Targeted delivery stop is separate from cancelling model generation. */
data class DeliveryStopAttempt(val endpoint: String, val sessionId: String, val messageId: String) {
    fun canStart(supported: Boolean, currentEndpoint: String, current: Conversation?): Boolean =
        supported && endpoint == currentEndpoint && sessionId == current?.id && messageId.isNotBlank() &&
            current.messages.lastOrNull()?.let { it.role == "assistant" && it.deliveryPending && it.id == messageId } == true
    fun request() = SourceRequest("/api/session/${encoded(sessionId)}/delivery/stop", json("message_id" to messageId))
    fun receiptMatches(value: JSONObject?): Boolean = value?.opt("ok") == true && value.opt("stopped") == true &&
        value.opt("message_id") == messageId && value.opt("reason") == "stopped"
    fun reconciled(value: JSONObject?, fresh: Conversation?): Boolean = receiptMatches(value) && fresh?.id == sessionId &&
        fresh.messages.any { it.id == messageId && it.role == "assistant" && !it.deliveryPending } &&
        fresh.messages.none { it.id != messageId && it.role == "assistant" && it.deliveryPending }
}

/** Both automatic offers and 409 fallback stay local until another explicit choice. */
data class QuoteMemoryReview(val sessionId: String, val messageId: String, val text: String) {
    fun matches(current: Conversation?) = current?.id == sessionId && current.messages.any { it.id == messageId && it.role == "user" && it.text == text }
    fun candidate(current: Conversation?): MemoryDraft { require(matches(current)) { "原话已变化，请先刷新核对。" }; return MemoryDraft(text = text, sessionId = sessionId) }
}
fun quoteReview(message: Message, current: Conversation?): QuoteMemoryReview? = current?.let { c ->
    QuoteMemoryReview(c.id, message.id, message.text).takeIf { message.role == "user" && message.id.isNotBlank() && message.text.isNotBlank() && it.matches(c) }
}
fun quoteReviewAfterRejection(message: Message, current: Conversation?, status: Int) = if (status == 409) quoteReview(message, current) else null
fun quoteRequest(review: QuoteMemoryReview) = SourceRequest("/api/memory/proposal", json("session_id" to review.sessionId, "message_id" to review.messageId, "confirm" to true))
fun quoteReceiptMatches(review: QuoteMemoryReview, saved: Memory) = saved.id.isNotBlank() && saved.status == "confirmed" && saved.kind == "fact" && saved.source == "对话原话 · 用户选存" && saved.sourceMessageId == review.messageId && saved.text == review.text.trim().trimEnd('。')
fun quoteOffer(result: JSONObject, turn: PendingTurn, current: Conversation?): QuoteMemoryReview? {
    if (!turn.memoryProposals || current?.id != turn.sessionId) return null
    val offer = result.optJSONObject("memory_proposal") ?: return null
    val message = current.messages.find { it.id == offer.str("message_id") } ?: return null
    if (result.str("user_message_id") != message.id || message.text != turn.text) return null
    val review = quoteReview(message, current) ?: return null
    return review.takeIf { it.text.trim().trimEnd('。') == offer.str("quote") && offer.str("quote").isNotBlank() }
}
fun manualMemoryRequest(draft: MemoryDraft, sid: String) = SourceRequest("/api/memory", json("session_id" to sid, "kind" to draft.kind, "text" to draft.text, "source" to "用户手动添加"))
