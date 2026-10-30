package cn.xinji.echo

import java.time.Instant
import java.time.ZoneId
import java.util.UUID
import org.json.JSONObject
import cn.xinji.echo.shared.EchoSharedReference as Shared

private fun sameInstant(a: String?, b: String?) = a != null && b != null && runCatching { Instant.parse(a) == Instant.parse(b) }.getOrDefault(false)
data class Followup(
    val id: String, val sessionId: String, val requestId: String, val content: String,
    val dueAt: String, val status: String, val due: Boolean, val repeatRule: String = "once",
    val paused: Boolean = false, val quiet: Boolean = false, val timeZone: String = "UTC",
    val quietStart: String? = null, val quietEnd: String? = null,
    val createdDueAt: String = dueAt, val lastOccurrenceAt: String? = null,
    val allowContact: Boolean = false, val contactWindowMinutes: Int = 30,
    val contactTopic: String = content, val contactExpiresAt: String? = null,
    val contactEligible: Boolean = false, val contactReason: String? = null, val pausedKnown: Boolean = true
) {
    val supportsNativeTransitions get() = repeatRule in setOf("once", "daily") && status in setOf("pending", "done", "cancelled")
}
fun followup(obj: JSONObject) = Followup(
    obj.str("id"), obj.str("session_id"), obj.str("request_id"), obj.str("content"),
    obj.str("due_at"), obj.str("status"), obj.optBoolean("due"), obj.str("repeat_rule", "once"),
    obj.opt("paused") == true, obj.opt("quiet") == true, obj.str("time_zone", "UTC"),
    obj.str("quiet_start").ifEmpty { null }, obj.str("quiet_end").ifEmpty { null },
    obj.str("created_due_at").ifEmpty { obj.str("due_at") }, obj.str("last_occurrence_at").ifEmpty { null },
    obj.opt("allow_contact") == true, obj.optInt("contact_window_minutes", 30),
    obj.str("contact_topic").ifEmpty { obj.str("content") }, obj.str("contact_expires_at").ifEmpty { null },
    obj.opt("contact_eligible") == true, obj.str("contact_reason").ifEmpty { null }, obj.opt("paused") is Boolean
)
fun followups(obj: JSONObject) = obj.rows("followups").map(::followup)
data class FollowupDraft(
    val sessionId: String, val content: String = "", val dueAt: String = "", val requestId: String = "", val started: Boolean = false,
    val repeatRule: String = "once", val timeZone: String = "UTC", val quietStart: String = "", val quietEnd: String = "",
    val allowContact: Boolean = false, val contactWindowMinutes: Int = 30, val contactTopic: String = "",
    val contactFieldsIncluded: Boolean = false, val wireVersion: Int = 1
) {
    fun prepared(now: Instant = Instant.now()): FollowupDraft {
        if (requestId.isNotEmpty()) return this
        require(content.isNotBlank() && content.codePointCount(0, content.length) <= 1000) { "请填写 1–1000 字的跟进内容。" }
        require(runCatching { Instant.parse(dueAt).isAfter(now) }.getOrDefault(false)) { "请选择未来的日期与时间。" }
        require(repeatRule in setOf("once", "daily")) { "请选择一次或每天。" }
        require(runCatching { ZoneId.of(timeZone) }.isSuccess) { "请填写有效时区，例如 Asia/Shanghai。" }
        require((quietStart.isEmpty() && quietEnd.isEmpty()) || (listOf(quietStart, quietEnd).all { it.matches(Regex("(?:[01]\\d|2[0-3]):[0-5]\\d")) } && quietStart != quietEnd)) { "安静时段需同时填写两个不同的有效时间。" }
        require(contactWindowMinutes in 5..180) { "轻问窗口需为 5–180 分钟。" }
        require(!allowContact || contactFieldsIncluded) { "当前服务尚未支持约定窗口。" }
        val topic = contactTopic.trim().ifEmpty { content.trim() }
        require(topic.codePointCount(0, topic.length) in 1..1000) { "请填写 1–1000 字的话题范围。" }
        return copy(content = content.trim(), contactTopic = topic, requestId = UUID.randomUUID().toString(), wireVersion = 1)
    }
    fun body(): JSONObject {
        val out = json("session_id" to sessionId, "content" to content, "due_at" to dueAt, "request_id" to requestId, "confirmed" to true)
        if (wireVersion >= 1) {
            out.put("repeat_rule", repeatRule).put("time_zone", timeZone)
                .put("quiet_start", quietStart.ifEmpty { null } ?: JSONObject.NULL).put("quiet_end", quietEnd.ifEmpty { null } ?: JSONObject.NULL)
            if (contactFieldsIncluded) out.put("allow_contact", allowContact).put("contact_window_minutes", contactWindowMinutes)
                .put("contact_topic", contactTopic.ifBlank { content })
        }
        return out
    }
    fun encode() = body().put("started", started).put("wire_version", wireVersion).put("contact_fields_included", contactFieldsIncluded).put("contact_topic", contactTopic).toString()
    fun beginSave(now: Instant = Instant.now()): FollowupSaveAttempt = FollowupSaveAttempt(prepared(now).copy(started = true), initialAttempt = requestId.isEmpty() && !started)
    fun matching(records: List<Followup>): Followup? = records.find {
        it.sessionId == sessionId && it.requestId == requestId && requestId.isNotEmpty() && it.supportsNativeTransitions &&
        it.content == content && sameInstant(if (it.repeatRule == "daily") it.createdDueAt else it.dueAt, dueAt) &&
        it.repeatRule == (if (wireVersion == 0) "once" else repeatRule) &&
        it.timeZone == (if (wireVersion == 0) "UTC" else timeZone) &&
        it.quietStart == quietStart.ifEmpty { null } && it.quietEnd == quietEnd.ifEmpty { null } &&
        (!contactFieldsIncluded || (it.allowContact == allowContact && it.contactWindowMinutes == contactWindowMinutes && it.contactTopic == contactTopic.ifBlank { content }))
    }
    companion object {
        fun decode(value: String): FollowupDraft? = runCatching {
            val obj = JSONObject(value); val id = obj.str("request_id")
            FollowupDraft(obj.getString("session_id"), obj.str("content"), obj.str("due_at"), id,
                if (obj.has("started")) obj.optBoolean("started") else id.isNotEmpty(),
                obj.str("repeat_rule", "once"), obj.str("time_zone", "UTC"), obj.str("quiet_start"), obj.str("quiet_end"),
                obj.opt("allow_contact") == true, obj.optInt("contact_window_minutes", 30), obj.str("contact_topic"),
                obj.opt("contact_fields_included") == true, obj.optInt("wire_version", 0))
        }.getOrNull()
    }
}
data class FollowupSaveAttempt(val request: FollowupDraft, val initialAttempt: Boolean) {
    fun afterFailure(httpStatus: Int? = null, errorCode: String = ""): FollowupDraft {
        val rejected = (httpStatus == 400 && errorCode in setOf("invalid_request", "confirmation_required")) || (httpStatus == 422 && errorCode == "validation_error")
        return if (initialAttempt && rejected) request.copy(requestId = "", started = false) else request
    }
}
fun followupStateLabel(item: Followup) = when (item.status) {
    "pending" -> when { item.paused -> "已暂停"; item.quiet -> "安静时段"; item.due -> "已到时间"; else -> "待跟进" }
    "done" -> "已完成"; "cancelled" -> "已取消"; else -> "状态待核对"
}
fun followupDefinitiveRejection(status: Int, firstAttempt: Boolean): Boolean = firstAttempt && status in setOf(400, 422)
fun followupTransitionRequest(item: Followup, target: String): SourceRequest {
    require(item.supportsNativeTransitions && item.status == "pending") { "此跟进状态或重复方式未知，请刷新核对。" }
    require(target in setOf("done", "cancelled", "paused", "resumed")) { "无效的跟进状态。" }
    require(target != "done" || item.repeatRule != "daily" || item.due) { "这次每日跟进尚未到时间。" }
    val body = json("session_id" to item.sessionId, "status" to target)
    if (target == "done" && item.repeatRule == "daily") body.put("occurrence_at", item.dueAt)
    return SourceRequest("/api/followups/" + encoded(item.id) + "/transition", body)
}
fun followupTransitionMatches(item: Followup, target: String, receipt: Followup): Boolean {
    if (receipt.id != item.id || receipt.sessionId != item.sessionId || receipt.requestId != item.requestId ||
        receipt.content != item.content || receipt.repeatRule != item.repeatRule || receipt.timeZone != item.timeZone ||
        receipt.quietStart != item.quietStart || receipt.quietEnd != item.quietEnd || !sameInstant(receipt.createdDueAt, item.createdDueAt)) return false
    return when (target) {
        "done" -> if (item.repeatRule == "daily") receipt.status == "pending" && sameInstant(receipt.lastOccurrenceAt, item.dueAt) &&
            runCatching { Instant.parse(receipt.dueAt).isAfter(Instant.parse(item.dueAt)) }.getOrDefault(false) else receipt.status == "done"
        "cancelled" -> receipt.status == "cancelled"
        "paused", "resumed" -> receipt.status == "pending" && receipt.pausedKnown && receipt.paused == (target == "paused") && sameInstant(receipt.dueAt, item.dueAt)
        else -> false
    }
}


