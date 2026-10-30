package cn.xinji.echo

import cn.xinji.echo.shared.EchoSharedReference as Shared

/** Same feedback policy for the page and modal windows; it never refreshes or mutates data. */
fun updateFeedback(status: UpdateStatus, hasConversation: Boolean, supported: Boolean): String = if (!hasConversation) "" else when (status) {
    UpdateStatus.PENDING -> Shared.COPY_CONNECTION_SYNC_PENDING
    UpdateStatus.UPDATED -> Shared.COPY_CONNECTION_SYNC_UPDATED
    UpdateStatus.OFFLINE -> Shared.COPY_CONNECTION_SYNC_OFFLINE
    UpdateStatus.UNSUPPORTED -> Shared.COPY_CONNECTION_SYNC_UNSUPPORTED
    UpdateStatus.IDENTITY_CHANGED -> "服务身份有变化，已保留草稿；请到设置核对原连接。"
    UpdateStatus.CHECKING -> "正在检查更新…"
    UpdateStatus.IDLE -> if (supported) "" else Shared.COPY_CONNECTION_SYNC_UNSUPPORTED
}
fun visibleFeedback(notice: String, status: UpdateStatus, hasConversation: Boolean, supported: Boolean): List<String> =
    listOf(notice, updateFeedback(status, hasConversation, supported)).filter { it.isNotBlank() }.distinct()

/** Already-loaded current-scope text only. No vault, endpoint, API, or recovery operation. */
data class LocalDraftAccess(val contextId: String, val scope: String, val activeScope: String?, val available: Boolean, val sessionId: String? = null) {
    val allowed get() = available && contextId.isNotBlank() && scope.isNotBlank() && activeScope == scope
}
data class LocalDraftText(val key: String, val title: String, val text: String, val explanation: String)
data class LocalDraftReview(val contextId: String, val scope: String, val entries: List<LocalDraftText>)
fun localDraftReview(access: LocalDraftAccess, chat: String, memory: MemoryDraft?, followup: FollowupDraft?, mood: MoodDraft?): LocalDraftReview? {
    if (!access.allowed) return null
    fun sameSession(value: String) = access.sessionId == null || value == access.sessionId
    val entries = buildList {
        if (chat.isNotBlank()) add(LocalDraftText("chat", "对话草稿", chat, "本机保留的输入文字；此页不会发送，也不代表服务端已经收到。"))
        memory?.takeIf { sameSession(it.sessionId) && it.text.isNotBlank() }?.let {
            add(LocalDraftText("memory", "记忆草稿", it.text, if (it.uncertain) "此前保存结果仍待核对；只展示本机文字，不会再次保存。" else "仅展示本机副本，尚未核对服务端当前版本。"))
        }
        followup?.takeIf { sameSession(it.sessionId) && it.content.isNotBlank() }?.let {
            val status = if (it.started || it.requestId.isNotEmpty()) "此前保存结果仍待核对；不会恢复、取消或重发原请求。" else "此页不会创建跟进或通知。"
            add(LocalDraftText("followup", "跟进文字", it.content, status + if (it.dueAt.isNotEmpty()) " 原定时间：${it.dueAt} · ${it.timeZone}" else " 尚未选择时间。"))
        }
        mood?.takeIf { sameSession(it.sessionId) && (it.note.isNotBlank() || it.xChosen || it.yChosen || it.dirty || it.locked) }?.let {
            val positions = "感受：${if (it.xChosen) it.x.toString() else "尚未选择"}；精力：${if (it.yChosen) it.y.toString() else "尚未选择"}"
            val status = if (it.locked) "此前提交结果仍待核对；此页不查询、重试或取消。" else "仅展示本机副本；服务端是否已有记录需联网核对。"
            add(LocalDraftText("mood", "心情本机副本 · ${it.date}", it.note.ifBlank { positions }, "$positions。$status"))
        }
    }
    return entries.takeIf { it.isNotEmpty() }?.let { LocalDraftReview(access.contextId, access.scope, it) }
}
fun mayPresentDraftReview(review: LocalDraftReview, current: LocalDraftAccess) = current.allowed && review.contextId == current.contextId && review.scope == current.scope
