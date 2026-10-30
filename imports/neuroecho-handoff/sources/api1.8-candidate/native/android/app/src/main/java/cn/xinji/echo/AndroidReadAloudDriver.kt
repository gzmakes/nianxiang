package cn.xinji.echo

import android.content.Context
import android.media.AudioAttributes
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.speech.tts.Voice

/** Only installed offline voices; never calls setLanguage, install/check-data intents or a server. */
class AndroidReadAloudDriver(context: Context) : ReadAloudDriver {
    // Main-thread process latch: a new Activity/driver must first resolve a failed stop.
    private companion object { var unresolvedEngine: TextToSpeech? = null }
    private val application = context.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private var engine: TextToSpeech? = unresolvedEngine
    private var operationId: String? = null
    private var utteranceId: String? = null
    private var mayHaveAudio = engine != null
    private var onEvent: ((String, ReadAloudEvent) -> Unit)? = null
    private fun installedOffline(tts: TextToSpeech, voice: Voice): Boolean =
        !voice.isNetworkConnectionRequired && voice.features != null &&
            TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED !in voice.features &&
            tts.isLanguageAvailable(voice.locale) >= TextToSpeech.LANG_AVAILABLE

    override fun initialize(operationId: String, ready: (String, Boolean, List<LocalSpeechVoice>, Int) -> Unit) {
        if (engine == null && unresolvedEngine != null) { engine = unresolvedEngine; mayHaveAudio = true }
        if (engine != null) { main.post { ready(operationId, false, emptyList(), 0) }; return }
        this.operationId = operationId
        try {
            // Always post: OnInit can be called before the constructor has returned on failure.
            engine = TextToSpeech(application) { status -> main.post {
                val current = engine
                if (this.operationId != operationId || current == null) return@post
                if (status != TextToSpeech.SUCCESS) { ready(operationId, false, emptyList(), 0); return@post }
                val voices = runCatching { current.voices.orEmpty().map { voice ->
                    LocalSpeechVoice(voice.name, voice.locale.toLanguageTag(), voice.isNetworkConnectionRequired, installedOffline(current, voice))
                } }.getOrDefault(emptyList())
                ready(operationId, true, voices, TextToSpeech.getMaxSpeechInputLength())
            } }
        } catch (_: Exception) { main.post { if (this.operationId == operationId) ready(operationId, false, emptyList(), 0) } }
    }
    override fun speak(operationId: String, utteranceId: String, voice: LocalSpeechVoice, text: String, event: (String, ReadAloudEvent) -> Unit): Boolean {
        val current = engine ?: return false
        if (this.operationId != operationId || voice.networkRequired || !voice.installed) return false
        return runCatching {
            // Recheck the actual engine on every chunk, before setVoice can trigger a data download.
            val actual = current.voices.orEmpty().singleOrNull { it.name == voice.name && it.locale.toLanguageTag() == voice.languageTag && installedOffline(current, it) } ?: return false
            if (current.setVoice(actual) != TextToSpeech.SUCCESS) return false
            val selected = current.voice ?: return false
            if (selected.name != actual.name || selected.locale != actual.locale || !installedOffline(current, selected)) return false
            this.utteranceId = utteranceId; onEvent = event
            fun emit(id: String?, value: ReadAloudEvent) {
                if (id == null) return
                main.post { if (this.operationId == operationId && this.utteranceId == id) {
                    if (value == ReadAloudEvent.DONE || value == ReadAloudEvent.STOP) mayHaveAudio = false
                    onEvent?.invoke(id, value)
                } }
            }
            if (current.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(id: String?) = emit(id, ReadAloudEvent.START)
                override fun onDone(id: String?) = emit(id, ReadAloudEvent.DONE)
                @Deprecated("Android callback retained for older engines")
                override fun onError(id: String?) = emit(id, ReadAloudEvent.ERROR)
                override fun onError(id: String?, errorCode: Int) = emit(id, ReadAloudEvent.ERROR)
                override fun onStop(id: String?, interrupted: Boolean) = emit(id, ReadAloudEvent.STOP)
            }) != TextToSpeech.SUCCESS) return false
            current.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            mayHaveAudio = true
            current.speak(text, TextToSpeech.QUEUE_FLUSH, Bundle(), utteranceId) == TextToSpeech.SUCCESS
        }.getOrDefault(false)
    }
    override fun stop(): Boolean {
        // Invalidate first; keep the engine if queued audio has no successful stop receipt.
        operationId = null; utteranceId = null; onEvent = null
        val current = engine ?: return true
        val stopped = runCatching { current.stop() == TextToSpeech.SUCCESS }.getOrDefault(false)
        if (stopped) mayHaveAudio = false
        if (!stopped && mayHaveAudio) unresolvedEngine = current
        return stopped || !mayHaveAudio
    }
    override fun shutdown(): Boolean {
        operationId = null; utteranceId = null; onEvent = null
        if (mayHaveAudio) return false
        val old = engine ?: return true
        return runCatching { old.shutdown(); if (unresolvedEngine === old) unresolvedEngine = null; engine = null; true }.getOrElse { unresolvedEngine = old; false }
    }
}

/** Cancellable main-thread deadlines, with controller identity guards for already-enqueued tasks. */
class AndroidReadAloudTimer : ReadAloudTimer {
    private val main = Handler(Looper.getMainLooper())
    override fun schedule(delayMillis: Long, action: () -> Unit): () -> Unit {
        val task = Runnable { action() }
        check(main.postDelayed(task, delayMillis)) { "Unable to schedule speech timeout" }
        return { main.removeCallbacks(task) }
    }
}
