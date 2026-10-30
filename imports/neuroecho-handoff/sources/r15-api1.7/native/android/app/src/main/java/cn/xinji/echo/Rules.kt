package cn.xinji.echo

import java.net.URI
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.util.UUID
import org.json.JSONObject

/** Pure rules: no Android, network, storage or account side effects. */
object EndpointPolicy {
    const val DEFAULT = "http://127.0.0.1:18787"
    fun validate(input: String, debug: Boolean): String {
        val uri = URI(input.trim().trimEnd('/'))
        require(uri.host != null && uri.userInfo == null && uri.query == null && uri.fragment == null && (uri.path.isNullOrEmpty() || uri.path == "/")) { "填写后端地址，不含账号、路径或参数。" }
        val emulator = uri.host in setOf("10.0.2.2", "127.0.0.1", "localhost")
        require(uri.scheme == "https" || (debug && emulator && uri.scheme == "http")) { "真机后端必须使用 HTTPS；HTTP 仅供 debug 模拟器或 adb 反向转发。" }
        return uri.toString().trimEnd('/')
    }
}
data class PendingTurn(val id: String, val sessionId: String, val text: String, val cancelWanted: Boolean = false, val memoryProposals: Boolean = false, val timeZone: String? = null) {
    fun body() = json("session_id" to sessionId, "text" to text, "request_id" to id, "memory_proposals" to memoryProposals).also { if (timeZone != null) it.put("time_zone", timeZone) }
    fun encode() = json("id" to id, "session_id" to sessionId, "text" to text, "cancel" to cancelWanted, "memory_proposals" to memoryProposals).also { if (timeZone != null) it.put("time_zone", timeZone) }.toString()
    companion object {
        fun new(sessionId: String, text: String, memoryProposals: Boolean = false, timeZone: String = java.time.ZoneId.systemDefault().id) = PendingTurn(UUID.randomUUID().toString(), sessionId, text, memoryProposals = memoryProposals, timeZone = timeZone)
        fun decode(value: String): PendingTurn? = runCatching { val obj = JSONObject(value); PendingTurn(obj.getString("id"), obj.getString("session_id"), obj.getString("text"), obj.opt("cancel") == true, obj.opt("memory_proposals") == true, obj.str("time_zone").ifEmpty { null }) }.getOrNull()
    }
}
enum class ActionRoute { CONFIRM_EXISTING, CHECK_ONLY, INSPECT }
fun actionRoute(status: String) = when (status) {
    "previewed" -> ActionRoute.CONFIRM_EXISTING
    "unknown", "executing" -> ActionRoute.CHECK_ONLY
    else -> ActionRoute.INSPECT
}
fun isDefinitiveBudgetRejection(httpStatus: Int? = null, errorCode: String = "") = httpStatus == 429 || errorCode == "budget_exceeded"
fun mayReturnTextAfterReview(pendingSession: String, currentSession: String, status: String) = pendingSession != currentSession || status == "unknown"
data class SelectedText(val name: String, val text: String, val truncated: Boolean)
object FilePreviewPolicy {
    const val MAX_BYTES = 256 * 1024
    private val extensions = setOf("md", "markdown", "txt", "json", "py", "ts", "js", "csv")
    fun preview(name: String, bytes: ByteArray): SelectedText {
        require(name.length in 1..200 && name.none { it == '/' || it == '\\' || it.code < 32 } && name.substringAfterLast('.').lowercase() in extensions) { "请选择支持的 UTF-8 文本文件。" }
        require(bytes.isNotEmpty() && bytes.size <= MAX_BYTES) { "每份文本需为 1–256 KB。" }
        val text = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString()
        require(text.isNotBlank() && '\u0000' !in text) { "文件为空或不是可用文本。" }
        val count = text.codePointCount(0, text.length)
        return SelectedText(name, text.substring(0, text.offsetByCodePoints(0, minOf(count, 4000))), count > 4000)
    }
}
