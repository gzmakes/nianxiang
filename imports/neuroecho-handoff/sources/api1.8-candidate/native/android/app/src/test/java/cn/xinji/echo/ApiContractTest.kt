package cn.xinji.echo

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** Real loopback HTTP and JSON transport; all payloads are synthetic, no account. */
class ApiContractTest {
    @Test fun http200FalseMissingAndUnknownRevokeReceiptsOnlyTriggerReadReconciliation() {
        val selected = Source("source-a", "合成资料A", "本机文本", false)
        for (reply in listOf("""{"ok":false,"reason":"source not found"}""", """{}""", """{"ok":true,"state":"unexpected","cleaned":0,"review_required":0,"remaining_sources":0,"revoked_source_ids":["source-a"]}""")) {
            val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
            var writes = 0; var reads = 0
            server.createContext("/api/source/revoke") { exchange ->
                writes++
                val body = JSONObject(exchange.requestBody.bufferedReader().readText())
                assertEquals("canonical", body.getString("session_id")); assertEquals("source-a", body.getString("source_id"))
                val bytes = reply.toByteArray(); exchange.sendResponseHeaders(200, bytes.size.toLong()); exchange.responseBody.use { it.write(bytes) }
            }
            server.createContext("/api/conversation") { exchange ->
                reads++
                val bytes = """{"session":{"id":"canonical"},"messages":[],"memories":[],"context":{"sources":[{"id":"source-a","title":"合成资料A","label":"本机文本","stale":false}]}}""".toByteArray()
                exchange.sendResponseHeaders(200, bytes.size.toLong()); exchange.responseBody.use { it.write(bytes) }
            }
            server.start()
            try {
                val origin = "http://127.0.0.1:${server.address.port}"
                val attempt = SourceRevocationAttempt(origin, "canonical", selected)
                val api = EchoApi(origin)
                val (receipt, fresh) = runBlocking { api.post("/api/source/revoke", attempt.body()) to conversation(api.get("/api/conversation")) }
                assertEquals(SourceRevokeOutcome.UNRESOLVED, attempt.outcome(receipt, fresh, origin, "canonical", attempt.token))
                assertEquals(listOf(selected), fresh.sources)
                assertEquals(1, writes); assertEquals(1, reads)
            } finally { server.stop(0) }
        }
    }
    @Test fun actualHttp503Then400RetainsTheSamePersistedFollowupRequest() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        val payloads = mutableListOf<JSONObject>()
        server.createContext("/api/followups") { exchange ->
            payloads += JSONObject(exchange.requestBody.bufferedReader().readText())
            val first = payloads.size == 1
            val reply = if (first) """{"detail":"保存结果未确认","error_code":"service_unavailable"}""" else """{"detail":"原时间已过","error_code":"invalid_request"}"""
            val bytes = reply.toByteArray()
            exchange.sendResponseHeaders(if (first) 503 else 400, bytes.size.toLong()); exchange.responseBody.use { it.write(bytes) }
        }
        server.start()
        try {
            val api = EchoApi("http://127.0.0.1:${server.address.port}")
            val first = FollowupDraft("canonical", "只保存一次", java.time.Instant.now().plusSeconds(3600).toString()).beginSave()
            val firstError = runCatching { runBlocking { api.post("/api/followups", first.request.body()) } }.exceptionOrNull() as ApiError
            val restored = FollowupDraft.decode(first.afterFailure(firstError.status, firstError.code).encode())!!
            val retry = restored.beginSave()
            val secondError = runCatching { runBlocking { api.post("/api/followups", retry.request.body()) } }.exceptionOrNull() as ApiError
            val retained = retry.afterFailure(secondError.status, secondError.code)
            assertEquals(503, firstError.status); assertEquals(400, secondError.status)
            assertEquals(first.request.requestId, retained.requestId)
            assertTrue(retained.started)
            assertEquals(2, payloads.size)
            assertEquals(payloads[0].toString(), payloads[1].toString())
        } finally { server.stop(0) }
    }
    @Test fun followupTransitionUsesReviewedPostAliasAndExactCanonicalId() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        var requests = 0
        server.createContext("/api/followups/f-1/transition") { exchange ->
            requests++
            assertEquals("POST", exchange.requestMethod)
            val body = JSONObject(exchange.requestBody.bufferedReader().readText())
            assertEquals("canonical", body.getString("session_id"))
            assertEquals("cancelled", body.getString("status"))
            val reply = """{"id":"f-1","session_id":"canonical","request_id":"stable","content":"合成跟进","due_at":"2026-10-31T01:00:00Z","status":"cancelled","due":false}""".toByteArray()
            exchange.sendResponseHeaders(200, reply.size.toLong()); exchange.responseBody.use { it.write(reply) }
        }
        server.start()
        try {
            val item = Followup("f-1", "canonical", "stable", "合成跟进", "2026-10-31T01:00:00Z", "pending", false)
            val request = followupTransitionRequest(item, "cancelled")
            val saved = followup(runBlocking { EchoApi("http://127.0.0.1:${server.address.port}").post(request.path, request.body) })
            assertEquals("f-1", saved.id); assertEquals("cancelled", saved.status); assertFalse(saved.due); assertEquals(1, requests)
        } finally { server.stop(0) }
    }
    @Test fun followupResponseKeepsDueAndTerminalStateDistinct() {
        val response = JSONObject("""{"followups":[{"id":"f1","content":"喝水","due_at":"2026-10-30T02:00:00Z","status":"pending","due":true},{"id":"f2","content":"散步","status":"cancelled","due":false}]}""")
        val items = followups(response)
        assertTrue(items[0].due); assertEquals("pending", items[0].status); assertEquals("喝水", items[0].content)
        assertFalse(items[1].due); assertEquals("cancelled", items[1].status)
    }
    @Test fun conflictBodyAnd409MetadataSurviveRealHttpTransportWithoutRetrying() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        var requests = 0
        server.createContext("/api/memory/mem") { exchange ->
            requests++
            // The host JDK URLConnection does not implement PATCH; Android's
            // transport method is verified by the Android SDK test/build gate.
            // This host test exercises the actual JSON body and error decoder.
            assertEquals("POST", exchange.requestMethod)
            val body = JSONObject(exchange.requestBody.bufferedReader().readText())
            assertEquals(2, body.getInt("expected_version"))
            assertEquals("我的草稿", body.getString("text"))
            val reply = """{"detail":"记忆已有更新","error_code":"memory_version_conflict","expected_version":2,"current_version":3}""".toByteArray()
            exchange.sendResponseHeaders(409, reply.size.toLong()); exchange.responseBody.use { it.write(reply) }
        }
        server.start()
        try {
            val original = Memory("mem", "旧内容", "fact", "candidate", 2, "用户手动添加", "")
            val request = memoryPatchRequest(original, text = "我的草稿")
            val draft = MemoryDraft.editing(original).copy(text = "我的草稿")
            val error = runCatching { runBlocking { EchoApi("http://127.0.0.1:${server.address.port}").post(request.path, request.body) } }.exceptionOrNull() as ApiError
            assertEquals(409, error.status); assertEquals("memory_version_conflict", error.code); assertEquals(3, error.currentVersion)
            assertEquals("我的草稿", draft.text); assertEquals(1, requests)
        } finally { server.stop(0) }
    }

    @Test fun notionPreviewSendsOnlySelectedPageAndExistingCliMethod() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        var seen = false
        server.createContext("/api/notion/preview") { exchange ->
            val body = JSONObject(exchange.requestBody.bufferedReader().readText())
            assertEquals("https://notion.so/synthetic-page", body.getString("url")); assertEquals("cli", body.getString("method")); assertFalse(body.has("token"))
            seen = true
            val reply = """{"ok":true,"preview_id":"p-once","items":[{"title":"选定页面","summary":"已读取片段"}]}""".toByteArray()
            exchange.sendResponseHeaders(200, reply.size.toLong()); exchange.responseBody.use { it.write(reply) }
        }
        server.start()
        try {
            val request = SourcePolicy.preview("notion", "https://notion.so/synthetic-page")
            val result = runBlocking { EchoApi("http://127.0.0.1:${server.address.port}").post(request.path, request.body) }
            assertTrue(seen); assertTrue(sourceReview(result).canAttach); assertEquals("p-once", sourceReview(result).previewId)
        } finally { server.stop(0) }
    }
}
