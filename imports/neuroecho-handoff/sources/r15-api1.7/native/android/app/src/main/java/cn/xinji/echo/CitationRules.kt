package cn.xinji.echo

import org.json.JSONArray
import java.net.URI

sealed interface MessageCitation
data class FeishuDocumentCitation(val title: String, val url: String, val text: String) : MessageCitation
/** Preserve legacy provenance without introducing a memory-editing route. */
data class MemoryCitation(val id: String, val version: Long, val text: String) : MessageCitation

data class CitationContext(val endpoint: String, val dataContextId: String, val conversation: Conversation?, val visibleMessageIds: Set<String>, val foreground: Boolean)
data class DocumentCitationTarget(val endpoint: String, val dataContextId: String, val sessionId: String, val messageId: String, val visibleText: String, val document: FeishuDocumentCitation)

/** Source buttons are local navigation only: no CLI, authorization, body fetch or device Bearer. */
object CitationPolicy {
    private val authority = Regex("(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\\.)*(?:feishu\\.cn|larksuite\\.com)(?::443)?", RegexOption.IGNORE_CASE)
    private val path = Regex("/(?:docx|docs|wiki)/[A-Za-z0-9_-]+/?")
    private val encodedUnsafe = Regex("%(?:0[0-9a-f]|1[0-9a-f]|7f|5c)|%c2%(?:8[0-9a-f]|9[0-9a-f])", RegexOption.IGNORE_CASE)
    private fun validTitle(value: String) = value.isNotBlank() && value.codePointCount(0, value.length) <= 500

    fun documentURL(value: String): String? {
        if (value.isEmpty() || value.toByteArray(Charsets.UTF_8).size > 4096 || value.any { it.isWhitespace() || Character.isSpaceChar(it) || it.isISOControl() || it == '\\' } || encodedUnsafe.containsMatchIn(value)) return null
        val uri = runCatching { URI(value) }.getOrNull() ?: return null
        val rawAuthority = uri.rawAuthority ?: return null
        if (!uri.scheme.equals("https", ignoreCase = true) || uri.isOpaque || uri.rawUserInfo != null || rawAuthority.any { it.code > 127 } || !authority.matches(rawAuthority)) return null
        if (uri.host == null || uri.host.length > 253 || uri.port !in setOf(-1, 443) || !path.matches(uri.rawPath.orEmpty())) return null
        return value
    }

    /** Inspect actual JSON types; a malformed item cannot discard the containing reply. */
    fun parse(items: JSONArray?): List<MessageCitation> = if (items == null) emptyList() else (0 until items.length()).mapNotNull { index ->
        val item = items.optJSONObject(index) ?: return@mapNotNull null
        if (item.has("kind")) {
            if (item.opt("kind") != "feishu_document") return@mapNotNull null
            val title = item.opt("title") as? String ?: return@mapNotNull null
            val url = item.opt("url") as? String ?: return@mapNotNull null
            val text = item.opt("text") as? String ?: return@mapNotNull null
            if (!validTitle(title) || documentURL(url) == null) return@mapNotNull null
            FeishuDocumentCitation(title, url, text)
        } else {
            val id = (item.opt("id") as? String)?.takeIf { it.isNotBlank() } ?: return@mapNotNull null
            val version = when (val value = item.opt("version")) { is Int -> value.toLong(); is Long -> value; else -> return@mapNotNull null }
            val text = item.opt("text") as? String ?: return@mapNotNull null
            if (version <= 0) return@mapNotNull null
            MemoryCitation(id, version, text)
        }
    }

    fun targets(context: CitationContext, messageId: String): List<DocumentCitationTarget> {
        val conversation = context.conversation ?: return emptyList()
        if (!context.foreground || context.endpoint.isBlank() || context.dataContextId.isBlank() || conversation.id.isBlank() || messageId !in context.visibleMessageIds) return emptyList()
        val message = conversation.messages.singleOrNull { it.id == messageId } ?: return emptyList()
        if (message.id.isBlank() || message.role != "assistant" || message.deliveryPending || !message.deliveryFlagValid) return emptyList()
        val visibleText = message.displayParts.joinToString("\n\n")
        if (visibleText.isBlank()) return emptyList()
        return message.citations.filterIsInstance<FeishuDocumentCitation>().filter { validTitle(it.title) && documentURL(it.url) != null }.map {
            DocumentCitationTarget(context.endpoint, context.dataContextId, conversation.id, message.id, visibleText, it)
        }
    }

    /** Re-read the current connection, topic visibility, completed message and exact document at click. */
    fun urlForOpen(target: DocumentCitationTarget, context: CitationContext): String? =
        if (target in targets(context, target.messageId)) documentURL(target.document.url) else null
}
