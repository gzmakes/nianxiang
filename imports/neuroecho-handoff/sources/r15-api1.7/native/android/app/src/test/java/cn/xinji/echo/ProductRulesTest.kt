package cn.xinji.echo

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ProductRulesTest {
    private fun memory(id: String = "mem", text: String = "想把回答写短一点", version: Int = 2, status: String = "candidate") = Memory(id, text, "fact", status, version, "用户手动添加", "")
    @Test fun oneSearchFindsMessagesAndMemoryWithoutDeletedRecords() {
        val c = Conversation("canonical", listOf(Message("msg", "user", "想写短一点")), listOf(memory(), memory("gone", "写短一点", status = "deleted")), emptyList())
        val hits = searchConversation(c, " 短一点 ")
        assertEquals(listOf(SearchKind.MESSAGE, SearchKind.MEMORY), hits.map { it.kind })
        assertEquals(listOf("msg", "mem"), hits.map { it.id })
        assertTrue(searchConversation(c, "").isEmpty())
    }
    @Test fun topicsSurviveSerializationWithoutChangingConversation() {
        val tagged = TopicPolicy.assign(emptyMap(), "message-1", " 周五方案 ")
        val restored = TopicPolicy.decode(JSONObject(tagged).toString())
        assertEquals("周五方案", TopicPolicy.label(restored, "message-1"))
        assertTrue(TopicPolicy.matches(restored, "message-1", "全部"))
        assertFalse(TopicPolicy.matches(restored, "message-1", "日常"))
        assertEquals("日常", TopicPolicy.label(restored, "other"))
        assertEquals(listOf("全部", "日常", "周五方案"), TopicPolicy.labels(restored))
    }
    @Test fun invalidAndCorruptTopicsDoNotCreateFilters() {
        assertTrue(TopicPolicy.decode("bad").isEmpty())
        assertThrows(IllegalArgumentException::class.java) { TopicPolicy.assign(emptyMap(), "msg", "全部") }
        assertThrows(IllegalArgumentException::class.java) { TopicPolicy.assign(emptyMap(), "local-unsent", "日常") }
        assertEquals("😀".repeat(20), TopicPolicy.label(TopicPolicy.assign(emptyMap(), "msg", "😀".repeat(20)), "msg"))
    }
    @Test fun noNewGrantCanBeStartedFromSourcePolicy() {
        for (id in listOf("feishu", "github", "apple_calendar", "apple_reminders")) {
            assertFalse(SourcePolicy.mayPreview(id, "needs_auth", "https://example.test/doc"))
            assertFalse(SourcePolicy.mayPreview(id, "needs_click", "https://example.test/doc"))
        }
        assertFalse(SourcePolicy.mayPreview("gmail", "ready", ""))
        assertFalse(SourcePolicy.mayPreview("rokid", "ready", ""))
    }
    @Test fun explicitlyChosenNotionPageAndGitDirectoryUseReadonlyExistingPaths() {
        assertTrue(SourcePolicy.mayPreview("notion", "needs_config", "https://notion.so/page"))
        val notion = SourcePolicy.preview("notion", "https://notion.so/page")
        assertEquals("/api/notion/preview", notion.path)
        assertEquals("cli", notion.body.getString("method"))
        assertFalse(notion.body.has("token"))
        assertFalse(SourcePolicy.mayPreview("git", "ready", "git log"))
        assertTrue(SourcePolicy.mayPreview("git", "needs_config", "/Users/synthetic/repo"))
        assertEquals("/Users/synthetic/repo", SourcePolicy.preview("git", "/Users/synthetic/repo").body.getString("path"))
    }
    @Test fun sourceAttachUsesExactlyTheReviewedTokenAndCanonicalId() {
        for (id in SourcePolicy.supported) {
            val request = SourcePolicy.attach(id, "https://example.test/doc", "reviewed-once", "canonical")
            assertEquals("reviewed-once", request.body.getString("preview_id"))
            assertEquals("canonical", request.body.getString("session_id"))
            assertFalse(request.path.contains("auth"))
        }
        assertEquals("/api/notion/start", SourcePolicy.attach("notion", "", "p", "s").path)
    }
    @Test fun conflictRetainsTextAndRequiresExplicitVersionRebase() {
        val draft = MemoryDraft.editing(memory()).copy(text = "我的未保存修改", sessionId = "canonical")
        val conflicted = draft.withConflict(memory(text = "另一端已改", version = 3))
        val restored = MemoryDraft.decode(conflicted.encode())!!
        assertEquals("我的未保存修改", restored.text)
        assertEquals(2, restored.expectedVersion)
        assertTrue(restored.conflict)
        assertEquals("另一端已改", restored.serverText)
        val reviewed = restored.rebase()
        assertEquals(3, reviewed.expectedVersion)
        assertEquals("我的未保存修改", reviewed.text)
        assertFalse(reviewed.conflict)
        assertEquals("canonical", reviewed.sessionId)
    }
    @Test fun deletedMemoryCannotBeAutomaticallyRecreatedByConflictRebase() {
        val missing = MemoryDraft.editing(memory()).withConflict(null)
        assertThrows(IllegalArgumentException::class.java) { missing.rebase() }
        assertEquals("mem", missing.id)
    }
    @Test fun memoryConfirmAndDeleteCarryTheDisplayedVersion() {
        val value = memory(version = 7)
        val confirm = memoryPatchRequest(value, confirm = true)
        assertEquals(7, confirm.body.getInt("expected_version"))
        assertEquals("confirmed", confirm.body.getString("status"))
        assertFalse(confirm.body.has("text"))
        assertEquals("/api/memory/mem?expected_version=7", memoryDeletePath(value))
    }
    @Test fun statusTextDescribesRealPendingAndInputState() {
        assertEquals("在听你说", presenceLabel(null, false, "输入中"))
        assertEquals("发送结果待核对", presenceLabel(PendingTurn("stable", "s", "hello"), false, ""))
        assertEquals("正在整理回复", presenceLabel(PendingTurn("stable", "s", "hello"), true, "", chatSending = true))
        assertEquals("发送结果待核对", presenceLabel(PendingTurn("stable", "s", "hello"), true, ""))
        assertEquals("正在核对停止请求", presenceLabel(PendingTurn("stable", "s", "hello", cancelWanted = true), false, ""))
        assertEquals("安静陪着", presenceLabel(null, false, ""))
    }
    @Test fun newComfortUsesSharedDefaultsWithoutChangingExistingExplicitPreferences() {
        assertEquals(Comfort(false, false, .7f), Comfort())
        assertEquals(Comfort(true, true, .45f), Comfort(reduceMotion = true, reduceTransparency = true, lightIntensity = .45f))
    }
    @Test fun targetedDeliveryStopRequiresFlagAndExactCurrentAssistant() {
        val first = Message("old", "assistant", "旧首段", deliveryPending = true)
        val latest = Message("latest", "assistant", "新首段", deliveryPending = true)
        val c = Conversation("canonical", listOf(first, latest), emptyList(), emptyList())
        val attempt = DeliveryStopAttempt("endpoint", "canonical", "latest")
        assertTrue(attempt.canStart(true, "endpoint", c))
        assertFalse(attempt.canStart(false, "endpoint", c))
        assertFalse(attempt.canStart(true, "other", c))
        assertFalse(attempt.canStart(true, "endpoint", c.copy(id = "other")))
        assertFalse(attempt.copy(messageId = "old").canStart(true, "endpoint", c))
        assertFalse(attempt.canStart(true, "endpoint", c.copy(messages = listOf(latest.copy(role = "user")))))
        assertFalse(attempt.canStart(true, "endpoint", c.copy(messages = c.messages + Message("user-new", "user", "新问题"))))
        assertEquals("/api/session/canonical/delivery/stop", attempt.request().path)
        assertEquals("latest", attempt.request().body.getString("message_id"))
    }
    @Test fun falseUnknownAndLateDeliveryStopReceiptsCannotClaimSuccess() {
        val attempt = DeliveryStopAttempt("endpoint", "canonical", "old")
        val ok = JSONObject("""{"ok":true,"stopped":true,"message_id":"old","reason":"stopped"}""")
        val c = Conversation("canonical", listOf(Message("old", "assistant", "首段")), emptyList(), emptyList())
        assertTrue(attempt.reconciled(ok, c))
        for (receipt in listOf(null, JSONObject(), JSONObject(ok.toString()).put("stopped", false), JSONObject(ok.toString()).put("stopped", "true"), JSONObject(ok.toString()).put("ok", "true"), JSONObject(ok.toString()).put("message_id", "latest"), JSONObject(ok.toString()).put("reason", "not_current"))) assertFalse(attempt.reconciled(receipt, c))
        assertFalse(attempt.reconciled(ok, c.copy(id = "other")))
        assertFalse(attempt.reconciled(ok, c.copy(messages = c.messages + Message("latest", "assistant", "新首段", deliveryPending = true))))
        assertFalse(attempt.reconciled(ok, c.copy(messages = listOf(c.messages.single().copy(deliveryPending = true)))))
    }

    @Test fun rejectedQuoteOnlyPrefillsAnUnconfirmedManualCandidateAfterExplicitChoice() {
        val message = Message("u", "user", "今天有点累，但想把项目做好。")
        val c = Conversation("canonical", listOf(message), emptyList(), emptyList())
        val review = quoteReviewAfterRejection(message, c, 409)!!
        assertEquals(message.text, review.text)
        val draft = review.candidate(c)
        assertNull(draft.id); assertEquals(message.text, draft.text); assertEquals("canonical", draft.sessionId)
        val request = manualMemoryRequest(draft, c.id)
        assertEquals("/api/memory", request.path); assertEquals("用户手动添加", request.body.getString("source"))
        assertFalse(request.body.has("confirm")); assertFalse(request.body.has("status")); assertFalse(request.body.has("source_message_id"))
        for (status in listOf(200, 400, 408, 422, 500, 503)) assertNull(quoteReviewAfterRejection(message, c, status))
    }
    @Test fun quoteReviewCannotUseAssistantStaleTextOrAnotherConversation() {
        val message = Message("u", "user", "原话")
        val c = Conversation("canonical", listOf(message), emptyList(), emptyList())
        assertNull(quoteReview(message.copy(role = "assistant"), c))
        assertNull(quoteReview(message.copy(text = "页面陈旧文字"), c))
        val review = quoteReview(message, c)!!
        assertThrows(IllegalArgumentException::class.java) { review.candidate(c.copy(id = "another")) }
        assertThrows(IllegalArgumentException::class.java) { review.candidate(c.copy(messages = emptyList())) }
    }
    @Test fun directQuoteReceiptRequiresConfirmedLiteralProvenanceBeforeSuccess() {
        val review = QuoteMemoryReview("canonical", "u", "我通常喜欢喝茶。")
        val saved = Memory("m", "我通常喜欢喝茶", "fact", "confirmed", 1, "对话原话 · 用户选存", "", "u")
        assertTrue(quoteReceiptMatches(review, saved))
        assertFalse(quoteReceiptMatches(review, saved.copy(status = "candidate")))
        assertFalse(quoteReceiptMatches(review, saved.copy(sourceMessageId = "other")))
        assertFalse(quoteReceiptMatches(review, saved.copy(source = "用户手动添加")))
        assertFalse(quoteReceiptMatches(review, saved.copy(text = "模型推测")))
        assertTrue(quoteRequest(review).body.getBoolean("confirm"))
    }
    @Test fun automaticOfferRequiresOptedInTurnAndExactUserLiteral() {
        val message = Message("u", "user", "我通常喜欢喝茶。")
        val c = Conversation("canonical", listOf(message), emptyList(), emptyList())
        val result = JSONObject("""{"user_message_id":"u","memory_proposal":{"message_id":"u","quote":"我通常喜欢喝茶"}}""")
        val optedIn = PendingTurn("stable", "canonical", message.text, memoryProposals = true)
        assertEquals(message.text, quoteOffer(result, optedIn, c)!!.text)
        assertNull(quoteOffer(result, optedIn.copy(memoryProposals = false), c))
        assertNull(quoteOffer(JSONObject(result.toString()).put("user_message_id", "old-user"), optedIn, c))
        assertNull(quoteOffer(result, optedIn, c.copy(id = "other")))
        assertNull(quoteOffer(JSONObject("""{"user_message_id":"u","memory_proposal":{"message_id":"u","quote":"模型扩展推测"}}"""), optedIn, c))
        assertNull(quoteOffer(result, optedIn, c.copy(messages = listOf(message.copy(role = "assistant")))))
    }

}
