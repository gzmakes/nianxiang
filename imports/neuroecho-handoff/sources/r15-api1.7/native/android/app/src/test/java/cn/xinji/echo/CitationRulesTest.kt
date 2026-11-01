package cn.xinji.echo

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class CitationRulesTest {
    private val document = FeishuDocumentCitation("合成参考文档", "https://demo.feishu.cn/docx/Abc_123-xyz", "合成来源片段")
    private fun message() = Message("a1", "assistant", "已根据资料回答。", citations = listOf(document))
    private fun context(message: Message = message()) = CitationContext("https://echo.example", "scope-a:1", Conversation("canonical", listOf(message), emptyList(), emptyList()), setOf(message.id), true)
    private fun docJSON() = JSONObject().put("kind", "feishu_document").put("title", document.title).put("url", document.url).put("text", document.text)

    @Test fun actualConversationParserPreservesNewDocumentAndLegacyMemory() {
        val payload = JSONObject("""{"session":{"id":"canonical"},"messages":[{"id":"a1","role":"assistant","text":"回答","citations":[{"kind":"feishu_document","title":"参考文档","url":"https://demo.feishu.cn/wiki/Token_1","text":"片段"},{"id":"memory-1","version":3,"text":"旧记忆"}]}]}""")
        val actual = conversation(payload).messages.single()
        assertEquals(2, actual.citations.size)
        assertEquals(FeishuDocumentCitation("参考文档", "https://demo.feishu.cn/wiki/Token_1", "片段"), actual.citations[0])
        assertEquals(MemoryCitation("memory-1", 3, "旧记忆"), actual.citations[1])
        assertEquals(1, CitationPolicy.targets(context(actual), "a1").size)
    }

    @Test fun absentNullAndWrongTypeCitationFieldsDoNotBreakConversation() {
        listOf("", ",\"citations\":null", ",\"citations\":{}", ",\"citations\":\"bad\"").forEach { field ->
            val value = conversation(JSONObject("""{"session":{"id":"canonical"},"messages":[{"id":"a1","role":"assistant","text":"旧消息"$field}]}"""))
            assertTrue(value.messages.single().citations.isEmpty())
            assertEquals("旧消息", value.messages.single().text)
        }
    }

    @Test fun malformedItemsAreSkippedWithoutDroppingOtherCitationsOrMessages() {
        val list = JSONArray().put(JSONObject.NULL).put("bad").put(3).put(JSONArray())
            .put(JSONObject().put("kind", "future").put("id", "m").put("version", 1).put("text", "memory"))
            .put(docJSON().put("url", "https://evil.example/docx/a"))
            .put(docJSON()).put(JSONObject().put("id", "m").put("version", 1).put("text", "legacy"))
        val actual = messages(JSONObject().put("messages", JSONArray().put(JSONObject().put("id", "a1").put("role", "assistant").put("text", "回答").put("citations", list))))
        assertEquals("回答", actual.single().text)
        assertEquals(listOf(document, MemoryCitation("m", 1, "legacy")), actual.single().citations)
    }

    @Test fun documentRequiresActualStringFieldsAndNonblankBoundedTitle() {
        listOf("kind", "title", "url", "text").forEach { key ->
            val missing = docJSON().also { it.remove(key) }
            assertTrue("missing $key", CitationPolicy.parse(JSONArray().put(missing)).isEmpty())
            listOf(JSONObject.NULL, 1, true, JSONObject()).forEach { wrong ->
                assertTrue("wrong $key", CitationPolicy.parse(JSONArray().put(docJSON().put(key, wrong))).isEmpty())
            }
        }
        listOf("", "  ", "a".repeat(501)).forEach { title -> assertTrue(CitationPolicy.parse(JSONArray().put(docJSON().put("title", title))).isEmpty()) }
        assertEquals(1, CitationPolicy.parse(JSONArray().put(docJSON().put("title", "a".repeat(500)).put("text", ""))).size)
        assertEquals(1, CitationPolicy.parse(JSONArray().put(docJSON().put("title", "🙂".repeat(500)))).size)
        assertTrue(CitationPolicy.parse(JSONArray().put(docJSON().put("title", "🙂".repeat(501)))).isEmpty())
    }

    @Test fun nullOrUnknownKindCannotMasqueradeAsLegacyMemory() {
        listOf(JSONObject.NULL, "memory", "", 7, false).forEach { kind ->
            val item = JSONObject().put("kind", kind).put("id", "m").put("version", 1).put("text", "legacy")
            assertTrue(CitationPolicy.parse(JSONArray().put(item)).isEmpty())
        }
    }

    @Test fun legacyVersionMustBeActualPositiveIntegerAndTextMustBeString() {
        listOf("1", 1.5, 0, -1, JSONObject.NULL, true).forEach { version ->
            assertTrue(CitationPolicy.parse(JSONArray().put(JSONObject().put("id", "m").put("version", version).put("text", "legacy"))).isEmpty())
        }
        assertTrue(CitationPolicy.parse(JSONArray("""[{"id":"m","version":1.0,"text":"legacy"}]""")).isEmpty())
        assertTrue(CitationPolicy.parse(JSONArray("""[{"id":"m","version":1,"text":null},{"id":"","version":1,"text":""}]""")).isEmpty())
        assertEquals(MemoryCitation("m", 2147483648L, ""), CitationPolicy.parse(JSONArray("""[{"id":"m","version":2147483648,"text":""}]""")).single())
    }

    @Test fun onlyOfficialHttpsDocumentPathsAndDefaultPortAreAccepted() {
        listOf("https://feishu.cn/docx/a", "https://sub.demo.feishu.cn/docs/A_1-2/", "https://larksuite.com/wiki/a", "HTTPS://WORK.LARKSUITE.COM:443/docx/a?from=chat%20citation#section", document.url + "?from=中文查询#中文").forEach { value ->
            assertEquals(value, CitationPolicy.documentURL(value))
        }
    }

    @Test fun rejectsCredentialsSpoofedHostsInvalidLabelsAndPorts() {
        listOf("http://feishu.cn/docx/a", "https://feishu.cn.evil.com/docx/a", "https://evilfeishu.cn/docx/a", "https://feishu.cn@evil.com/docx/a", "https://u@feishu.cn/docx/a", "https://u:p@feishu.cn/docx/a", "https://-x.feishu.cn/docx/a", "https://x-.feishu.cn/docx/a", "https://x..feishu.cn/docx/a", "https://feishu.cn./docx/a", "https://feishu.cn:8443/docx/a", "https://feishu.cn:0443/docx/a", "https://feishu.cn:/docx/a", "https://fｅishu.cn/docx/a", "https://%66eishu.cn/docx/a", "https://[::1]/docx/a").forEach { value -> assertNull(value, CitationPolicy.documentURL(value)) }
        assertNull(CitationPolicy.documentURL("https://" + "a".repeat(64) + ".feishu.cn/docx/a"))
        assertNull(CitationPolicy.documentURL("https://" + (1..4).joinToString(".") { "a".repeat(62) } + ".feishu.cn/docx/a"))
    }

    @Test fun rejectsEncodedOrNormalizedPathConfusion() {
        listOf("/docx/", "/Docx/a", "/docx/a/b", "/docx/a.txt", "/wiki/中文", "/docs/../docx/a", "/docx/%61", "/docx/a%2fb", "/docx/a%5Cb", "//docx/a", "/docx/a//", "/%64ocx/a").forEach { path -> assertNull(path, CitationPolicy.documentURL("https://demo.feishu.cn$path")) }
    }

    @Test fun rejectsRawWhitespaceControlsBackslashesAndEncodedControlsAnywhere() {
        listOf(" ", "\t", "\r", "\n", "\u0000", "\u007f", "\u0085", "\u00a0", "\\").forEach { part -> assertNull(CitationPolicy.documentURL(document.url + "?x=" + part)) }
        listOf("%00", "%1F", "%7f", "%C2%80", "%c2%9f", "%5C").forEach { part -> assertNull(CitationPolicy.documentURL(document.url + "#" + part)) }
        assertNull(CitationPolicy.documentURL(" " + document.url))
        assertNull(CitationPolicy.documentURL(document.url + "?bad=%"))
        assertNull(CitationPolicy.documentURL(document.url + "?" + "a".repeat(4096)))
        assertNull(CitationPolicy.documentURL(document.url + "?" + "中".repeat(1366)))
    }

    @Test fun onlyCompleteVisibleAssistantMessagesExposeDocuments() {
        val normal = message()
        listOf(normal.copy(role = "user"), normal.copy(role = "system"), normal.copy(id = ""), normal.copy(deliveryPending = true), normal.copy(deliveryFlagValid = false), normal.copy(text = " "), normal.copy(bubbles = listOf(" "))).forEach { value -> assertTrue(CitationPolicy.targets(context(value), value.id).isEmpty()) }
        assertTrue(CitationPolicy.targets(context().copy(visibleMessageIds = emptySet()), normal.id).isEmpty())
        assertTrue(CitationPolicy.targets(context().copy(foreground = false), normal.id).isEmpty())
        assertTrue(CitationPolicy.targets(context().copy(conversation = null), normal.id).isEmpty())
        assertEquals(document, CitationPolicy.targets(context(normal.copy(text = "", bubbles = listOf("实际可见回复"))), normal.id).single().document)
    }

    @Test fun invalidDeliveryFlagFromJsonNeverExposesSourceButton() {
        listOf("\"false\"", "0", "null", "{}").forEach { flag ->
            val item = docJSON()
            val json = JSONObject("""{"messages":[{"id":"a1","role":"assistant","text":"回答","delivery_pending":$flag}]}""")
            json.getJSONArray("messages").getJSONObject(0).put("citations", JSONArray().put(item))
            val message = messages(json).single()
            assertFalse(message.deliveryFlagValid)
            assertTrue(CitationPolicy.targets(context(message), message.id).isEmpty())
        }
    }

    @Test fun legacyMemoryUnknownReferencesAndProgrammaticBadUrlsDoNotCreateDocumentTargets() {
        val message = message().copy(citations = listOf(MemoryCitation("m", 1, "legacy"), document.copy(url = "https://evil.example/docx/a")))
        assertTrue(CitationPolicy.targets(context(message), message.id).isEmpty())
    }

    @Test fun clickRevalidatesEndpointIdentitySessionVisibilityAndForeground() {
        val current = context()
        val target = CitationPolicy.targets(current, "a1").single()
        assertEquals(document.url, CitationPolicy.urlForOpen(target, current))
        listOf(current.copy(endpoint = "https://other.example"), current.copy(dataContextId = "scope-b:1"), current.copy(dataContextId = "scope-a:2"), current.copy(conversation = current.conversation!!.copy(id = "other")), current.copy(visibleMessageIds = emptySet()), current.copy(foreground = false)).forEach { changed -> assertNull(CitationPolicy.urlForOpen(target, changed)) }
    }

    @Test fun clickRevalidatesCurrentBodyCompletionAndExactDocument() {
        val current = context()
        val target = CitationPolicy.targets(current, "a1").single()
        listOf(message().copy(text = "回答已更新"), message().copy(deliveryPending = true), message().copy(deliveryFlagValid = false), message().copy(citations = emptyList()), message().copy(citations = listOf(document.copy(title = "另一文档"))), message().copy(citations = listOf(document.copy(url = "https://demo.feishu.cn/docx/other"))), message().copy(citations = listOf(document.copy(text = "更新片段")))).forEach { changed -> assertNull(CitationPolicy.urlForOpen(target, context(changed))) }
        assertNull(CitationPolicy.urlForOpen(target, current.copy(conversation = current.conversation!!.copy(messages = emptyList()))))
        assertNull(CitationPolicy.urlForOpen(target, current.copy(conversation = current.conversation!!.copy(messages = listOf(message(), message())))))
    }
}
