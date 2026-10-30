package cn.xinji.echo

import java.time.Instant
import java.time.ZoneId
import org.json.JSONObject

data class CompanionBoundary(val revision: Int, val mode: String, val until: String?, val timeZone: String, val suppressionRevision: Int) {
    val isPaused get() = mode != "active"
}
fun companionBoundary(obj: JSONObject): CompanionBoundary {
    require(listOf("revision", "mode", "until", "time_zone", "suppression_revision").all { obj.has(it) }) { "陪伴边界回执不完整，请更新服务后刷新。" }
    val revision = obj.opt("revision")
    val suppression = obj.opt("suppression_revision")
    require(revision is Int && revision >= 0 && suppression is Int && suppression >= 0) { "陪伴边界版本无效。" }
    val mode = obj.str("mode"); val until = obj.str("until").ifEmpty { null }; val zone = obj.str("time_zone")
    require(mode in setOf("active", "paused", "until") && runCatching { ZoneId.of(zone) }.isSuccess) { "陪伴边界状态或时区无效。" }
    require(if (mode == "until") until != null && runCatching { Instant.parse(until) }.isSuccess else until == null) { "陪伴边界时间无效。" }
    return CompanionBoundary(revision, mode, until, zone, suppression)
}
data class BoundaryChange(val sessionId: String, val expectedRevision: Int, val mode: String, val until: String?, val timeZone: String) {
    fun body() = json("session_id" to sessionId, "expected_revision" to expectedRevision, "confirmed" to true,
        "mode" to mode, "until" to until, "time_zone" to timeZone)
    fun matches(value: CompanionBoundary): Boolean = value.revision > expectedRevision && value.mode == mode && value.timeZone == timeZone &&
        (if (until == null) value.until == null else value.until != null && runCatching { Instant.parse(value.until) == Instant.parse(until) }.getOrDefault(false))
}
fun boundaryChange(sid: String, current: CompanionBoundary, mode: String, now: Instant = Instant.now(), zone: ZoneId = ZoneId.systemDefault()): BoundaryChange {
    require(mode in setOf("active", "paused", "until")) { "请选择有效的陪伴边界。" }
    val until = if (mode == "until") now.atZone(zone).toLocalDate().plusDays(1).atStartOfDay(zone).toInstant().toString() else null
    return BoundaryChange(sid, current.revision, mode, until, zone.id)
}
