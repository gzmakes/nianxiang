package cn.xinji.echo

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class MoodOperationTest {
    private val old = "2026-10-30T00:00:00.000001+00:00"
    private val fresh = "2026-10-30T00:00:01.000001+00:00"
    private fun draft() = MoodDraft("synthetic-sid", "2026-10-30", .4, -.3, "合成原文🙂\n由我选择", true, true, dirty = true)
    private fun response(d: MoodDraft, state: String = "applied", token: String? = fresh): JSONObject {
        val op = d.ledgerOperation()!!
        return json("session_id" to d.sessionId, "request_id" to op.requestId, "operation_sha256" to if (state == "not_found") null else op.sha256,
            "kind" to if (state == "not_found") null else op.kind, "state" to state, "result_updated_at" to token)
    }
    @Test fun exactBytesAndIdSurviveRestartWithoutReserialization() {
        val frozen = draft().beginSave(true)
        val original = frozen.ledgerOperation()!!
        val restored = MoodDraft.decode(frozen.encode())!!
        assertEquals(frozen, restored)
        assertEquals(original.raw, restored.ledgerOperation()!!.raw)
        assertEquals(original.sha256, restored.ledgerOperation()!!.sha256)
        assertEquals(original.raw, original.applyBody(frozen.sessionId).getString("operation_json"))
        assertEquals(64, original.sha256.length)
        assertNotEquals(original.sha256, MoodOperation(original.requestId, original.raw + " ", "save").sha256)
    }
    @Test fun legacyUnknownNeverGetsAnInventedIdentity() {
        val legacy = MoodDraft.decode(draft().beginSave().encode())!!
        assertNull(legacy.ledgerOperation())
        assertNull(legacy.operationId)
        assertTrue(legacy.locked)
        assertTrue(runCatching { legacy.requestCancellation() }.isFailure)
    }
    @Test fun cancellationIntentIsDurableAndMetadataOnly() {
        val frozen = draft().beginSave(true).requestCancellation()
        val restored = MoodDraft.decode(frozen.encode())!!
        assertTrue(restored.cancelRequested)
        val body = restored.ledgerOperation()!!.cancelBody(restored.sessionId)
        assertEquals(setOf("session_id", "operation_sha256", "kind", "confirmed"), body.keySet())
        assertFalse(body.toString().contains("合成原文"))
    }
    @Test fun notFoundDoesNotUnlockPendingOrCancelledIntent() {
        for (frozen in listOf(draft().beginSave(true), draft().beginSave(true).requestCancellation())) {
            val receipt = moodOperationReceipt(response(frozen, "not_found", null), frozen.sessionId, frozen.ledgerOperation()!!)
            assertEquals(frozen, frozen.afterLedgerReceipt(receipt, null))
            assertTrue(frozen.locked)
        }
    }
    @Test fun receiptRequiresAllFieldsAndExactIdentity() {
        val frozen = draft().beginSave(true)
        val valid = response(frozen)
        for (key in valid.keySet()) assertTrue(runCatching {
            moodOperationReceipt(JSONObject(valid.toString()).also { it.remove(key) }, frozen.sessionId, frozen.ledgerOperation()!!)
        }.isFailure)
        for ((key, wrong) in listOf("session_id" to "wrong", "request_id" to "wrong", "operation_sha256" to "0".repeat(64), "kind" to "delete", "state" to "running", "result_updated_at" to "bad"))
            assertTrue(runCatching { moodOperationReceipt(JSONObject(valid.toString()).put(key, wrong), frozen.sessionId, frozen.ledgerOperation()!!) }.isFailure)
        assertTrue(runCatching { moodOperationReceipt(response(frozen, token = null), frozen.sessionId, frozen.ledgerOperation()!!) }.isFailure)
        assertTrue(runCatching { moodOperationReceipt(response(frozen).put("extra", true), frozen.sessionId, frozen.ledgerOperation()!!) }.isFailure)
        val update = draft().copy(expectedUpdatedAt = old).beginSave(true)
        assertTrue(runCatching { moodOperationReceipt(response(update, token = old), update.sessionId, update.ledgerOperation()!!) }.isFailure)
    }
    @Test fun appliedHistoricalSaveDoesNotResurrectLaterDeletionOrOverwriteNewerRow() {
        val frozen = draft().beginSave(true)
        val receipt = moodOperationReceipt(response(frozen), frozen.sessionId, frozen.ledgerOperation()!!)
        for (current in listOf(null, MoodRecord(frozen.date, frozen.x, frozen.y, frozen.note, old), MoodRecord(frozen.date, frozen.x, frozen.y, frozen.note, "2026-10-30T00:00:02.000001+00:00"), MoodRecord(frozen.date, .9, .9, "后来改过", fresh))) {
            val next = frozen.afterLedgerReceipt(receipt, current)
            assertTrue(next.conflict && next.dirty)
            assertEquals(frozen.note, next.note)
            assertNull(next.operationId)
        }
        val current = MoodRecord(frozen.date, frozen.x, frozen.y, frozen.note, fresh)
        assertFalse(frozen.afterLedgerReceipt(receipt, current).locked)
        assertFalse(frozen.afterLedgerReceipt(receipt, current).dirty)
    }
    @Test fun cancellationAfterApplyMeansAppliedAndDoesNotRollback() {
        val frozen = draft().beginSave(true).requestCancellation()
        val receipt = moodOperationReceipt(response(frozen), frozen.sessionId, frozen.ledgerOperation()!!)
        assertEquals("applied", receipt.state)
        val current = MoodRecord(frozen.date, frozen.x, frozen.y, frozen.note, fresh)
        assertEquals(fresh, frozen.afterLedgerReceipt(receipt, current).expectedUpdatedAt)
    }
    @Test fun terminalCancelledOrConflictRequiresExplicitRebaseAndFreshId() {
        for (status in listOf("cancelled", "conflict")) {
            val frozen = draft().beginSave(true)
            val next = frozen.afterLedgerReceipt(moodOperationReceipt(response(frozen, status, null), frozen.sessionId, frozen.ledgerOperation()!!), null)
            assertTrue(next.conflict && next.dirty)
            assertEquals(frozen.note, next.note)
            assertTrue(runCatching { next.beginSave(true) }.isFailure)
            val freshId = next.rebased(null).beginSave(true).operationId
            assertNotEquals(frozen.operationId, freshId)
        }
    }
    @Test fun deleteBindsReceiptToExactOriginalVersion() {
        val frozen = MoodDraft.from("synthetic-sid", "2026-10-30", MoodRecord("2026-10-30", 0.0, 0.0, "合成", old)).beginDelete(true)
        assertTrue(runCatching { frozen.afterLedgerReceipt(MoodOperationReceipt("applied", fresh), null) }.isFailure)
        assertFalse(frozen.afterLedgerReceipt(MoodOperationReceipt("applied", old), null).locked)
        assertTrue(frozen.afterLedgerReceipt(MoodOperationReceipt("applied", old), MoodRecord(frozen.date, 1.0, 1.0, "重建", fresh)).conflict)
    }
    @Test fun invalidPersistedIdentityCannotBecomeFreshEditableDraft() {
        val frozen = draft().beginSave(true)
        for (obj in listOf(JSONObject(frozen.encode()).put("operation_id", JSONObject.NULL), JSONObject(frozen.encode()).put("operation_json", "{}"), JSONObject(frozen.encode()).put("cancel_requested", "true")))
            assertNull(MoodDraft.decode(obj.toString()))
    }
}
