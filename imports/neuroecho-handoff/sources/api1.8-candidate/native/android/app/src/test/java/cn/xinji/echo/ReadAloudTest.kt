package cn.xinji.echo

import org.junit.Assert.*
import org.junit.Test
import java.util.Locale

class ReadAloudTest {
    private val local = LocalSpeechVoice("installed-zh", "zh-CN", false, true)
    private fun conversation(message: Message = Message("a", "assistant", "你好，今天慢慢来。"), id: String = "one") = Conversation(id, listOf(message), emptyList(), emptyList())
    private class FakeDriver : ReadAloudDriver {
        data class Init(val id: String, val ready: (String, Boolean, List<LocalSpeechVoice>, Int) -> Unit)
        data class Spoken(val op: String, val id: String, val voice: LocalSpeechVoice, val text: String, val event: (String, ReadAloudEvent) -> Unit)
        val initialized = mutableListOf<Init>(); val spoken = mutableListOf<Spoken>(); val events = mutableListOf<String>()
        var stopSucceeds = true; var shutdownSucceeds = true; var accepts = true; var throwInit = false; var throwSpeak = false; var throwStop = false
        override fun initialize(operationId: String, ready: (String, Boolean, List<LocalSpeechVoice>, Int) -> Unit) { if (throwInit) error("init failed"); events.add("init:$operationId"); initialized.add(Init(operationId, ready)) }
        override fun speak(operationId: String, utteranceId: String, voice: LocalSpeechVoice, text: String, event: (String, ReadAloudEvent) -> Unit): Boolean { if (throwSpeak) error("speak failed"); spoken.add(Spoken(operationId, utteranceId, voice, text, event)); events.add("speak:$utteranceId"); return accepts }
        override fun stop(): Boolean { events.add("stop"); if (throwStop) error("stop failed"); return stopSucceeds }
        override fun shutdown(): Boolean { events.add("shutdown"); return shutdownSucceeds }
    }
    private class FakeTimer : ReadAloudTimer {
        data class Task(val delay: Long, val action: () -> Unit, var cancelled: Boolean = false)
        val tasks = mutableListOf<Task>()
        override fun schedule(delayMillis: Long, action: () -> Unit): () -> Unit { val task = Task(delayMillis, action); tasks.add(task); return { task.cancelled = true } }
        fun fire(index: Int = tasks.lastIndex) { tasks[index].action() }
    }
    private inner class Fixture {
        var context = ReadAloudContext("http://127.0.0.1:18787", conversation(), setOf("a"), true)
        val driver = FakeDriver(); val timer = FakeTimer(); private var serial = 0
        val transitions = mutableListOf<ReadAloudState>()
        val controller = ReadAloudController(driver, { context }, timer, { "en-US" }, { "id-${++serial}" }, { transitions.add(it) })
        fun ready(index: Int = driver.initialized.lastIndex, voices: List<LocalSpeechVoice> = listOf(local), limit: Int = 4000, success: Boolean = true) { val init = driver.initialized[index]; init.ready(init.id, success, voices, limit) }
        fun event(value: ReadAloudEvent, index: Int = driver.spoken.lastIndex) { val speech = driver.spoken[index]; speech.event(speech.id, value) }
    }
    @Test fun creatingOrRefreshingNeverInitializesOrPlays() { val f = Fixture(); f.controller.refresh(); assertTrue(f.driver.initialized.isEmpty()); assertTrue(f.driver.spoken.isEmpty()); assertEquals(ReadAloudPhase.IDLE, f.controller.state.phase) }
    @Test fun onlyCompleteVisibleAssistantCanBeSelected() {
        val candidates = listOf(Message("a", "user", "原话"), Message("a", "system", "系统"), Message("a", "assistant", "", bubbles = emptyList()), Message("a", "assistant", "隐藏后文", bubbles = listOf("已显示"), deliveryPending = true), Message("a", "assistant", "不可信", deliveryFlagValid = false))
        for (message in candidates) { val f = Fixture(); f.context = f.context.copy(conversation = conversation(message)); f.controller.play("a"); assertTrue(f.driver.initialized.isEmpty()) }
        for (kind in 0..3) { val f = Fixture(); f.context = when(kind) { 0 -> f.context.copy(foreground = false); 1 -> f.context.copy(visibleMessageIds = emptySet()); 2 -> f.context.copy(conversation = null); else -> f.context.copy(conversation = conversation().copy(messages = listOf(Message("a", "assistant", "一"), Message("a", "assistant", "二")))) }; f.controller.play("a"); assertTrue(f.driver.initialized.isEmpty()) }
    }
    @Test fun parserRejectsMalformedDeliveryFlagForSpeechButKeepsLegacyVisibleText() {
        for (flag in listOf("false", 0, org.json.JSONObject.NULL)) { val parsed = messages(json("messages" to org.json.JSONArray().put(json("id" to "a", "role" to "assistant", "text" to "已显示", "delivery_pending" to flag)))).single(); assertFalse(parsed.deliveryFlagValid); val f = Fixture(); assertNull(ReadAloudPolicy.target(f.context.copy(conversation = conversation(parsed)), "a")) }
        val legacy = messages(json("messages" to org.json.JSONArray().put(json("id" to "a", "role" to "assistant", "text" to "旧完整文本")))).single(); assertTrue(legacy.deliveryFlagValid); assertEquals("旧完整文本", ReadAloudPolicy.target(Fixture().context.copy(conversation = conversation(legacy)), "a")?.visibleText)
    }
    @Test fun speaksRenderedPartsNeverTheHiddenFullBody() { val f = Fixture(); f.context = f.context.copy(conversation = conversation(Message("a", "assistant", "绝不能朗读的隐藏原文", bubbles = listOf("可见第一段", "可见第二段")))); f.controller.play("a"); f.ready(); assertEquals("可见第一段\n\n可见第二段", f.driver.spoken.single().text); assertFalse(f.driver.spoken.single().text.contains("隐藏")) }
    @Test fun voiceSelectionRejectsNetworkMissingAndWrongLanguageWithoutFallback() {
        val network = local.copy(name = "network", networkRequired = true); val missing = local.copy(name = "missing", installed = false); val english = local.copy(name = "en", languageTag = "en-US")
        assertNull(ReadAloudPolicy.chooseVoice(listOf(network, missing, english), "zh-CN")); assertEquals(local, ReadAloudPolicy.chooseVoice(listOf(local.copy(name = "other", languageTag = "zh-TW"), local), "zh-CN")); assertEquals("zh-CN", ReadAloudPolicy.preferredLanguage("中文🙂", "en-US")); assertEquals("en-US", ReadAloudPolicy.preferredLanguage("Hello", "en-US"))
        val f = Fixture(); f.controller.play("a"); f.ready(voices = listOf(network, missing, english)); assertEquals(ReadAloudPhase.UNAVAILABLE, f.controller.state.phase); assertTrue(f.driver.spoken.isEmpty()); assertEquals(ReadAloudUnavailable.NO_LOCAL_VOICE, f.controller.state.unavailable)
    }
    @Test fun failedInitAndEmptyVoiceListAreUnavailableNotAutomaticDownloads() { for (success in listOf(false, true)) { val f = Fixture(); f.controller.play("a"); f.ready(voices = emptyList(), success = success); assertEquals(ReadAloudPhase.UNAVAILABLE, f.controller.state.phase); assertTrue(f.driver.spoken.isEmpty()); assertEquals(1, f.driver.initialized.size) } }
    @Test fun stopBeforeInitPreventsLateReadyFromStarting() { val f = Fixture(); f.controller.play("a"); f.controller.stop(); f.ready(); assertEquals(ReadAloudPhase.IDLE, f.controller.state.phase); assertTrue(f.driver.spoken.isEmpty()) }
    @Test fun replacingPlaybackInvalidatesOldInitAndUtteranceCallbacks() {
        val f = Fixture(); f.controller.play("a"); val oldInit = f.driver.initialized.single(); f.controller.play("a"); oldInit.ready(oldInit.id, true, listOf(local), 4000); assertTrue(f.driver.spoken.isEmpty()); f.ready(); val firstSpeech = f.driver.spoken.single(); f.controller.play("a"); f.ready(); val active = f.controller.state
        firstSpeech.event(firstSpeech.id, ReadAloudEvent.START); firstSpeech.event(firstSpeech.id, ReadAloudEvent.DONE); firstSpeech.event(firstSpeech.id, ReadAloudEvent.ERROR); assertEquals(active, f.controller.state); assertEquals(2, f.driver.spoken.size)
    }
    @Test fun incorrectCallbackIdentitiesCannotAdvanceState() { val f = Fixture(); f.controller.play("a"); f.driver.initialized.single().ready("wrong", true, listOf(local), 4000); assertTrue(f.driver.spoken.isEmpty()); f.ready(); f.driver.spoken.single().event("wrong", ReadAloudEvent.DONE); assertEquals(ReadAloudPhase.QUEUED, f.controller.state.phase) }
    @Test fun acceptanceOnlyMeansQueuedAndStartDoneAreActualEvents() { val f = Fixture(); f.controller.play("a"); assertEquals(ReadAloudPhase.PREPARING, f.controller.state.phase); f.ready(); assertEquals(ReadAloudPhase.QUEUED, f.controller.state.phase); f.event(ReadAloudEvent.START); assertEquals(ReadAloudPhase.SPEAKING, f.controller.state.phase); f.event(ReadAloudEvent.DONE); assertEquals(ReadAloudPhase.IDLE, f.controller.state.phase) }
    @Test fun errorRejectionAndUnexpectedStopDoNotRetryOrSelectAnotherVoice() {
        for (mode in 0..2) { val f = Fixture(); f.controller.play("a"); if (mode == 0) f.driver.accepts = false; f.ready(); if (mode == 1) f.event(ReadAloudEvent.ERROR); if (mode == 2) f.event(ReadAloudEvent.STOP); assertEquals(if (mode == 2) ReadAloudPhase.IDLE else ReadAloudPhase.UNAVAILABLE, f.controller.state.phase); assertEquals(1, f.driver.initialized.size); assertEquals(1, f.driver.spoken.size) }
    }
    @Test fun endpointSessionContentDeletionVisibilityAndBackgroundChangesStopPlayback() {
        for (mode in 0..7) { val f = Fixture(); f.controller.play("a"); f.ready(); f.event(ReadAloudEvent.START); f.context = when(mode) {
            0 -> f.context.copy(endpoint = "https://other.example"); 1 -> f.context.copy(conversation = conversation(id = "two")); 2 -> f.context.copy(conversation = conversation(Message("a", "assistant", "更改"))); 3 -> f.context.copy(conversation = conversation().copy(messages = emptyList())); 4 -> f.context.copy(visibleMessageIds = emptySet()); 5 -> f.context.copy(foreground = false); 6 -> f.context.copy(conversation = conversation(Message("a", "assistant", "你好，今天慢慢来。", deliveryPending = true))); else -> f.context.copy(conversation = conversation(Message("a", "assistant", "你好，今天慢慢来。", bubbles = listOf("更改片段"))))
        }; f.controller.refresh(); assertEquals(ReadAloudPhase.IDLE, f.controller.state.phase); f.event(ReadAloudEvent.START); assertEquals(ReadAloudPhase.IDLE, f.controller.state.phase) }
    }
    @Test fun callbacksRevalidateLiveContextBeforePlayingEvenWithoutACompositionRefresh() { val f = Fixture(); f.controller.play("a"); f.context = f.context.copy(endpoint = "https://other.example"); f.ready(); assertTrue(f.driver.spoken.isEmpty()); assertEquals(ReadAloudPhase.IDLE, f.controller.state.phase) }
    @Test fun longTextChunksKeepAllVisibleCharactersAndSurrogatePairs() {
        val text = "开头。" + "a".repeat(3995) + "🙂" + "后文\n\n" + "结尾".repeat(3000)
        for (prefix in listOf(3999, 4000)) { val edge = "a".repeat(prefix) + "🙂"; val pieces = ReadAloudPolicy.chunks(edge, 4000); assertEquals(edge, pieces.joinToString("")); assertTrue(pieces.all { it.length <= 4000 }); assertTrue(pieces.none { Character.isHighSurrogate(it.last()) || Character.isLowSurrogate(it.first()) }) }; val chunks = ReadAloudPolicy.chunks(text, 4000); assertEquals(text, chunks.joinToString("")); assertTrue(chunks.all { it.length <= 4000 }); assertTrue(chunks.none { Character.isHighSurrogate(it.last()) || Character.isLowSurrogate(it.first()) }); assertThrows(IllegalArgumentException::class.java) { ReadAloudPolicy.chunks("🙂", 1) }
    }
    @Test fun chunksAdvanceOnlyOnMatchingDoneAndOldDoneCannotSkipANewChunk() {
        val f = Fixture(); f.context = f.context.copy(conversation = conversation(Message("a", "assistant", "甲乙丙丁戊己庚辛"))); f.controller.play("a"); f.ready(limit = 3); val first = f.driver.spoken.single(); f.event(ReadAloudEvent.START); assertEquals(1, f.driver.spoken.size); f.event(ReadAloudEvent.DONE); assertEquals(2, f.driver.spoken.size); val current = f.controller.state; first.event(first.id, ReadAloudEvent.DONE); assertEquals(current, f.controller.state); f.event(ReadAloudEvent.DONE); f.event(ReadAloudEvent.DONE); assertEquals("甲乙丙丁戊己庚辛", f.driver.spoken.joinToString("") { it.text }); assertEquals(ReadAloudPhase.IDLE, f.controller.state.phase)
    }
    @Test fun hiddenOrChangedTextBetweenChunksCannotContinue() { val f = Fixture(); f.context = f.context.copy(conversation = conversation(Message("a", "assistant", "甲乙丙丁戊己"))); f.controller.play("a"); f.ready(limit = 2); f.context = f.context.copy(foreground = false); f.event(ReadAloudEvent.DONE); assertEquals(1, f.driver.spoken.size); assertEquals(ReadAloudPhase.IDLE, f.controller.state.phase) }
    @Test fun badEngineLimitsFailInsteadOfSilentlyTruncating() { for (limit in listOf(0, -1)) { val f = Fixture(); f.controller.play("a"); f.ready(limit = limit); assertTrue(f.driver.spoken.isEmpty()); assertEquals(ReadAloudPhase.UNAVAILABLE, f.controller.state.phase) } }
    @Test fun closeReleasesEngineAndCannotBeRestartedByAnyOldCallback() { val f = Fixture(); f.controller.play("a"); f.controller.close(); f.ready(); f.controller.play("a"); assertTrue(f.driver.spoken.isEmpty()); assertEquals(1, f.driver.initialized.size); assertTrue(f.driver.events.contains("shutdown")) }
    @Test fun platformExceptionsDoNotCrashOrCauseFallback() { for (mode in 0..2) { val f = Fixture(); if (mode == 0) f.driver.throwInit = true; if (mode == 1) f.driver.throwSpeak = true; if (mode == 2) f.driver.throwStop = true; f.controller.play("a"); if (f.driver.initialized.isNotEmpty()) f.ready(); assertEquals(ReadAloudPhase.UNAVAILABLE, f.controller.state.phase); assertTrue(f.driver.initialized.size <= 1) } }
    @Test fun duplicateReadyCannotRestartOrRewindAnAlreadyQueuedUtterance() { val f = Fixture(); f.controller.play("a"); f.ready(); f.event(ReadAloudEvent.START); val current = f.controller.state; f.ready(); assertEquals(current, f.controller.state); assertEquals(1, f.driver.spoken.size) }
    @Test fun initializationTimeoutStopsAndIgnoresItsLateReadyCallback() { val f = Fixture(); f.controller.play("a"); assertEquals(10_000L, f.timer.tasks.last().delay); f.timer.fire(); assertEquals(ReadAloudUnavailable.TIMEOUT, f.controller.state.unavailable); f.ready(); assertTrue(f.driver.spoken.isEmpty()) }
    @Test fun queueAndPlaybackTimeoutsAreBoundedAndDoNotRetry() { for (started in listOf(false, true)) { val f = Fixture(); f.controller.play("a"); f.ready(); if (started) f.event(ReadAloudEvent.START); val timeout = f.timer.tasks.last().delay; assertTrue(timeout in 10_000L..300_000L); f.timer.fire(); assertEquals(ReadAloudUnavailable.TIMEOUT, f.controller.state.unavailable); assertEquals(1, f.driver.spoken.size); f.event(ReadAloudEvent.DONE); assertEquals(ReadAloudPhase.UNAVAILABLE, f.controller.state.phase) }; assertTrue(ReadAloudTimeouts.playbackMillis("a".repeat(100000)) <= 300_000L) }
    @Test fun obsoleteTimersCannotStopNewPhaseNewChunkOrNewPlayback() { val f = Fixture(); f.controller.play("a"); val initial = 0; f.ready(); val queued = f.timer.tasks.lastIndex; f.event(ReadAloudEvent.START); val current = f.controller.state; f.timer.fire(initial); f.timer.fire(queued); assertEquals(current, f.controller.state); val playing = f.timer.tasks.lastIndex; f.controller.play("a"); f.ready(); val replacement = f.controller.state; f.timer.fire(playing); assertEquals(replacement, f.controller.state); f.controller.stop(); f.timer.fire(); assertEquals(ReadAloudPhase.IDLE, f.controller.state.phase) }
    @Test fun duplicateStartDoesNotExtendPlaybackDeadlineForever() { val f = Fixture(); f.controller.play("a"); f.ready(); f.event(ReadAloudEvent.START); val count = f.timer.tasks.size; f.event(ReadAloudEvent.START); assertEquals(count, f.timer.tasks.size); f.timer.fire(); assertEquals(ReadAloudUnavailable.TIMEOUT, f.controller.state.unavailable) }
    @Test fun failedStopIsVisibleAndBlocksAnotherEngineUntilExplicitSuccessfulStop() { val f = Fixture(); f.controller.play("a"); f.ready(); f.event(ReadAloudEvent.START); f.driver.stopSucceeds = false; f.controller.stop(); assertTrue(f.controller.state.stopUncertain); assertEquals(ReadAloudUnavailable.STOP_UNCERTAIN, f.controller.state.unavailable); val stopped = f.driver.events.count { it == "stop" }; val before = f.context; f.context = before.copy(foreground = false); repeat(3) { f.controller.refresh() }; assertEquals(stopped, f.driver.events.count { it == "stop" }); f.context = before; val initializations = f.driver.initialized.size; f.controller.play("a"); assertEquals(initializations, f.driver.initialized.size); f.event(ReadAloudEvent.DONE); assertTrue(f.controller.state.stopUncertain); f.driver.stopSucceeds = true; f.controller.stop(); assertFalse(f.controller.state.stopUncertain); f.controller.play("a"); assertEquals(initializations + 1, f.driver.initialized.size) }
    @Test fun failedReleaseOrStopExceptionIsNotReportedAsStopped() { for (throwStop in listOf(false, true)) { val f = Fixture(); f.controller.play("a"); f.ready(); if (throwStop) f.driver.throwStop = true else f.driver.shutdownSucceeds = false; f.controller.stop(); assertTrue(f.controller.state.stopUncertain); assertEquals(ReadAloudPhase.UNAVAILABLE, f.controller.state.phase) } }
}
