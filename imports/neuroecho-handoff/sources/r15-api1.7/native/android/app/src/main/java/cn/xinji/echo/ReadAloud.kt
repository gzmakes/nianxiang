package cn.xinji.echo

import java.util.Locale
import java.util.UUID

/** A local UI snapshot, never a request to the model or the backend voice endpoint. */
data class ReadAloudContext(val endpoint: String, val conversation: Conversation?, val visibleMessageIds: Set<String>, val foreground: Boolean)
data class ReadAloudTarget(val endpoint: String, val sessionId: String, val messageId: String, val visibleText: String, val originalText: String, val originalBubbles: List<String>)
data class LocalSpeechVoice(val name: String, val languageTag: String, val networkRequired: Boolean, val installed: Boolean)

enum class ReadAloudPhase { IDLE, PREPARING, QUEUED, SPEAKING, UNAVAILABLE }
enum class ReadAloudEvent { START, DONE, ERROR, STOP }
enum class ReadAloudUnavailable { INITIALIZATION, NO_LOCAL_VOICE, INPUT_LIMIT, OUTPUT, TIMEOUT, STOP_UNCERTAIN }
data class ReadAloudState(val phase: ReadAloudPhase = ReadAloudPhase.IDLE, val target: ReadAloudTarget? = null, val operationId: String? = null, val utteranceId: String? = null, val unavailable: ReadAloudUnavailable? = null, val stopUncertain: Boolean = false) {
    val active get() = stopUncertain || phase in setOf(ReadAloudPhase.PREPARING, ReadAloudPhase.QUEUED, ReadAloudPhase.SPEAKING)
}

object ReadAloudPolicy {
    fun target(context: ReadAloudContext, messageId: String): ReadAloudTarget? {
        val conversation = context.conversation ?: return null
        if (!context.foreground || context.endpoint.isBlank() || conversation.id.isBlank() || messageId !in context.visibleMessageIds) return null
        val message = conversation.messages.singleOrNull { it.id == messageId } ?: return null
        if (message.id.isBlank() || message.role != "assistant" || message.deliveryPending || !message.deliveryFlagValid) return null
        // Use exactly the parts rendered by the chat UI; never substitute a hidden full body.
        val text = message.displayParts.joinToString("\n\n")
        if (text.isBlank()) return null
        return ReadAloudTarget(context.endpoint, conversation.id, message.id, text, message.text, message.bubbles.toList())
    }
    fun matches(target: ReadAloudTarget, context: ReadAloudContext) = ReadAloudPolicy.target(context, target.messageId) == target
    fun preferredLanguage(text: String, deviceLanguageTag: String): String =
        if (text.codePoints().anyMatch { Character.UnicodeScript.of(it) == Character.UnicodeScript.HAN }) "zh-CN" else deviceLanguageTag
    fun chooseVoice(voices: List<LocalSpeechVoice>, languageTag: String): LocalSpeechVoice? {
        val locale = Locale.forLanguageTag(languageTag)
        if (locale.language.isBlank()) return null
        return voices.filter { it.name.isNotBlank() && !it.networkRequired && it.installed && Locale.forLanguageTag(it.languageTag).language == locale.language }
            .sortedWith(compareBy<LocalSpeechVoice> { if (it.languageTag.equals(languageTag, ignoreCase = true)) 0 else 1 }.thenBy { it.name }).firstOrNull()
    }
    /** Android's limit counts UTF-16 chars. Keep every character and never cut a surrogate pair. */
    fun chunks(text: String, maxChars: Int): List<String> {
        require(maxChars > 0)
        val value = text.trim()
        require(value.isNotEmpty())
        val result = mutableListOf<String>()
        var start = 0
        while (start < value.length) {
            var end = (start.toLong() + maxChars.toLong()).coerceAtMost(value.length.toLong()).toInt()
            if (end < value.length && Character.isHighSurrogate(value[end - 1]) && Character.isLowSurrogate(value[end])) end--
            require(end > start) { "语音引擎无法完整读取这个字符。" }
            if (end < value.length) {
                val boundary = (end - 1 downTo start + (end - start) / 2).firstOrNull { value[it] in "\n。！？.!? " }
                if (boundary != null) end = boundary + 1
            }
            result.add(value.substring(start, end)); start = end
        }
        return result
    }
}

/** Thin platform adapter; implementations must deliver callbacks on the controller's UI thread. */
interface ReadAloudDriver {
    fun initialize(operationId: String, ready: (String, Boolean, List<LocalSpeechVoice>, Int) -> Unit)
    fun speak(operationId: String, utteranceId: String, voice: LocalSpeechVoice, text: String, event: (String, ReadAloudEvent) -> Unit): Boolean
    fun stop(): Boolean
    fun shutdown(): Boolean
}

/** The returned cancellation also needs an identity guard for already-enqueued callbacks. */
fun interface ReadAloudTimer { fun schedule(delayMillis: Long, action: () -> Unit): () -> Unit }
object ReadAloudTimeouts {
    const val INITIALIZATION_MS = 10_000L
    const val QUEUED_MS = 10_000L
    const val MAX_CHUNK_CHARS = 600
    fun playbackMillis(text: String): Long = (15_000L + text.codePointCount(0, text.length).toLong() * 450L).coerceIn(15_000L, 300_000L)
}

