package cn.xinji.echo

import java.time.Instant
import java.time.LocalDate
import org.json.JSONObject

/** A self-report record, deliberately separate from model context and memories. */
data class MoodRecord(val date: String, val x: Double, val y: Double, val note: String, val updatedAt: String)
private fun validMoodDay(day: String) = runCatching { LocalDate.parse(day).toString() == day }.getOrDefault(false)
private fun validMoodVersion(value: String?) = value != null && runCatching { Instant.parse(value) }.isSuccess
fun moodRecord(obj: JSONObject): MoodRecord {
    val date = obj.opt("date") as? String ?: error("记录缺少日期。")
    val x = (obj.opt("x") as? Number)?.toDouble() ?: error("记录缺少感受位置。")
    val y = (obj.opt("y") as? Number)?.toDouble() ?: error("记录缺少精力位置。")
    val note = obj.opt("note") as? String ?: error("记录缺少原文。")
    val version = obj.opt("updated_at") as? String ?: error("记录缺少版本。")
    require(validMoodDay(date) && x.isFinite() && y.isFinite() && x in -1.0..1.0 && y in -1.0..1.0 && validMoodVersion(version)) { "记录格式尚不能核对。" }
    return MoodRecord(date, x, y, note, version)
}
fun moodRecords(obj: JSONObject): List<MoodRecord> {
    val rows = obj.optJSONArray("moods") ?: error("没有收到完整的心情记录列表。")
    val list = (0 until rows.length()).map { moodRecord(rows.getJSONObject(it)) }
    require(list.map { it.date }.distinct().size == list.size) { "记录日期重复，暂不用于核对。" }
    return list.sortedByDescending { it.date }
}
data class MoodDraft(
    val sessionId: String, val date: String,
    val x: Double = 0.0, val y: Double = 0.0, val note: String = "",
    val xChosen: Boolean = false, val yChosen: Boolean = false,
    val expectedUpdatedAt: String? = null, val dirty: Boolean = false,
    val operation: String? = null, val conflict: Boolean = false,
    val operationId: String? = null, val operationJson: String? = null, val cancelRequested: Boolean = false
) {
    val locked get() = operation != null || conflict
    fun validate() {
        require(sessionId.isNotBlank() && validMoodDay(date)) { "请核对日期和当前连接。" }
        require(xChosen && yChosen && x.isFinite() && y.isFinite() && x in -1.0..1.0 && y in -1.0..1.0) { "请分别选择感受和精力，也可以明确选择中间位置。" }
        require(note.codePointCount(0, note.length) <= 1000) { "想说的话最多1000字。" }
        require(expectedUpdatedAt == null || validMoodVersion(expectedUpdatedAt)) { "记录版本尚不能核对。" }
    }
    fun beginSave(useLedger: Boolean = false): MoodDraft { require(!locked); validate(); return freeze("save", useLedger) }
    fun beginDelete(useLedger: Boolean = false): MoodDraft { require(!locked && validMoodVersion(expectedUpdatedAt)); return freeze("delete", useLedger) }
    private fun freeze(kind: String, useLedger: Boolean): MoodDraft {
        if (!useLedger) return copy(operation = kind)
        val identity = MoodOperation.capture(this, kind)
        return copy(operation = kind, operationId = identity.requestId, operationJson = identity.raw)
    }
    fun ledgerOperation(): MoodOperation? {
        if (operationId == null && operationJson == null) { require(!cancelRequested); return null }
        require(operationId != null && operationJson != null && operation in listOf("save", "delete"))
        val identity = MoodOperation(operationId, operationJson, operation!!)
        val inner = JSONObject(operationJson)
        require(inner.keys().asSequence().toSet() == if (operation == "save") setOf("kind", "date", "expected_updated_at", "x", "y", "note") else setOf("kind", "date", "expected_updated_at"))
        require(inner.opt("kind") == operation && inner.opt("date") == date)
        require(if (expectedUpdatedAt == null) inner.opt("expected_updated_at") === JSONObject.NULL else inner.opt("expected_updated_at") == expectedUpdatedAt)
        if (operation == "save") require((inner.opt("x") as? Number)?.toDouble() == x && (inner.opt("y") as? Number)?.toDouble() == y && inner.opt("note") == note)
        return identity
    }
    fun requestCancellation(): MoodDraft { require(ledgerOperation() != null); return copy(cancelRequested = true) }
    fun body(): JSONObject { validate(); return json("session_id" to sessionId, "x" to x, "y" to y, "note" to note, "confirmed" to true, "expected_updated_at" to expectedUpdatedAt) }
    fun matches(record: MoodRecord?) = record != null && record.date == date && record.x == x && record.y == y && record.note == note && record.updatedAt != expectedUpdatedAt
    fun saveReceipt(obj: JSONObject) = runCatching { matches(moodRecord(obj)) }.getOrDefault(false)
    fun afterFailure(status: Int?): MoodDraft = when (status) {
        409 -> copy(conflict = true) // keep frozen body; an explicit reload/rebase is required
        400, 422 -> copy(operation = null) // only this definite response to the initial attempt
        else -> this
    }
    fun rebased(record: MoodRecord?): MoodDraft {
        require(record == null || record.date == date)
        return copy(expectedUpdatedAt = record?.updatedAt, operation = null, conflict = false, dirty = true, operationId = null, operationJson = null, cancelRequested = false)
    }
    fun encode() = json("session_id" to sessionId, "date" to date, "x" to x, "y" to y, "note" to note,
        "x_chosen" to xChosen, "y_chosen" to yChosen, "expected_updated_at" to expectedUpdatedAt,
        "dirty" to dirty, "operation" to operation, "conflict" to conflict,
        "operation_id" to operationId, "operation_json" to operationJson, "cancel_requested" to cancelRequested).toString()
    companion object {
        fun from(sessionId: String, date: String, record: MoodRecord?) = MoodDraft(sessionId, date,
            record?.x ?: 0.0, record?.y ?: 0.0, record?.note.orEmpty(), record != null, record != null, record?.updatedAt)
        fun decode(raw: String): MoodDraft? = runCatching {
            val o = JSONObject(raw)
            require(!o.has("cancel_requested") || o.opt("cancel_requested") is Boolean)
            val draft = MoodDraft(o.getString("session_id"), o.getString("date"), o.getDouble("x"), o.getDouble("y"), o.getString("note"),
                o.opt("x_chosen") == true, o.opt("y_chosen") == true, o.str("expected_updated_at").ifEmpty { null }, o.opt("dirty") == true,
                o.str("operation").ifEmpty { null }, o.opt("conflict") == true,
                o.str("operation_id").ifEmpty { null }, o.str("operation_json").ifEmpty { null }, o.opt("cancel_requested") == true)
            require(validMoodDay(draft.date) && draft.x.isFinite() && draft.y.isFinite() && draft.operation in listOf(null, "save", "delete"))
            if (draft.operation == "save") draft.validate()
            if (draft.operation == "delete") require(validMoodVersion(draft.expectedUpdatedAt))
            draft.ledgerOperation() // never invent an identity for a legacy pending draft
            draft
        }.getOrNull()
    }
}
fun moodChatText(record: MoodRecord): String = "我想聊聊自己在 ${record.date} 留下的感受：${record.note.ifBlank { "感受位置 ${record.x}，精力位置 ${record.y}" }}。这是我自己选择的记录，想从这里慢慢说。"
