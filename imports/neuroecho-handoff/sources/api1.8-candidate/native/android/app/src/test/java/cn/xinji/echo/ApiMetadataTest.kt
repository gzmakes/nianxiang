package cn.xinji.echo

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ApiMetadataTest {
    @Test fun structuredDocumentProvenanceSurvivesDecoding() {
        val item = memory(JSONObject("""{"id":"mem","text":"合成来源记忆","kind":"fact","status":"candidate","version":4,"source":"合成文档","source_attachment_id":"source-1"}"""))
        assertEquals("source-1", item.sourceAttachmentId)
        assertEquals(4, item.version)
        assertEquals("", item.sourceMessageId)
    }
    @Test fun conversationRetainsSourceMessageLinkAndActualMessageTime() {
        val result = conversation(JSONObject("""{
            "session":{"id":"canonical"},
            "messages":[{"id":"msg-original","role":"user","text":"合成原话","created_at":"2026-10-30T09:10:00+08:00"}],
            "memories":[{"id":"memory-1","text":"合成记忆","kind":"fact","status":"confirmed","version":1,"source":"对话原话 · 用户选存","created_at":"2026-10-30T09:11:00+08:00","source_message_id":"msg-original"}]
        }"""))
        val memory = result.memories.single()
        assertEquals("msg-original", memory.sourceMessageId)
        assertEquals("2026-10-30T09:10:00+08:00", result.messages.single { it.id == memory.sourceMessageId }.createdAt)
        assertEquals("2026-10-30T09:11:00+08:00", memory.createdAt)
        assertEquals("对话原话 · 用户选存", memory.source)
    }

    @Test fun legacyPayloadMissingOptionalMetadataRemainsCompatible() {
        val result = conversation(JSONObject("""{"session":{"id":"canonical"},"messages":[{"id":"m","role":"user","text":"合成原话"}],"memories":[{"id":"mem","text":"合成记忆","kind":"fact","status":"candidate","source":"用户手动添加"}]}"""))
        assertEquals("", result.messages.single().createdAt)
        assertEquals("", result.memories.single().sourceMessageId)
        assertEquals("", result.memories.single().createdAt)
        assertEquals("用户手动添加", result.memories.single().source)
        assertEquals("", Message("m", "user", "合成原话").createdAt)
    }

    @Test fun explicitNullMetadataDoesNotBecomeLiteralNullOrSourceLabel() {
        val result = conversation(JSONObject("""{"session":{"id":"canonical"},"messages":[{"id":"m","role":"user","text":"合成原话","created_at":null}],"memories":[{"id":"mem","text":"合成记忆","source":"合成来源标签","source_message_id":null,"created_at":null}]}"""))
        assertEquals("", result.messages.single().createdAt)
        assertEquals("", result.memories.single().sourceMessageId)
        assertEquals("", result.memories.single().createdAt)
        assertEquals("合成来源标签", result.memories.single().source)
    }
    @Test fun serverDeliveryPreservesMessageAndPartOrderAcrossSnapshots() {
        val first = conversation(JSONObject("""{"session":{"id":"canonical"},"messages":[{"id":"u","role":"user","text":"问"},{"id":"a","role":"assistant","text":"一","bubbles":["一"],"delivery_pending":true,"delivery_next_ms":70}],"memories":[]}"""))
        assertEquals(listOf("u", "a"), first.messages.map { it.id })
        assertEquals(listOf("一"), first.messages.last().displayParts)
        assertTrue(first.messages.last().deliveryPending)
        assertEquals(100L, first.messages.last().deliveryNextMs)
        val complete = conversation(JSONObject("""{"session":{"id":"canonical"},"messages":[{"id":"u","role":"user","text":"问"},{"id":"a","role":"assistant","text":"一\n\n二","bubbles":["一","二"],"delivery_pending":false}],"memories":[]}"""))
        assertEquals(listOf("u", "a"), complete.messages.map { it.id })
        assertEquals(listOf("一", "二"), complete.messages.last().displayParts)
        assertFalse(complete.messages.last().deliveryPending)
    }
    @Test fun legacyMessageFallsBackToOnePart() {
        val message = messages(JSONObject("""{"messages":[{"id":"a","role":"assistant","text":"旧消息"}]}""")).single()
        assertEquals(listOf("旧消息"), message.displayParts)
        assertFalse(message.deliveryPending)
    }
}