/** Pure state machine. No auto-play, persisted speech, network fallback or stale callback adoption. */
class ReadAloudController(
    private val driver: ReadAloudDriver,
    private val context: () -> ReadAloudContext,
    private val timer: ReadAloudTimer,
    private val deviceLanguageTag: () -> String = { Locale.getDefault().toLanguageTag() },
    private val nextId: () -> String = { UUID.randomUUID().toString() },
    private val changed: (ReadAloudState) -> Unit = {}
) {
    var state = ReadAloudState(); private set
    private var closed = false
    private var chunks = emptyList<String>()
    private var chunkIndex = 0
    private var voice: LocalSpeechVoice? = null
    private var cancelTimer: (() -> Unit)? = null
    private var timerGeneration = 0L
    private fun publish(value: ReadAloudState) { state = value; changed(value) }
    private fun clearTimer() { timerGeneration++; runCatching { cancelTimer?.invoke() }; cancelTimer = null }
    private fun release(): Boolean {
        // A failed stop must not be followed by a new engine and overlapping playback.
        if (!runCatching { driver.stop() }.getOrDefault(false)) return false
        return runCatching { driver.shutdown() }.getOrDefault(false)
    }
    fun stop() {
        val target = state.target
        clearTimer(); publish(ReadAloudState()); chunks = emptyList(); voice = null; chunkIndex = 0
        if (!release()) publish(ReadAloudState(ReadAloudPhase.UNAVAILABLE, target, unavailable = ReadAloudUnavailable.STOP_UNCERTAIN, stopUncertain = true))
    }
    fun close() { closed = true; stop() }
    fun refresh() { if (state.stopUncertain) return; state.target?.let { if (!ReadAloudPolicy.matches(it, context())) stop() } }
    private fun current(operationId: String): Boolean {
        if (closed || !state.active || state.operationId != operationId) return false
        val target = state.target ?: return false
        if (!ReadAloudPolicy.matches(target, context())) { stop(); return false }
        return true
    }
    private fun watch(operationId: String, utteranceId: String?, phase: ReadAloudPhase, delay: Long) {
        clearTimer(); val generation = timerGeneration
        cancelTimer = timer.schedule(delay) {
            if (generation != timerGeneration || state.operationId != operationId || state.utteranceId != utteranceId || state.phase != phase) return@schedule
            if (current(operationId)) unavailable(ReadAloudUnavailable.TIMEOUT)
        }
    }
    private fun unavailable(reason: ReadAloudUnavailable = ReadAloudUnavailable.OUTPUT) {
        val target = state.target
        clearTimer(); publish(ReadAloudState(ReadAloudPhase.UNAVAILABLE, target, unavailable = reason)); chunks = emptyList(); voice = null
        if (!release()) publish(ReadAloudState(ReadAloudPhase.UNAVAILABLE, target, unavailable = ReadAloudUnavailable.STOP_UNCERTAIN, stopUncertain = true))
    }
    /** Called only by a message's explicit read button, and revalidates its current UI snapshot. */
    fun play(messageId: String) {
        if (closed) return
        stop()
        if (state.stopUncertain) return
        val target = ReadAloudPolicy.target(context(), messageId) ?: return
        val id = nextId()
        publish(ReadAloudState(ReadAloudPhase.PREPARING, target, id))
        try {
            watch(id, null, ReadAloudPhase.PREPARING, ReadAloudTimeouts.INITIALIZATION_MS)
            driver.initialize(id) { callbackId, success, voices, maxChars ->
                if (callbackId != id || !current(id) || state.phase != ReadAloudPhase.PREPARING) return@initialize
                clearTimer()
                if (!success) { unavailable(ReadAloudUnavailable.INITIALIZATION); return@initialize }
                val selected = ReadAloudPolicy.chooseVoice(voices, ReadAloudPolicy.preferredLanguage(target.visibleText, deviceLanguageTag()))
                if (selected == null) { unavailable(ReadAloudUnavailable.NO_LOCAL_VOICE); return@initialize }
                val pieces = runCatching { ReadAloudPolicy.chunks(target.visibleText, minOf(maxChars, ReadAloudTimeouts.MAX_CHUNK_CHARS)) }.getOrNull()
                if (pieces == null) { unavailable(ReadAloudUnavailable.INPUT_LIMIT); return@initialize }
                chunks = pieces; chunkIndex = 0; voice = selected; nextChunk(id)
            }
        } catch (_: Exception) { if (current(id)) unavailable(ReadAloudUnavailable.INITIALIZATION) }
    }
    private fun nextChunk(operationId: String) {
        if (!current(operationId)) return
        clearTimer()
        if (chunkIndex >= chunks.size) { stop(); return }
        val selected = voice ?: return unavailable()
        val utteranceId = nextId()
        publish(state.copy(phase = ReadAloudPhase.QUEUED, utteranceId = utteranceId))
        try {
            watch(operationId, utteranceId, ReadAloudPhase.QUEUED, ReadAloudTimeouts.QUEUED_MS)
            val accepted = driver.speak(operationId, utteranceId, selected, chunks[chunkIndex]) { callbackId, event ->
                if (!current(operationId) || callbackId != state.utteranceId || callbackId != utteranceId) return@speak
                when (event) {
                    ReadAloudEvent.START -> if (state.phase == ReadAloudPhase.QUEUED) {
                        publish(state.copy(phase = ReadAloudPhase.SPEAKING))
                        watch(operationId, utteranceId, ReadAloudPhase.SPEAKING, ReadAloudTimeouts.playbackMillis(chunks[chunkIndex]))
                    }
                    ReadAloudEvent.DONE -> { chunkIndex++; nextChunk(operationId) }
                    ReadAloudEvent.ERROR -> unavailable()
                    ReadAloudEvent.STOP -> stop()
                }
            }
            if (!accepted && current(operationId) && state.utteranceId == utteranceId) unavailable()
        } catch (_: Exception) { if (current(operationId) && state.utteranceId == utteranceId) unavailable() }
    }
}
