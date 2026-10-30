package cn.xinji.echo

import java.time.Instant
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class FollowupRulesTest {
    @Test fun only_first_attempt_validation_rejection_allows_editing() {
        assertTrue(followupDefinitiveRejection(400, true)); assertTrue(followupDefinitiveRejection(422, true))
        for (status in listOf(400, 422, 408, 409, 429, 500)) assertFalse(followupDefinitiveRejection(status, false))
        for (status in listOf(408, 409, 429, 500)) assertFalse(followupDefinitiveRejection(status, true))
    }
    private val now = Instant.parse("2026-10-30T00:00:00Z")
    @Test fun explicitFutureFollowupCarriesConsentAndPersistentRequestIdentity() {
        val prepared = FollowupDraft("canonical", " 周五再看看 ", "2026-10-31T01:00:00Z").prepared(now)
        val restored = FollowupDraft.decode(prepared.encode())!!
        assertEquals(prepared, restored)
        assertEquals("周五再看看", restored.content)
        assertTrue(restored.body().getBoolean("confirmed"))
        assertTrue(restored.requestId.isNotEmpty())
    }
    @Test fun uncertainSaveKeepsSameIdAndPayloadAfterDueTime() {
        val pending = FollowupDraft("canonical", "只留一次", "2026-10-31T01:00:00Z").prepared(now)
        assertEquals(pending, pending.prepared(Instant.parse("2026-11-01T01:00:00Z")))
    }
    @Test fun emptyPastAndTimezoneFreeInputsCannotBecomeRequests() {
        for (draft in listOf(FollowupDraft("s", "", "2026-10-31T00:00:00Z"), FollowupDraft("s", "跟进", "2026-10-29T00:00:00Z"), FollowupDraft("s", "跟进", "2026-10-31T00:00"))) {
            assertThrows(IllegalArgumentException::class.java) { draft.prepared(now) }
        }
    }
    @Test fun reconciliationRequiresRequestIdScopeContentAndSameInstant() {
        val draft = FollowupDraft("s", "同一内容", "2026-10-31T01:00:00Z").prepared(now)
        val saved = Followup("f", "s", draft.requestId, draft.content, "2026-10-31T01:00:00.000000Z", "done", false)
        assertEquals(saved, draft.matching(listOf(saved)))
        assertNull(draft.matching(listOf(saved.copy(requestId = "another"))))
        assertNull(draft.matching(listOf(saved.copy(sessionId = "other"))))
        assertNull(draft.matching(listOf(saved.copy(content = "不同内容"))))
        assertNull(draft.matching(listOf(saved.copy(status = "unexpected"))))
    }
    @Test fun oneTimeApprovalCannotBeReconciledOrTransitionedAsRecurring() {
        val draft = FollowupDraft("s", "只确认这一次", "2026-10-31T01:00:00Z").prepared(now)
        val repeated = Followup("f", "s", draft.requestId, draft.content, draft.dueAt, "pending", false, repeatRule = "daily")
        assertNull(draft.matching(listOf(repeated)))
        assertEquals("cancelled", followupTransitionRequest(repeated, "cancelled").body.getString("status"))
        assertThrows(IllegalArgumentException::class.java) { followupTransitionRequest(repeated.copy(repeatRule = "weekly"), "done") }
    }
    @Test fun statusParsingDoesNotPretendAClosedOrUnknownRecordWasDelivered() {
        val result = followups(JSONObject("""{"followups":[{"id":"f","session_id":"s","request_id":"r","content":"跟进","due_at":"2026-10-31T01:00:00Z","status":"pending","due":true}]}"""))
        assertEquals("已到时间", followupStateLabel(result.single()))
        assertEquals("已取消", followupStateLabel(result.single().copy(status = "cancelled")))
        assertEquals("状态待核对", followupStateLabel(result.single().copy(status = "unexpected")))
    }
    @Test fun knownDailyRulesSupportTransitionsButUnknownRulesStayReadOnly() {
        val base = """{"id":"f","session_id":"s","request_id":"r","content":"跟进","due_at":"2026-10-31T01:00:00Z","status":"pending","due":true"""
        val legacy = followup(JSONObject("$base}"))
        val daily = followup(JSONObject("$base,\"repeat_rule\":\"daily\",\"paused\":true}"))
        val future = followup(JSONObject("$base,\"repeat_rule\":\"weekly\",\"quiet\":true}"))
        assertTrue(legacy.supportsNativeTransitions)
        assertTrue(daily.supportsNativeTransitions); assertEquals("已暂停", followupStateLabel(daily))
        assertFalse(future.supportsNativeTransitions); assertEquals("安静时段", followupStateLabel(future))
    }
    @Test fun UnicodeFollowupLimitMatchesBackendCodePoints() {
        assertEquals(1000, FollowupDraft("s", "😀".repeat(1000), "2026-10-31T01:00:00Z").prepared(now).content.codePointCount(0, 2000))
        assertThrows(IllegalArgumentException::class.java) { FollowupDraft("s", "中".repeat(1001), "2026-10-31T01:00:00Z").prepared(now) }
    }
    @Test fun firstExplicitValidationRejectionCanReturnToEditableDraft() {
        for ((status, code) in listOf(400 to "invalid_request", 422 to "validation_error")) {
            val initial = FollowupDraft("s", "跟进", "2026-10-31T01:00:00Z").beginSave(now)
            assertTrue(initial.initialAttempt)
            val rejected = initial.afterFailure(status, code)
            assertEquals("", rejected.requestId); assertFalse(rejected.started)
            assertEquals(initial.request.content, rejected.content)
            assertNotEquals(initial.request.requestId, rejected.beginSave(now).request.requestId)
        }
    }
    @Test fun firstTimeoutThenRetry400KeepsOriginalUnknownLedger() {
        val initial = FollowupDraft("s", "只跟进一次", "2026-10-31T01:00:00Z").beginSave(now)
        val unknown = initial.afterFailure()
        val retry = unknown.beginSave(now)
        val laterRejected = retry.afterFailure(400, "invalid_request")
        assertFalse(retry.initialAttempt)
        assertEquals(initial.request.requestId, laterRejected.requestId)
        assertEquals(initial.request.body().toString(), laterRejected.body().toString())
        assertTrue(laterRejected.started)
    }
    @Test fun restartAfterStartedSaveCannotReleaseIdOn422() {
        val initial = FollowupDraft("s", "保留这个账本", "2026-10-31T01:00:00Z").beginSave(now)
        val restored = FollowupDraft.decode(initial.request.encode())!!
        assertTrue(restored.started)
        val rejected = restored.beginSave(now).afterFailure(422, "validation_error")
        assertEquals(initial.request.requestId, rejected.requestId)
        assertTrue(rejected.started)
    }
    @Test fun legacyLedgerWithIdIsConservativelyTreatedAsStarted() {
        val legacy = FollowupDraft.decode("""{"session_id":"s","content":"旧版未决请求","due_at":"2026-10-31T01:00:00Z","request_id":"original-stable-id"}""")!!
        assertTrue(legacy.started)
        assertEquals("original-stable-id", legacy.beginSave(now).afterFailure(400, "invalid_request").requestId)
    }
    @Test fun authRateLimitConflictAndServerFailuresNeverRetireAnUnknownId() {
        for (status in listOf(401, 403, 404, 408, 409, 429, 500, 503)) {
            val attempt = FollowupDraft("s", "合成跟进", "2026-10-31T01:00:00Z").beginSave(now)
            assertEquals(attempt.request.requestId, attempt.afterFailure(status, "unrelated_error").requestId)
        }
        val attempt = FollowupDraft("s", "合成跟进", "2026-10-31T01:00:00Z").beginSave(now)
        assertEquals(attempt.request.requestId, attempt.afterFailure(400, "unknown_proxy_error").requestId)
    }
    @Test fun startedIsPersistedBeforeWireSendButNeverAddedToApiPayload() {
        val attempt = FollowupDraft("s", "合成跟进", "2026-10-31T01:00:00Z").beginSave(now)
        assertTrue(JSONObject(attempt.request.encode()).getBoolean("started"))
        assertFalse(attempt.request.body().has("started"))
        assertEquals(attempt.request, FollowupDraft.decode(attempt.request.encode()))
    }
    @Test fun preexistingPreparedIdCannotBeCalledANewInitialAttempt() {
        val prepared = FollowupDraft("s", "只保留原编号", "2026-10-31T01:00:00Z").prepared(now)
        val attempt = prepared.beginSave(now)
        assertFalse(attempt.initialAttempt)
        assertEquals(prepared.requestId, attempt.afterFailure(400, "invalid_request").requestId)
    }
    @Test fun dailyLedgerFreezesAllConsentedFieldsAndMatchesAdvancedOccurrence() {
        val draft = FollowupDraft("s", "核对原型", "2026-10-31T01:00:00Z", repeatRule = "daily",
            timeZone = "Asia/Shanghai", quietStart = "22:00", quietEnd = "08:00",
            allowContact = true, contactWindowMinutes = 15, contactTopic = "原型",
            contactFieldsIncluded = true).prepared(now)
        val restored = FollowupDraft.decode(draft.encode())!!
        assertEquals(draft, restored)
        val receipt = Followup("f", "s", draft.requestId, draft.content, "2026-11-02T01:00:00Z", "pending", false,
            repeatRule = "daily", timeZone = "Asia/Shanghai", quietStart = "22:00", quietEnd = "08:00",
            createdDueAt = draft.dueAt, allowContact = true, contactWindowMinutes = 15, contactTopic = "原型")
        assertNotNull(restored.matching(listOf(receipt)))
        assertNull(restored.matching(listOf(receipt.copy(quietEnd = "09:00"))))
        assertNull(restored.matching(listOf(receipt.copy(timeZone = "UTC"))))
        assertNull(restored.matching(listOf(receipt.copy(contactTopic = "不同话题"))))
        assertNull(restored.matching(listOf(receipt.copy(allowContact = false))))
        assertNull(restored.matching(listOf(receipt.copy(status = "unknown"))))
    }
    @Test fun invalidRecurringQuietAndWindowFieldsCannotBeSubmitted() {
        val good = FollowupDraft("s", "跟进", "2026-10-31T01:00:00Z")
        for (bad in listOf(good.copy(repeatRule = "weekly"), good.copy(timeZone = "Nowhere/Invalid"),
            good.copy(quietStart = "22:00"), good.copy(quietStart = "22:00", quietEnd = "22:00"),
            good.copy(quietStart = "24:00", quietEnd = "08:00"), good.copy(contactWindowMinutes = 181),
            good.copy(allowContact = true))) assertThrows(IllegalArgumentException::class.java) { bad.prepared(now) }
    }
    @Test fun dailyTransitionBindsOccurrenceAndRejectsOtherOrUnchangedReceipt() {
        val old = Followup("f", "s", "r", "每天聊聊", "2026-10-31T01:00:00Z", "pending", true, repeatRule = "daily")
        val request = followupTransitionRequest(old, "done")
        assertEquals(old.dueAt, request.body.getString("occurrence_at"))
        val good = old.copy(dueAt = "2026-11-01T01:00:00Z", lastOccurrenceAt = old.dueAt)
        assertTrue(followupTransitionMatches(old, "done", good))
        assertFalse(followupTransitionMatches(old, "done", old))
        assertFalse(followupTransitionMatches(old, "done", good.copy(lastOccurrenceAt = "2026-10-30T01:00:00Z")))
        assertFalse(followupTransitionMatches(old, "done", good.copy(id = "other")))
        assertFalse(followupTransitionMatches(old, "done", good.copy(status = "done")))
        assertThrows(IllegalArgumentException::class.java) { followupTransitionRequest(old.copy(due = false), "done") }
        assertTrue(followupTransitionMatches(old, "paused", old.copy(paused = true)))
        assertFalse(followupTransitionMatches(old, "resumed", old.copy(paused = true)))
    }
    @Test fun legacyUnknownFollowupNeverAddsNewFieldsToItsWirePayload() {
        val old = FollowupDraft.decode("""{"session_id":"s","content":"旧请求","due_at":"2026-10-31T01:00:00Z","request_id":"old"}""")!!
        assertEquals(0, old.wireVersion)
        for (key in listOf("repeat_rule", "time_zone", "quiet_start", "quiet_end", "allow_contact", "contact_topic", "contact_window_minutes")) assertFalse(old.body().has(key))
        assertEquals(old.body().toString(), FollowupDraft.decode(old.encode())!!.body().toString())
        assertEquals(old.body().toString(), old.beginSave(now).afterFailure(400, "invalid_request").body().toString())
    }

    @Test fun chosenZoneMatchesTheTimeShownForConsentAndHistory() {
        val time = "2026-10-31T14:00:00Z"
        assertEquals("10月31日 10:00", followupTimeLabel(time, "America/New_York"))
        assertEquals("10月31日 22:00", followupTimeLabel(time, "Asia/Shanghai"))
        assertEquals("时间待核对", followupTimeLabel(time, "Invalid/Zone"))
    }
    @Test fun permissionHistoryDoesNotPretendRevokedOrExpiredContactIsStillActive() {
        val item = Followup("f", "s", "r", "正文", "2026-10-31T01:00:00Z", "pending", true, allowContact = true, contactTopic = "原型")
        assertTrue(followupContactLabel(item.copy(contactReason = "boundary_changed")).contains("失效"))
        assertTrue(followupContactLabel(item.copy(contactReason = "suppressed_occurrence")).contains("重新约定"))
        assertTrue(followupContactLabel(item.copy(contactReason = "expired")).contains("不再补问"))
        assertTrue(followupContactLabel(item.copy(contactReason = "quiet")).contains("不主动"))
        assertTrue(followupContactLabel(item.copy(contactEligible = true)).contains("窗口内"))
        assertTrue(followupContactLabel(item.copy(contactReason = "already_claimed")).contains("不会再"))
    }
    @Test fun resumeCannotSucceedWithoutExplicitBooleanPausedReceipt() {
        val original = Followup("f", "s", "r", "暂停", "2026-10-31T01:00:00Z", "pending", false, paused = true)
        fun fixture() = JSONObject().put("id","f").put("session_id","s").put("request_id","r").put("content","暂停")
            .put("due_at",original.dueAt).put("status","pending")
        for (obj in listOf(fixture(), fixture().put("paused","false"), fixture().put("paused",0))) {
            val parsed = followup(obj)
            assertFalse(parsed.pausedKnown); assertFalse(followupTransitionMatches(original,"resumed",parsed))
        }
        assertTrue(followupTransitionMatches(original,"resumed",followup(fixture().put("paused",false))))
    }

}
