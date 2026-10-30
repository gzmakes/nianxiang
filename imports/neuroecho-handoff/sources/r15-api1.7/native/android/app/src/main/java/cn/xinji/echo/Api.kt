package cn.xinji.echo

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

fun JSONArray.objects(): List<JSONObject> = (0 until length()).mapNotNull { optJSONObject(it) }
fun JSONObject.rows(key: String) = optJSONArray(key)?.objects().orEmpty()
fun JSONObject.str(key: String, fallback: String = "") = if (isNull(key)) fallback else optString(key, fallback)
fun json(vararg pairs: Pair<String, Any?>) = JSONObject().also { obj -> pairs.forEach { (key, value) -> obj.put(key, value ?: JSONObject.NULL) } }
fun encoded(value: String): String = URLEncoder.encode(value, "UTF-8")
data class Message(val id: String, val role: String, val text: String, val createdAt: String = "", val bubbles: List<String> = emptyList(), val deliveryPending: Boolean = false, val deliveryNextMs: Long = 800, val deliveryFlagValid: Boolean = true) {
    val displayParts: List<String> get() = if (role == "assistant" && bubbles.isNotEmpty()) bubbles else listOf(text)
}
data class Memory(val id: String, val text: String, val kind: String, val status: String, val version: Int, val source: String, val createdAt: String, val sourceMessageId: String = "", val sourceAttachmentId: String = "")
data class Source(val id: String, val title: String, val label: String, val stale: Boolean)
data class SavedAction(val id: String, val sessionId: String, val kind: String, val title: String, val detail: String, val whenText: String, val status: String, val real: Boolean, val receipt: String)
data class Conversation(val id: String, val messages: List<Message>, val memories: List<Memory>, val sources: List<Source>, val bookmark: String = "", val bookmarkNext: String = "")
fun messages(obj: JSONObject) = obj.rows("messages").map { item ->
    val parts = item.optJSONArray("bubbles")?.let { list -> (0 until list.length()).mapNotNull { i -> (list.opt(i) as? String)?.takeIf { it.isNotEmpty() } } }.orEmpty()
    Message(item.str("id"), item.str("role"), item.str("text"), item.str("created_at"), parts, item.optBoolean("delivery_pending"), item.optLong("delivery_next_ms", 800).coerceIn(100, 2000), !item.has("delivery_pending") || item.opt("delivery_pending") is Boolean)
}
fun memory(obj: JSONObject) = Memory(obj.str("id"), obj.str("text"), obj.str("kind"), obj.str("status"), obj.optInt("version", 1), obj.str("source"), obj.str("created_at"), obj.str("source_message_id"), obj.str("source_attachment_id"))
fun memories(obj: JSONObject) = obj.rows("memories").map(::memory)
fun conversation(obj: JSONObject): Conversation {
    val id = obj.getJSONObject("session").getString("id")
    val sources = obj.optJSONObject("context")?.rows("sources").orEmpty().map { Source(it.str("id"), it.str("title", it.str("label")), it.str("label"), it.optBoolean("stale")) }
    val bookmark = obj.optJSONObject("bookmark")
    return Conversation(id, messages(obj), memories(obj), sources, bookmark?.str("note").orEmpty(), bookmark?.str("next_step").orEmpty())
}
fun savedActions(obj: JSONObject) = obj.rows("actions").map { SavedAction(it.str("id"), it.str("session_id"), it.str("kind"), it.str("title"), it.str("detail"), it.str("when_text"), it.str("status"), it.optInt("real") == 1, it.str("receipt")) }
class ApiError(val status: Int, message: String, val code: String = "", val currentVersion: Int? = null) : Exception(message)

/** Immutable authorization is bound to one HTTPS origin and one service instance. */
data class DeviceAuthorization(val token: String, val serviceInstanceId: String? = null)
/** Native HTTP, no WebView or shell bridge; never receives a model key. */
class EchoApi(private val base: String, private val authorization: DeviceAuthorization? = null,
    private val requireCurrent: () -> Unit = {}, private val onInvalidCredential: (ApiError) -> Unit = {},
    private val connectTimeoutMs: Int = 15_000, private val readTimeoutMs: Int = 70_000) {
    init { if (authorization != null) { require(PairingPolicy.origin(base) == base); require(PairingPolicy.validToken(authorization.token)); authorization.serviceInstanceId?.let { require(it.isNotBlank() && it.length <= 200 && it.none(Char::isISOControl)) } } }
    suspend fun call(method: String, path: String, body: JSONObject? = null): JSONObject {
        require(path.startsWith("/api/") && !path.startsWith("//") && '\r' !in path && '\n' !in path)
        requireCurrent()
        try {
            val response = withContext(Dispatchers.IO) {
                requireCurrent()
                val connection = URL(base + path).openConnection() as HttpURLConnection
                try {
                    connection.requestMethod = method
                    connection.connectTimeout = connectTimeoutMs
                    connection.readTimeout = readTimeoutMs
                    connection.instanceFollowRedirects = false
                    connection.useCaches = false
                    connection.setRequestProperty("Cache-Control", "no-store")
                    connection.setRequestProperty("Accept", "application/json")
                    authorization?.let { auth ->
                        connection.setRequestProperty("Authorization", "Bearer " + auth.token)
                        auth.serviceInstanceId?.let { connection.setRequestProperty("X-Echo-Service-Instance", it) }
                    }
                    if (body != null) {
                        connection.doOutput = true
                        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                        connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
                    }
                    val status = connection.responseCode
                    val stream = if (status in 200..299) connection.inputStream else connection.errorStream
                    val text = stream?.bufferedReader(Charsets.UTF_8)?.use { reader ->
                        val out = StringBuilder(); val buffer = CharArray(8192)
                        while (true) { val count = reader.read(buffer); if (count < 0) break; check(out.length + count <= 16 * 1024 * 1024) { "服务回复过大；请在电脑核对。" }; out.append(buffer, 0, count) }
                        out.toString()
                    }.orEmpty()
                    val result = runCatching { JSONObject(text) }.getOrElse { JSONObject() }
                    if (status !in 200..299) throw ApiError(status, result.str("detail", "服务暂时不可达（$status）。"), result.str("error_code"), if (result.has("current_version")) result.optInt("current_version") else null)
                    result
                } finally { connection.disconnect() }
            }
            requireCurrent()
            return response
        } catch (error: ApiError) {
            requireCurrent()
            if (authorization != null && PairingPolicy.invalidates(error)) onInvalidCredential(error)
            throw error
        }
    }
    suspend fun get(path: String) = call("GET", path)
    suspend fun post(path: String, body: JSONObject = JSONObject()) = call("POST", path, body)
    suspend fun put(path: String, body: JSONObject) = call("PUT", path, body)
}
