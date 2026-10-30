package cn.xinji.echo

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class SourcePreviewTest {
    @Test fun actualFeishuTitleAndPreviewShapeShowsTheSourceText() {
        val body = " 前缀😀e\u0301\n结尾 "
        val length = body.codePointCount(0, body.length)
        val review = sourceReview(JSONObject().put("ok", true).put("title", "合成飞书文档").put("preview", body).put("length", length).put("extracted_length", length).put("truncated", false).put("preview_id", "preview-one"), "feishu")
        assertTrue(review.canAttach)
        assertEquals(listOf(PreviewSection("合成飞书文档", body)), review.sections)
        assertTrue(review.scope!!.contains("全部"))
    }
    @Test fun feishuShowsExactBoundedSnapshotAndExplainsTruncation() {
        val body = "字".repeat(12000)
        val result = JSONObject().put("ok", true).put("preview_id", "p").put("preview", body).put("length", 12000).put("extracted_length", 12001).put("truncated", true)
        val review = sourceReview(result, "feishu")
        assertTrue(review.canAttach)
        assertEquals(body, review.sections.single().body)
        assertTrue(review.scope!!.contains("其余内容不会接入"))
    }
    @Test fun feishuRejectsOldOrInconsistentMetadataWithoutFallingBackToItems() {
        fun fixture() = JSONObject().put("ok", true).put("preview_id", "p").put("preview", "内容").put("length", 2).put("extracted_length", 2).put("truncated", false).put("items", org.json.JSONArray().put(JSONObject().put("title", "不能代替正文")))
        val invalid = listOf(
            fixture().removeKey("extracted_length"), fixture().removeKey("truncated"),
            fixture().put("length", 3), fixture().put("extracted_length", 3),
            fixture().put("truncated", true), fixture().put("length", "2"),
            fixture().put("preview_id", ""), fixture().put("preview", "  "),
            fixture().put("ok", false), fixture().put("preview", "字".repeat(12001)).put("length", 12001).put("extracted_length", 12001)
        )
        invalid.forEach { val review = sourceReview(it, "feishu"); assertFalse(review.canAttach); assertTrue(review.sections.isEmpty()); assertNotNull(review.error) }
    }
    @Test fun actualCalendarItemsAndUnderstandingRemainSeparatelyVisible() {
        val review = sourceReview(JSONObject("""{"ok":true,"preview_id":"calendar-one","items":[{"title":"合成日程","meta":"周五 10:00","summary":"和队友联调"}],"understanding":{"facts":["一条日程"],"inferences":["可能忙碌"],"questions":["需要留空档吗？"]}}"""))
        assertTrue(review.canAttach)
        assertEquals(PreviewSection("合成日程", "周五 10:00\n和队友联调"), review.sections.single())
        assertEquals(listOf("一条日程"), review.facts)
        assertEquals(listOf("可能忙碌"), review.inferences)
        assertEquals(listOf("需要留空档吗？"), review.questions)
    }
    @Test fun emptySourceAndGeneratedGuessesCannotBeConfirmed() {
        listOf(
            """{"preview_id":"p","title":"只有文档名","preview":"  "}""",
            """{"preview_id":"p","items":[{},null,{"meta":"只有元数据"}],"understanding":{"facts":["模型猜测"],"inferences":["推测"]}}""",
            """{"preview_id":"p","items":[]}"""
        ).forEach { assertFalse(sourceReview(JSONObject(it)).canAttach) }
    }
    @Test fun validBodyWithoutSingleUsePreviewTokenCannotBeConfirmed() {
        assertFalse(sourceReview(JSONObject("""{"title":"资料","preview":"可读内容"}""")).canAttach)
        assertFalse(sourceReview(JSONObject("""{"ok":false,"preview_id":"p","preview":"错误回包不作内容"}""")).canAttach)
    }
    @Test fun titleOnlyCalendarEventIsVisibleAndCanBeReviewed() {
        val review = sourceReview(JSONObject("""{"ok":true,"preview_id":"p","items":[{"title":"合成休息时间"}]}"""))
        assertTrue(review.canAttach)
        assertEquals("合成休息时间", review.sections.single().title)
    }
}

private fun JSONObject.removeKey(key: String): JSONObject = apply { remove(key) }
