package cn.xinji.echo

import org.json.JSONObject

/** Actual backend preview shapes: Feishu uses title/preview, other readers use items. */
data class PreviewSection(val title: String, val body: String)
data class SourceReview(val previewId: String, val sections: List<PreviewSection>, val facts: List<String>, val inferences: List<String>, val questions: List<String>, val canAttach: Boolean, val scope: String? = null, val error: String? = null)

fun sourceReview(result: JSONObject, sourceId: String = ""): SourceReview {
    fun text(obj: JSONObject, key: String): String = if (obj.isNull(key)) "" else obj.optString(key, "").trim()
    fun lines(key: String): List<String> {
        val values = result.optJSONObject("understanding")?.optJSONArray(key) ?: return emptyList()
        return (0 until values.length()).mapNotNull { index -> (values.opt(index) as? String)?.trim()?.takeIf { it.isNotEmpty() } }
    }
    if (sourceId == "feishu") {
        // Preserve all whitespace and count Unicode code points, matching Python len.
        // Never accept a short excerpt or fall back to generated items for this source.
        val body = result.opt("preview") as? String
        fun count(key: String): Long? = when (val value = result.opt(key)) {
            is Int -> value.toLong()
            is Long -> value
            else -> null
        }
        val length = count("length")
        val extracted = count("extracted_length")
        val truncated = result.opt("truncated") as? Boolean
        val id = text(result, "preview_id")
        val valid = result.opt("ok") == true && id.isNotEmpty() && !body.isNullOrBlank() &&
            length != null && length <= 12_000 && body.codePointCount(0, body.length).toLong() == length &&
            extracted != null && extracted >= length && truncated != null && truncated == (extracted > length)
        if (!valid) return SourceReview(id, emptyList(), emptyList(), emptyList(), emptyList(), false,
            error = "无法完整核对将接入的飞书正文。请更新电脑上的回响服务并重新读取；本次不会接入。")
        val scope = if (truncated == true) "已提取 ${extracted} 字，以下为将保留的前 ${length} 字；其余内容不会接入。"
                    else "以下为将接入的全部 ${length} 字。"
        return SourceReview(id, listOf(PreviewSection(text(result, "title").ifBlank { "飞书文档" }, body!!)),
            lines("facts"), lines("inferences"), lines("questions"), true, scope)
    }
    val sections = mutableListOf<PreviewSection>()
    val excerpt = text(result, "preview")
    if (excerpt.isNotBlank()) sections += PreviewSection(text(result, "title").ifBlank { "文档正文片段" }, excerpt)
    val items = result.optJSONArray("items")
    if (items != null) for (index in 0 until items.length()) {
        val item = items.optJSONObject(index) ?: continue
        val title = text(item, "title")
        val summary = text(item, "summary")
        // A real calendar event or mail subject can itself be the source content.
        // Metadata, generated guesses, or an empty document title alone are insufficient.
        if (title.isNotBlank() || summary.isNotBlank()) sections += PreviewSection(title.ifBlank { "资料条目" }, listOf(text(item, "meta"), summary).filter { it.isNotBlank() }.joinToString("\n"))
    }
    val previewId = text(result, "preview_id")
    return SourceReview(previewId, sections, lines("facts"), lines("inferences"), lines("questions"), result.optBoolean("ok", true) && previewId.isNotBlank() && sections.isNotEmpty())
}
