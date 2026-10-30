package cn.xinji.echo

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class SourceRevocationTest {
    private val selected = Source("source-a", "合成资料A", "本机文本", false)
    private val other = Source("source-b", "合成资料B", "本机文本", false)
    private val attempt = SourceRevocationAttempt("http://127.0.0.1:18787", "canonical", selected, "operation-1")
    private fun snapshot(sources: List<Source> = listOf(selected, other), sid: String = "canonical") = Conversation(sid, emptyList(), emptyList(), sources)
    private fun receipt() = JSONObject("""{"ok":true,"state":"listening","cleaned":2,"review_required":0,"remaining_sources":1,"revoked_source_ids":["source-a"]}""")
    private fun outcome(result: JSONObject?, fresh: Conversation? = snapshot(listOf(other))) = attempt.outcome(result, fresh, attempt.endpoint, attempt.sessionId, attempt.token)

    @Test fun exactReceiptAndSameConversationReadConfirmOnlySelectedSource() {
        assertTrue(attempt.canStart(attempt.endpoint, snapshot()))
        assertEquals(SourceRevokeOutcome.CONFIRMED, outcome(receipt()))
        assertEquals(listOf(other), snapshot(listOf(other)).sources)
        assertEquals("source-a", attempt.body().getString("source_id"))
        assertEquals("canonical", attempt.body().getString("session_id"))
    }
    @Test fun falseAndMissingOkNeverMeanSuccessEvenIfReadNoLongerHasSource() {
        assertEquals(SourceRevokeOutcome.UNRESOLVED, outcome(receipt().put("ok", false)))
        val missing = receipt(); missing.remove("ok")
        assertEquals(SourceRevokeOutcome.UNRESOLVED, outcome(missing))
        assertEquals(SourceRevokeOutcome.UNRESOLVED, outcome(null))
    }
    @Test fun stringTrueIsNotABooleanReceipt() {
        assertFalse(attempt.receiptMatches(receipt().put("ok", "true")))
    }
    @Test fun missingIdentityOrCountersCannotConfirmRevocation() {
        for (key in listOf("revoked_source_ids", "cleaned", "review_required", "remaining_sources", "state")) {
            val incomplete = receipt(); incomplete.remove(key)
            assertEquals(key, SourceRevokeOutcome.UNRESOLVED, outcome(incomplete))
        }
    }
    @Test fun unknownStatesAndInvalidCountsRemainUnresolved() {
        assertEquals(SourceRevokeOutcome.UNRESOLVED, outcome(receipt().put("state", "unexpected")))
        assertEquals(SourceRevokeOutcome.UNRESOLVED, outcome(receipt().put("cleaned", "2")))
        assertEquals(SourceRevokeOutcome.UNRESOLVED, outcome(receipt().put("remaining_sources", -1)))
    }
    @Test fun differentOrExtraRevokedIdsCannotApproveThisSingleSourceRequest() {
        assertFalse(attempt.receiptMatches(receipt().put("revoked_source_ids", org.json.JSONArray(listOf("source-b")))))
        assertFalse(attempt.receiptMatches(receipt().put("revoked_source_ids", org.json.JSONArray(listOf("source-a", "source-b")))))
    }
    @Test fun sourceStillPresentAfterRefreshMeansUnresolved() {
        assertEquals(SourceRevokeOutcome.UNRESOLVED, outcome(receipt(), snapshot()))
        assertEquals(SourceRevokeOutcome.UNRESOLVED, outcome(receipt(), null))
    }
    @Test fun differentEndpointSessionOrOperationMakesLateReceiptObsolete() {
        for ((origin, sid, token) in listOf(Triple("https://other.test", "canonical", "operation-1"), Triple(attempt.endpoint, "other-session", "operation-1"), Triple(attempt.endpoint, "canonical", "new-operation"))) {
            assertEquals(SourceRevokeOutcome.OBSOLETE, attempt.outcome(receipt(), snapshot(listOf(other)), origin, sid, token))
        }
    }
    @Test fun wrongConversationSnapshotDoesNotConfirmTheCurrentOne() {
        assertEquals(SourceRevokeOutcome.UNRESOLVED, outcome(receipt(), snapshot(listOf(other), "other-session")))
        assertFalse(attempt.receiptMatches(receipt().put("session_id", "other-session")))
    }
    @Test fun sourceChangedBetweenApprovalAndStartRequiresReviewWithoutPost() {
        assertFalse(attempt.canStart(attempt.endpoint, snapshot(listOf(other))))
        assertFalse(attempt.canStart(attempt.endpoint, snapshot(listOf(selected.copy(stale = true), other))))
    }
}