fun followupTimeLabel(value: String, timeZone: String = ZoneId.systemDefault().id): String = runCatching {
    java.time.format.DateTimeFormatter.ofPattern("MM月dd日 HH:mm", java.util.Locale.CHINA)
        .format(Instant.parse(value).atZone(ZoneId.of(timeZone)))
}.getOrDefault("时间待核对")
fun followupContactLabel(item: Followup): String = when {
    !item.allowContact -> Shared.COPY_FOLLOWUP_CONTACT_DEFAULT
    item.contactReason in setOf("expired", "claim_expired") -> Shared.COPY_FOLLOWUP_CONTACT_EXPIRED
    item.contactReason in setOf("boundary_changed", "suppressed_occurrence") -> "原许可已失效，需重新约定"
    item.contactReason in setOf("boundary_paused", "boundary_until", "paused") -> "当前先安静，暂不轻问"
    item.contactReason in setOf("quiet", "item_quiet") -> "安静时段内，不主动轻问"
    item.contactReason in setOf("already_claimed", "topic_window_claimed") -> "这次不会再主动问，待办仍可查看"
    item.contactReason in setOf("completed", "contact_not_allowed") -> "当前不再主动轻问"
    item.contactReason == "not_due" -> "已约定，尚未到时间"
    item.contactReason in setOf("daily_limit", "cooldown") -> "本次暂不轻问，错过窗口不补问"
    item.contactEligible -> "窗口内可轻问一次"
    else -> "轻问状态暂时未能核对"
}
