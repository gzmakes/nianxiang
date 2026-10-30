package cn.xinji.echo

import org.junit.Assert.*
import org.junit.Test

class RulesTest {
    @Test fun defaultEndpointUsesLoopbackForExplicitAdbReverse() {
        assertEquals("http://127.0.0.1:18787", EndpointPolicy.DEFAULT)
        assertEquals(EndpointPolicy.DEFAULT, EndpointPolicy.validate(EndpointPolicy.DEFAULT, true))
        assertFails { EndpointPolicy.validate(EndpointPolicy.DEFAULT, false) }
    }
    @Test fun emulatorHttpIsDebugOnly() {
        assertEquals("http://10.0.2.2:18787", EndpointPolicy.validate("http://10.0.2.2:18787/", true))
        assertFails { EndpointPolicy.validate("http://10.0.2.2:18787", false) }
        assertFails { EndpointPolicy.validate("http://192.168.1.4:18787", true) }
    }
    @Test fun physicalEndpointRequiresHttpsAndNoEmbeddedCredentials() {
        assertEquals("https://echo.example.com", EndpointPolicy.validate("https://echo.example.com", false))
        assertFails { EndpointPolicy.validate("https://name:secret@echo.example.com", false) }
        assertFails { EndpointPolicy.validate("https://echo.example.com/path", false) }
        assertFails { EndpointPolicy.validate("https://echo.example.com?token=value", false) }
    }
    @Test fun pendingTurnKeepsTheSameIdentityWhenCancelled() {
        val turn = PendingTurn.new("canonical", "用户原话")
        assertEquals(turn.id, turn.copy(cancelWanted = true).id)
        assertEquals(turn.sessionId, turn.copy(cancelWanted = true).sessionId)
        assertEquals(turn.text, turn.copy(cancelWanted = true).text)
        assertNotEquals(turn.id, PendingTurn.new("canonical", "另一句话").id)
    }
    @Test fun memoryProposalChoiceIsFrozenIntoPendingWireAndCancelPayload() {
        val turn = PendingTurn.new("canonical", "我通常喜欢喝茶", memoryProposals = true)
        val restored = PendingTurn.decode(turn.encode())!!
        assertTrue(restored.memoryProposals)
        assertEquals(turn.body().toString(), restored.body().toString())
        assertEquals(turn.id, restored.copy(cancelWanted = true).id)
        assertTrue(restored.copy(cancelWanted = true).body().getBoolean("memory_proposals"))
        // The current preference is deliberately not an argument to body().
        assertTrue(restored.body().getBoolean("memory_proposals"))
    }
    @Test fun legacyPendingWithoutProposalChoicePreservesItsOriginalFalsePayload() {
        val restored = PendingTurn.decode("""{"id":"stable","session_id":"canonical","text":"旧请求","cancel":true}""")!!
        assertFalse(restored.memoryProposals)
        assertFalse(restored.body().getBoolean("memory_proposals"))
        assertTrue(restored.cancelWanted); assertEquals("stable", restored.id)
        assertFalse(PendingTurn.new("canonical", "新请求").memoryProposals)
    }
    @Test fun onlyPreviewedActionsCanContinue() {
        assertEquals(ActionRoute.CONFIRM_EXISTING, actionRoute("previewed"))
        listOf("unknown", "executing").forEach { assertEquals(ActionRoute.CHECK_ONLY, actionRoute(it)) }
        listOf("committed", "failed", "other").forEach { assertEquals(ActionRoute.INSPECT, actionRoute(it)) }
    }
    @Test fun runningOrMissingRequestsCannotBeReleasedAsANewTurn() {
        listOf("running", "pending", "unconfirmed", "").forEach { status -> assertFalse(mayReturnTextAfterReview("same", "same", status)) }
        assertTrue(mayReturnTextAfterReview("same", "same", "unknown"))
        assertTrue(mayReturnTextAfterReview("old-backend-record", "new-canonical", ""))
    }
    @Test fun onlyExplicitBudgetRejectionAllowsRestoringDraftWithoutUnknownState() {
        assertTrue(isDefinitiveBudgetRejection(httpStatus = 429))
        assertTrue(isDefinitiveBudgetRejection(errorCode = "budget_exceeded"))
        listOf(202, 408, 409, 500, 503).forEach { assertFalse(isDefinitiveBudgetRejection(httpStatus = it)) }
        listOf("execution_uncertain", "process_interrupted", "", "running").forEach { assertFalse(isDefinitiveBudgetRejection(errorCode = it)) }
    }
    @Test fun filePreviewRetainsExactlyTheConfirmedPrefixWithoutSplittingEmoji() {
        val text = "😀".repeat(4001)
        val preview = FilePreviewPolicy.preview("合成.txt", text.toByteArray())
        assertEquals(4000, preview.text.codePointCount(0, preview.text.length))
        assertEquals("😀".repeat(4000), preview.text)
        assertTrue(preview.truncated)
    }
    @Test fun unsafeOrUnsupportedSelectionsAreRejectedBeforeUpload() {
        listOf("../secret.txt", "folder/file.md", "image.png", "line\n.txt").forEach { name -> assertFails { FilePreviewPolicy.preview(name, "text".toByteArray()) } }
        assertFails { FilePreviewPolicy.preview("empty.txt", byteArrayOf()) }
        assertFails { FilePreviewPolicy.preview("invalid.txt", byteArrayOf(0xC3.toByte(), 0x28)) }
        assertFails { FilePreviewPolicy.preview("binary.txt", byteArrayOf(0)) }
        assertFails { FilePreviewPolicy.preview("huge.txt", ByteArray(FilePreviewPolicy.MAX_BYTES + 1) { 65 }) }
    }
    private fun assertFails(block: () -> Unit) {
        try { block(); fail("Expected validation to reject the input") } catch (_: IllegalArgumentException) {} catch (_: java.nio.charset.CharacterCodingException) {}
    }
}
