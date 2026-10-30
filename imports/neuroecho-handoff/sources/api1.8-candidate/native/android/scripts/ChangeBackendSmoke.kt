package cn.xinji.echo

import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.LocalDate

/** Actual production coordinator/transport; all writes belong to the synthetic other client. */
fun main(args: Array<String>) = runBlocking {
    val origin = args[0]; val owner = EchoApi(args[3]); var checks = 0
    fun verify(value: Boolean, label: String) { check(value) { label }; checks++; println("PASS $label") }
    suspend fun paired(token: String): Pair<EchoApi, PairedProfile> {
        val verified = PairingPolicy.verify(origin, token, EchoApi(origin, DeviceAuthorization(token)).get("/api/paired-device"))
        return EchoApi(origin, DeviceAuthorization(token, verified.profile.serviceInstanceId), connectTimeoutMs = 8_000, readTimeoutMs = 8_000) to verified.profile
    }
    val (reader, identity) = paired(args[1]); val (writer, other) = paired(args[2]); val sid = identity.conversationId
    verify(identity.deviceId != other.deviceId && sid == other.conversationId && identity.serviceInstanceId == other.serviceInstanceId, "two real paired clients share canonical identity with distinct device IDs")
    verify(reader.get("/api/capabilities").getJSONObject("features").opt("conversation_change_cursor") == true, "real remote capability gate is true")
    var context = UpdateContext(identity.scope + ":1", sid, identity.serviceInstanceId, true, false, true, "original", moods = true, followups = true, boundary = true)
    var visible: UpdateSnapshot? = null; var published = 0; var status = UpdateStatus.IDLE; val requests = mutableListOf<String>()
    val coordinator = ChangeCoordinator({ context }, { 0L }, { _, value -> visible = value; published++; true }, { status = it })
    suspend fun poll() = coordinator.poll({ path -> requests += path; reader.get(path) }, force = true)
    poll(); val initial = coordinator.cursor
    verify(initial != null && visible?.conversation?.id == sid && published == 1, "initial reset stages all allowed domains then commits candidate cursor")
    verify(requests.none { it.startsWith("/api/actions") || it.startsWith("/api/next-step") || it.contains("claim") || it.contains("settings") }, "paired refresh never probes forbidden local actions or notification/CLI paths")
    requests.clear(); poll(); verify(published == 1 && requests.size == 1 && coordinator.cursor == initial, "unchanged actual cursor is byte identical without snapshot reads")
    val memory = memory(writer.post("/api/memory", json("session_id" to sid, "kind" to "fact", "text" to "合成另一端记忆", "source" to "用户手动添加")))
    context = context.copy(blocked = true, revision = "local unknown and original draft")
    requests.clear(); poll()
    verify(status == UpdateStatus.PENDING && published == 1 && coordinator.cursor == initial && requests.size == 1, "edit or unknown defers real changed memory without advancing cursor")
    verify(context.revision == "local unknown and original draft", "read-only discovery retains exact local draft identity")
    context = context.copy(blocked = false); poll()
    verify(visible!!.conversation.memories.any { it.id == memory.id } && coordinator.cursor != initial, "second client memory appears after stable staged refresh")
    writer.call("DELETE", memoryDeletePath(memory)); poll()
    verify(visible!!.conversation.memories.none { it.id == memory.id }, "second client expected-version deletion replaces reader memory list")
    fun upload(name: String, text: String) = json("session_id" to sid, "files" to JSONArray(listOf(json("name" to name, "text" to text))))
    val a = conversation(writer.post("/api/local-files/confirm", upload("synthetic-r14-a.txt", "合成资料A，只用于双端撤回。"))).sources.single()
    val b = conversation(writer.post("/api/local-files/confirm", upload("synthetic-r14-b.txt", "合成资料B，撤回A后仍保留。"))).sources.single { it.id != a.id }
    poll(); verify(visible!!.conversation.sources.map { it.id }.toSet() == setOf(a.id, b.id), "second-client selected uploads appear in attached sources")
    writer.post("/api/source/revoke", json("session_id" to sid, "source_id" to a.id)); poll()
    verify(visible!!.conversation.sources.map { it.id } == listOf(b.id), "source withdrawal replaces snapshot and retains unrelated B")
    val day = LocalDate.now().toString()
    val operation = MoodOperation("synthetic-r14-mood", json("kind" to "save", "date" to day, "expected_updated_at" to JSONObject.NULL, "x" to .2, "y" to -.3, "note" to "合成另一端心情").toString(), "save")
    moodOperationReceipt(writer.post("/api/mood-operations", operation.applyBody(sid)), sid, operation); poll()
    verify(visible!!.moods!!.any { it.date == day && it.note == "合成另一端心情" }, "mood invalidation rereads separate self-report list")
    val followup = followup(writer.post("/api/followups", json("session_id" to sid, "request_id" to "synthetic-r14-followup", "content" to "合成另一端待办", "due_at" to Instant.now().plusSeconds(3600).toString(), "confirmed" to true, "allow_contact" to false, "time_zone" to "Asia/Shanghai")))
    poll(); verify(visible!!.followups!!.any { it.id == followup.id }, "passive followup update is visible without contact claim")
    val prior = companionBoundary(writer.get("/api/companion-boundary?session_id=" + encoded(sid)))
    writer.put("/api/companion-boundary", BoundaryChange(sid, prior.revision, "paused", null, prior.timeZone).body()); poll()
    verify(visible!!.boundary?.mode == "paused", "another client boundary change rereads shared boundary")
    val beforeRace = coordinator.cursor; val countBeforeRace = published
    writer.post("/api/memory", json("session_id" to sid, "kind" to "fact", "text" to "合成竞态首条", "source" to "用户手动添加"))
    var lateMemory: Memory? = null
    coordinator.poll({ path ->
        requests += path
        reader.get(path).also {
            if (path == "/api/conversation" && lateMemory == null) lateMemory = memory(writer.post("/api/memory", json("session_id" to sid, "kind" to "fact", "text" to "合成快照读取后新增", "source" to "用户手动添加")))
        }
    }, force = true)
    verify(status == UpdateStatus.PENDING && coordinator.cursor == beforeRace && published == countBeforeRace, "actual write during stage prevents publish and second-cursor advance")
    poll(); verify(visible!!.conversation.memories.any { it.id == lateMemory!!.id } && published == countBeforeRace + 1, "next whole read includes late change before cursor commit")
    val stable = coordinator.cursor; requests.clear(); context = context.copy(foreground = false); coordinator.background(); poll()
    verify(requests.isEmpty() && coordinator.cursor == stable, "background stops actual discovery network calls")
    context = context.copy(foreground = true); poll(); verify(coordinator.cursor == stable, "foreground resume reads without blind replay or duplicate publish")
    var invalidated = 0
    val guarded = EchoApi(origin, DeviceAuthorization(args[1], identity.serviceInstanceId), onInvalidCredential = { invalidated++; context = context.copy(scope = "locked-original", foreground = false) })
    owner.post("/api/paired-devices/" + encoded(identity.deviceId) + "/revoke", json("confirmed" to true))
    coordinator.poll(guarded::get, force = true)
    verify(invalidated == 1 && coordinator.cursor == stable && context.scope == "locked-original", "real 401 locks original identity and late callback cannot publish into another scope")
    println("CHANGE_BACKEND_HTTPS_OK: $checks checks; two synthetic paired devices; Host JVM, not Android runtime")
}
