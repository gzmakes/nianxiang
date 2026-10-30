package cn.xinji.echo

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class MoodRulesTest {
    private val stamp = "2026-10-30T00:00:00.000001+00:00"
    private fun record(note: String = "合成心情") = MoodRecord("2026-10-30", .4, -.3, note, stamp)
    private fun raw(r: MoodRecord = record()) = json("date" to r.date, "x" to r.x, "y" to r.y, "note" to r.note, "updated_at" to r.updatedAt)
    private fun draft() = MoodDraft("synthetic-sid", "2026-10-30", .4, -.3, "合成心情", true, true, dirty = true)
    @Test fun neutralDefaultsAreNotImplicitChoices() {
        val empty = MoodDraft("s", "2026-10-30")
        assertTrue(runCatching { empty.beginSave() }.isFailure)
        assertTrue(runCatching { empty.copy(xChosen = true).beginSave() }.isFailure)
        assertEquals("save", empty.copy(xChosen = true, yChosen = true).beginSave().operation)
    }
    @Test fun malformedListCannotBecomeAnAbsenceProof() {
        for (obj in listOf(JSONObject(), json("moods" to "wrong"), json("moods" to org.json.JSONArray(listOf(raw(), raw())))))
            assertTrue(runCatching { moodRecords(obj) }.isFailure)
        assertTrue(moodRecords(json("moods" to org.json.JSONArray())).isEmpty())
    }
    @Test fun strictRecordRejectsMissingBoolNonFiniteOrBadDate() {
        for (obj in listOf(raw().put("x", true), raw().put("date", "2026-02-30"), raw().put("updated_at", "unknown"), raw().also { it.remove("note") }))
            assertTrue(runCatching { moodRecord(obj) }.isFailure)
        assertTrue(runCatching { draft().copy(x = Double.NaN).beginSave() }.isFailure)
    }
    @Test fun receiptMustMatchDayCoordinatesTextAndNewVersion() {
        val frozen = draft().beginSave()
        assertTrue(frozen.saveReceipt(raw()))
        for (obj in listOf(raw().put("date", "2026-10-29"), raw().put("x", .6), raw().put("y", .8), raw().put("note", "另一条"))) assertFalse(frozen.saveReceipt(obj))
        assertFalse(frozen.copy(expectedUpdatedAt = stamp).saveReceipt(raw()))
    }
    @Test fun unknownBodySurvivesSerializationAndCannotResubmit() {
        val frozen = draft().beginSave()
        val restored = MoodDraft.decode(frozen.encode())!!
        assertEquals(frozen, restored)
        assertEquals(frozen.body().toString(), restored.body().toString())
        assertTrue(runCatching { restored.beginSave() }.isFailure)
        assertEquals(restored, restored.afterFailure(null))
        assertEquals(restored, restored.afterFailure(500))
    }
    @Test fun definiteConflictPreservesDraftUntilExplicitRebase() {
        val pending = draft().beginSave().afterFailure(409)
        assertTrue(pending.conflict && pending.locked)
        val latest = record("另一窗口的内容")
        val rebased = pending.rebased(latest)
        assertEquals("合成心情", rebased.note)
        assertEquals(latest.updatedAt, rebased.expectedUpdatedAt)
        assertFalse(rebased.locked)
        assertEquals("save", rebased.beginSave().operation)
    }
    @Test fun definiteInitialRejectionCanUnlockButNeverChangesExpectedVersion() {
        val pending = draft().copy(expectedUpdatedAt = stamp).beginSave()
        val rejected = pending.afterFailure(422)
        assertFalse(rejected.locked)
        assertEquals(stamp, rejected.expectedUpdatedAt)
        assertEquals(pending.note, rejected.note)
    }
    @Test fun deletionBindsExactReadVersionAndSurvivesRestart() {
        assertTrue(runCatching { draft().beginDelete() }.isFailure)
        val pending = MoodDraft.from("s", "2026-10-30", record()).beginDelete()
        assertEquals("delete", pending.operation)
        assertEquals(pending, MoodDraft.decode(pending.encode()))
        assertEquals(stamp, pending.expectedUpdatedAt)
    }
    @Test fun explicitChatTextUsesSavedNoteWithoutImpliedDiagnosis() {
        val text = moodChatText(record("合成原文\n由我决定"))
        assertTrue(text.contains("2026-10-30") && text.contains("合成原文\n由我决定"))
        assertFalse(text.contains("诊断"))
    }
    @Test fun invalidPersistedOperationOrDateIsNotLoaded() {
        assertNull(MoodDraft.decode(draft().encode().replace("2026-10-30", "2026-02-30")))
        assertNull(MoodDraft.decode(JSONObject(draft().encode()).put("operation", "retry").toString()))
    }
}
