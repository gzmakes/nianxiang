package cn.xinji.echo

import org.junit.Assert.*
import org.junit.Test
import cn.xinji.echo.shared.EchoSharedReference as Shared

class UsabilityRulesTest {
    private val access = LocalDraftAccess("active-generation:1", "active-scope", "active-scope", true, "same-conversation")
    @Test fun modalShowsErrorAndPendingTogetherWithoutClearingEither() {
        val lines = visibleFeedback("设备令牌格式不正确。", UpdateStatus.PENDING, true, true)
        assertEquals(listOf("设备令牌格式不正确。", Shared.COPY_CONNECTION_SYNC_PENDING), lines)
        assertEquals(listOf(Shared.COPY_CONNECTION_SYNC_PENDING), visibleFeedback("", UpdateStatus.PENDING, true, true))
    }
    @Test fun disconnectedPairingErrorStillVisibleWithoutPretendingUpdatesAvailable() {
        assertEquals(listOf("HTTPS 连接未完成。"), visibleFeedback("HTTPS 连接未完成。", UpdateStatus.IDLE, false, false))
        assertTrue(visibleFeedback("", UpdateStatus.UPDATED, false, true).isEmpty())
    }
    @Test fun exactUpdateStatesStayDistinctAndDoNotMaskNotice() {
        assertEquals(Shared.COPY_CONNECTION_SYNC_OFFLINE, updateFeedback(UpdateStatus.OFFLINE, true, true))
        assertEquals(Shared.COPY_CONNECTION_SYNC_UNSUPPORTED, updateFeedback(UpdateStatus.IDLE, true, false))
        assertTrue(updateFeedback(UpdateStatus.IDENTITY_CHANGED, true, true).contains("身份"))
        assertEquals(1, visibleFeedback(Shared.COPY_CONNECTION_SYNC_PENDING, UpdateStatus.PENDING, true, true).size)
    }
    @Test fun draftReviewRequiresCurrentAvailableScope() {
        for (invalid in listOf(access.copy(available = false), access.copy(activeScope = null), access.copy(activeScope = "old-scope"), access.copy(contextId = ""), access.copy(scope = "")))
            assertNull(localDraftReview(invalid, "private text", null, null, null))
    }
    @Test fun originalTextAndUnknownStateAreNotChangedByReview() {
        val chat = "  原输入\n中文🙂  "
        val memory = MemoryDraft(text = "原记忆草稿", sessionId = access.sessionId!!, uncertain = true)
        val followup = FollowupDraft(access.sessionId!!, content = "原跟进", requestId = "frozen-request-identity", started = true)
        val mood = MoodDraft(access.sessionId!!, "2026-10-30", note = "原心情", xChosen = true, yChosen = true).beginSave(useLedger = true)
        val before = listOf(memory.encode(), followup.encode(), mood.encode())
        val review = localDraftReview(access, chat, memory, followup, mood)!!
        assertEquals(chat, review.entries.single { it.key == "chat" }.text)
        assertEquals(listOf("chat", "memory", "followup", "mood"), review.entries.map { it.key })
        assertEquals(before, listOf(memory.encode(), followup.encode(), mood.encode()))
        assertTrue(review.entries.single { it.key == "followup" }.explanation.contains("待核对"))
        assertFalse(review.entries.any { it.text.contains(followup.requestId) || it.text.contains(mood.operationId!!) })
    }
    @Test fun otherConversationDraftsAreNeverMixedIntoPairedReview() {
        val memory = MemoryDraft(text = "other memory", sessionId = "another-conversation")
        val followup = FollowupDraft("another-conversation", content = "other followup")
        val mood = MoodDraft("another-conversation", "2026-10-30", note = "other diary")
        val review = localDraftReview(access, "current-scope composer", memory, followup, mood)!!
        assertEquals(listOf("chat"), review.entries.map { it.key })
    }
    @Test fun rememberedViewCannotBeCopiedAfterIdentityOrGenerationChanges() {
        val review = localDraftReview(access, "kept text", null, null, null)!!
        assertTrue(mayPresentDraftReview(review, access))
        assertFalse(mayPresentDraftReview(review, access.copy(contextId = "active-generation:2")))
        assertFalse(mayPresentDraftReview(review, access.copy(scope = "new", activeScope = "new")))
        assertFalse(mayPresentDraftReview(review, access.copy(available = false)))
    }
    @Test fun emptyAndUnchosenMoodDoesNotInventNeutralFeeling() {
        val empty = MoodDraft(access.sessionId!!, "2026-10-30")
        assertNull(localDraftReview(access, "", null, null, empty))
        val explicitNeutral = empty.copy(xChosen = true, yChosen = true)
        val entry = localDraftReview(access, "", null, null, explicitNeutral)!!.entries.single()
        assertTrue(entry.text.contains("0.0")); assertFalse(entry.text.contains("尚未选择"))
    }
    @Test fun oneChosenAxisLeavesOtherExplicitlyUnchosen() {
        val entry = localDraftReview(access, "", null, null, MoodDraft(access.sessionId!!, "2026-10-30", xChosen = true))!!.entries.single()
        assertTrue(entry.explanation.contains("精力：尚未选择"))
    }
    @Test fun localDevelopmentReviewRemainsOriginScopedWithoutClaimingServerIdentity() {
        val local = access.copy(contextId = "local-origin-epoch", scope = "local-origin", activeScope = "local-origin", sessionId = null)
        val original = MemoryDraft(text = "本地址保留的旧文字", sessionId = "unverified-while-offline")
        val review = localDraftReview(local, "", original, null, null)!!
        assertEquals(original.text, review.entries.single().text)
        assertTrue(review.entries.single().explanation.contains("尚未核对"))
        assertFalse(mayPresentDraftReview(review, local.copy(contextId = "different-endpoint-epoch")))
    }
}
