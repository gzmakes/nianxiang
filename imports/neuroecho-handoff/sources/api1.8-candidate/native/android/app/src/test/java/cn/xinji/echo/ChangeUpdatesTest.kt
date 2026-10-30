package cn.xinji.echo

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ChangeUpdatesTest {
    private fun receipt(cursor: String = "opaque_A", reset: Boolean = true, domains: List<String> = if (reset) ChangePolicy.domains.toList() else emptyList(), reason: String? = if (reset) "initial" else null, service: String = "svc_test", sid: String = "ses_test") =
        json("service_instance_id" to service, "conversation_id" to sid, "cursor" to cursor, "reset_required" to reset, "domains" to JSONArray(domains), "reset_reason" to reason)
    private fun conversation() = json("session" to json("id" to "ses_test"), "messages" to JSONArray(), "memories" to JSONArray(), "context" to json("sources" to JSONArray()))
    private class Fixture {
        var time = 0L
        var current = UpdateContext("scope:1", "ses_test", "svc_test", true, false, true, "original")
        var applied: UpdateSnapshot? = null
        var count = 0
        val statuses = mutableListOf<UpdateStatus>()
        val paths = mutableListOf<String>()
        val coordinator = ChangeCoordinator({ current }, { time }, { _, snapshot -> applied = snapshot; count++; true }, { statuses += it })
    }
    private suspend fun Fixture.fetch(force: Boolean = false, get: suspend (String) -> JSONObject) = coordinator.poll({ path -> paths += path; get(path) }, force)
    @Test fun strictBooleanAndOpaqueCursor() {
        assertEquals("opaque_A", changeReceipt(receipt()).cursor)
        listOf("", "a+b", "a/b", "a=", "a".repeat(2049)).forEach { assertTrue(runCatching { changeReceipt(receipt(it)) }.isFailure) }
        assertTrue(runCatching { changeReceipt(receipt().put("reset_required", "true")) }.isFailure)
    }
    @Test fun resetAndDomainsMustBeCompleteUniqueAndTyped() {
        assertTrue(runCatching { changeReceipt(receipt(domains = listOf("messages"))) }.isFailure)
        assertTrue(runCatching { changeReceipt(receipt(reset = false, domains = listOf("messages", "messages"))) }.isFailure)
        assertTrue(runCatching { changeReceipt(receipt().put("domains", JSONArray().put(1))) }.isFailure)
        assertTrue(runCatching { changeReceipt(receipt(reason = "new_reason")) }.isFailure)
        assertTrue(runCatching { changeReceipt(receipt().also { it.remove("reset_reason") }) }.isFailure)
    }
    @Test fun futureDomainPreservedButNotApplied() = runBlocking {
        val f = Fixture(); f.fetch { receipt(domains = ChangePolicy.domains.toList() + "future_domain") }
        assertNull(f.coordinator.cursor); assertEquals(0, f.count); assertEquals(UpdateStatus.UNSUPPORTED, f.statuses.last())
    }
    @Test fun initialReadsThenRechecksThenPublishesExactCandidate() = runBlocking {
        val f = Fixture(); f.fetch { path -> if (path == "/api/conversation") conversation() else if (path.contains("after=")) receipt(reset = false) else receipt() }
        assertEquals(listOf("/api/conversation/changes", "/api/conversation", "/api/conversation/changes?after=opaque_A"), f.paths)
        assertEquals("opaque_A", f.coordinator.cursor); assertEquals(1, f.count); assertEquals(UpdateStatus.UPDATED, f.statuses.last())
    }
    @Test fun unchangedDoesNotReadSnapshotsOrInventNewCursor() = runBlocking {
        val f = Fixture(); f.fetch { path -> if (path == "/api/conversation") conversation() else if (path.contains("after=")) receipt(reset = false) else receipt() }
        f.paths.clear(); f.time = 10_000; f.fetch { receipt(reset = false) }
        assertEquals(listOf("/api/conversation/changes?after=opaque_A"), f.paths); assertEquals(1, f.count)
    }
    @Test fun snapshotFailureDoesNotAdvanceOrPartiallyPublish() = runBlocking {
        val f = Fixture(); f.fetch { path -> if (path == "/api/conversation") error("offline") else receipt() }
        assertNull(f.coordinator.cursor); assertNull(f.applied); assertEquals(UpdateStatus.OFFLINE, f.statuses.last())
    }
    @Test fun malformedSnapshotCannotLookLikeDeletion() = runBlocking {
        val f = Fixture(); f.fetch { path -> if (path == "/api/conversation") conversation().also { it.remove("memories") } else receipt() }
        assertNull(f.applied); assertNull(f.coordinator.cursor)
    }
    @Test fun newerDuringReadNeverAdvancesSecondCursor() = runBlocking {
        val f = Fixture(); f.fetch { path -> when { path == "/api/conversation" -> conversation(); path.contains("after=") -> receipt("opaque_B", false, listOf("messages")); else -> receipt() } }
        assertNull(f.coordinator.cursor); assertEquals(0, f.count); assertEquals(UpdateStatus.PENDING, f.statuses.last())
    }
    @Test fun editingUnknownOrUploadBlockBeforeSnapshot() = runBlocking {
        val f = Fixture(); f.current = f.current.copy(blocked = true); f.fetch { receipt() }
        assertEquals(listOf("/api/conversation/changes"), f.paths); assertNull(f.coordinator.cursor); assertEquals(UpdateStatus.PENDING, f.statuses.last())
    }
    @Test fun editBeginningDuringReadDiscardsAllStagedData() = runBlocking {
        val f = Fixture(); f.fetch { path -> if (path == "/api/conversation") { f.current = f.current.copy(blocked = true, revision = "new draft"); conversation() } else receipt() }
        assertEquals(0, f.count); assertNull(f.coordinator.cursor)
    }
    @Test fun revisionChangeEvenWithoutBlockerPreventsOverwrite() = runBlocking {
        val f = Fixture(); f.fetch { path -> if (path == "/api/conversation") { f.current = f.current.copy(revision = "newer local snapshot"); conversation() } else receipt() }
        assertEquals(0, f.count); assertNull(f.coordinator.cursor)
    }
    @Test fun wrongIdentityNeverRebinds() = runBlocking {
        for (value in listOf(receipt(service = "svc_other"), receipt(sid = "ses_other"), receipt(reason = "identity_changed"))) {
            val f = Fixture(); f.fetch { value }; f.fetch(true) { receipt() }
            assertEquals(1, f.paths.size); assertEquals(0, f.count); assertNull(f.coordinator.cursor); assertEquals(UpdateStatus.IDENTITY_CHANGED, f.statuses.last())
        }
    }
    @Test fun backgroundIgnoresLateResponseAndPreventsOverlapUntilUnwound() = runBlocking {
        val f = Fixture(); val waiting = CompletableDeferred<Unit>(); val release = CompletableDeferred<Unit>()
        val first = async { f.fetch { waiting.complete(Unit); release.await(); receipt() } }
        waiting.await(); f.current = f.current.copy(foreground = false); f.coordinator.background()
        f.current = f.current.copy(foreground = true); f.fetch(true) { receipt() }
        assertEquals(1, f.paths.size); release.complete(Unit); first.await(); assertEquals(0, f.count)
        f.fetch { path -> if (path == "/api/conversation") conversation() else if (path.contains("after=")) receipt(reset = false) else receipt() }
        assertEquals(1, f.count)
    }
    @Test fun singleFlightAndOldScopeCannotPublish() = runBlocking {
        val f = Fixture(); val waiting = CompletableDeferred<Unit>(); val release = CompletableDeferred<Unit>()
        val first = async { f.fetch { waiting.complete(Unit); release.await(); receipt() } }
        waiting.await(); f.fetch(true) { receipt() }; assertEquals(1, f.paths.size)
        f.current = f.current.copy(scope = "scope:2"); release.complete(Unit); first.await(); assertEquals(0, f.count)
    }
    @Test fun boundedBackoffAndExplicitCheck() = runBlocking {
        val f = Fixture(); f.fetch { error("offline") }; f.time = 19_999; f.fetch { receipt() }; assertEquals(1, f.paths.size)
        f.fetch(true) { error("offline") }; assertEquals(2, f.paths.size)
        f.time += 39_999; f.fetch { receipt() }; assertEquals(2, f.paths.size)
        f.time++; f.fetch { error("offline") }; assertEquals(3, f.paths.size)
        f.time += 60_000; f.fetch { error("offline") }; assertEquals(4, f.paths.size)
    }
    @Test fun forbiddenDoesNotInvalidateCredentialsOrWrite() = runBlocking {
        val f = Fixture(); f.fetch { throw ApiError(403, "forbidden", "paired_operation_forbidden") }
        assertEquals(UpdateStatus.UNSUPPORTED, f.statuses.last()); assertNull(f.coordinator.cursor); assertEquals("scope:1", f.current.scope)
    }
    @Test fun oldServerHasOnlyExplicitRefreshFallback() = runBlocking {
        val f = Fixture(); f.current = f.current.copy(supported = false); f.fetch { error("must not contact") }
        assertTrue(f.paths.isEmpty()); assertEquals(UpdateStatus.UNSUPPORTED, f.statuses.last())
    }
    @Test fun deletionAndSourceWithdrawalReplaceRatherThanAppend() = runBlocking {
        val f = Fixture(); f.current = f.current.copy(moods = true, followups = true, boundary = true)
        f.fetch { path -> when {
            path == "/api/conversation" -> conversation()
            path.startsWith("/api/moods?") -> json("moods" to JSONArray())
            path.startsWith("/api/followups?") -> json("followups" to JSONArray())
            path.startsWith("/api/companion-boundary?") -> json("revision" to 1, "mode" to "active", "until" to null, "time_zone" to "Asia/Shanghai", "suppression_revision" to 1)
            path.contains("after=") -> receipt(reset = false)
            else -> receipt()
        } }
        assertTrue(f.applied!!.conversation.sources.isEmpty()); assertTrue(f.applied!!.conversation.memories.isEmpty()); assertTrue(f.applied!!.moods!!.isEmpty()); assertTrue(f.applied!!.followups!!.isEmpty())
        assertFalse(f.paths.any { it.startsWith("/api/actions") || it.startsWith("/api/next-step") || it.contains("claim") || it.contains("/turn/") })
    }
    @Test fun failedFinalRecheckDoesNotPublishEarlierSnapshot() = runBlocking {
        val f = Fixture(); f.fetch { path -> when { path == "/api/conversation" -> conversation(); path.contains("after=") -> throw ApiError(500,"temporary"); else -> receipt() } }
        assertNull(f.applied); assertNull(f.coordinator.cursor)
    }
    @Test fun stagedDomainFailureKeepsEverythingOriginal() = runBlocking {
        val f = Fixture(); f.current = f.current.copy(moods = true)
        f.fetch { path -> when { path == "/api/conversation" -> conversation(); path.startsWith("/api/moods?") -> JSONObject(); else -> receipt() } }
        assertNull(f.applied); assertNull(f.coordinator.cursor)
    }
    @Test fun emptyCanonicalHasExplicitNullContext() = runBlocking {
        val f = Fixture(); f.fetch { path -> if (path == "/api/conversation") conversation().put("context", JSONObject.NULL) else if (path.contains("after=")) receipt(reset = false) else receipt() }
        assertEquals(1, f.count); assertTrue(f.applied!!.conversation.sources.isEmpty())
    }
    @Test fun finalIdentityChangeBlocksRatherThanGenericPending() = runBlocking {
        val f = Fixture(); f.fetch { path -> if (path == "/api/conversation") conversation() else if (path.contains("after=")) receipt(reset = false, service = "another_service") else receipt() }
        assertEquals(UpdateStatus.IDENTITY_CHANGED, f.statuses.last()); assertNull(f.coordinator.cursor); assertNull(f.applied)
    }

    @Test fun malformedRowsCannotSilentlyVanishFromReplacement() = runBlocking {
        for (key in listOf("messages", "memories")) {
            val f = Fixture(); f.fetch { path -> if (path == "/api/conversation") conversation().put(key, JSONArray().put(1)) else receipt() }
            assertNull(f.applied); assertNull(f.coordinator.cursor)
        }
    }
    @Test fun duplicateIdsCannotMakeReplacementAmbiguous() = runBlocking {
        val f = Fixture(); f.fetch { path -> if (path == "/api/conversation") conversation().put("messages", JSONArray(listOf(json("id" to "same", "role" to "user", "text" to "A"), json("id" to "same", "role" to "user", "text" to "B")))) else receipt() }
        assertNull(f.applied); assertNull(f.coordinator.cursor)
    }

}
