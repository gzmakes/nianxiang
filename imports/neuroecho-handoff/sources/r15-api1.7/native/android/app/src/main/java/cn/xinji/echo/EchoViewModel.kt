package cn.xinji.echo

import android.app.Application
import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.CancellationException
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.util.UUID
import cn.xinji.echo.shared.EchoSharedReference as Shared

data class ActionEditor(val token: String = UUID.randomUUID().toString(), val kind: String, val title: String = "", val detail: String = "", val whenText: String = "", val existingId: String? = null, val immutable: Boolean = false, val uncertain: Boolean = false, val committing: Boolean = false)
data class SourcePreview(val sourceId: String, val result: JSONObject, val url: String = "", val uncertain: Boolean = false)
data class EchoState(val conversation: Conversation? = null, val actions: List<SavedAction> = emptyList(), val nextStep: String = "", val descriptors: List<JSONObject> = emptyList(), val draft: String = "", val busy: Boolean = false, val pending: PendingTurn? = null, val notice: String = "", val editor: ActionEditor? = null, val files: List<SelectedText> = emptyList(), val filesUncertain: Boolean = false, val sourcePreview: SourcePreview? = null, val revisions: List<JSONObject> = emptyList(), val memoryDraft: MemoryDraft? = null, val memoryEditorOpen: Boolean = false, val topics: Map<String, String> = emptyMap(), val selectedTopic: String = "全部", val focusMessageId: String? = null, val memoryVersioning: Boolean = false, val followups: List<Followup> = emptyList(), val followupDraft: FollowupDraft? = null, val followupEditorOpen: Boolean = false, val followupsAvailable: Boolean = false, val chatSending: Boolean = false, val targetedDeliveryStop: Boolean = false, val memoryOffer: QuoteMemoryReview? = null, val quoteForReview: QuoteMemoryReview? = null, val recurringFollowups: Boolean = false, val boundedFollowups: Boolean = false, val boundaryAvailable: Boolean = false, val boundary: CompanionBoundary? = null, val moodsAvailable: Boolean = false, val moodLedgerAvailable: Boolean = false, val moodEntries: List<MoodRecord> = emptyList(), val moodsLoaded: Boolean = false, val moodDraft: MoodDraft? = null, val moodEditorOpen: Boolean = false, val moodLocalSaved: Boolean = true, val changesAvailable: Boolean = false, val updateStatus: UpdateStatus = UpdateStatus.IDLE)

class EchoViewModel(application: Application) : AndroidViewModel(application) {
    private val preferences = application.getSharedPreferences("echo-native", Context.MODE_PRIVATE)
    private val vault = AndroidCredentialVault(preferences)
    private val connectionEpoch = ConnectionEpoch()
    private var credential: PairedCredential? = null
    private var pairedProfile: PairedProfile? = null
    private var dataStorageBlocked = false
    var savedConnections by mutableStateOf<List<PairedProfile>>(emptyList())
        private set
    val activeConnectionScope get() = credential?.profile?.scope
    var connectionStatus by mutableStateOf("")
        private set
    val pairedMode get() = pairedProfile != null || baseUrl.startsWith("https:")
    val dataContextId get() = scopeKey() + ":" + connectionEpoch.value
    val connectionNeedsPairing get() = pairedMode && credential == null
    val connectionIdentity get() = pairedProfile?.let { "${it.label} · ${it.deviceId.take(12)}" }.orEmpty()
    val connectionExpiry get() = pairedProfile?.expiresAt.orEmpty()
    var baseUrl by mutableStateOf(preferences.getString("endpoint", EndpointPolicy.DEFAULT)!!)
        private set
    var comfort by mutableStateOf(Comfort(preferences.getBoolean("reduce_motion", Shared.DEFAULT_REDUCE_MOTION), preferences.getBoolean("reduce_transparency", Shared.DEFAULT_REDUCE_TRANSPARENCY), preferences.getFloat("light_intensity", Shared.DEFAULT_LIGHT_INTENSITY)))
        private set
    var state by mutableStateOf(EchoState())
        private set
    var memoryProposals by mutableStateOf(preferences.getBoolean("memory-proposals", false))
        private set
    fun memoryProposals(value: Boolean) {
        if (!preferences.edit().putBoolean("memory-proposals", value).commit()) { tell("未能保存记忆提议偏好，请稍后再试。"); return }
        memoryProposals = value
        if (!value) state = state.copy(memoryOffer = null)
    }
    private val api: EchoApi get() = client()
    private fun client(shortRead: Boolean = false): EchoApi {
        val current = credential
        if (pairedMode) {
            check(current != null && !current.profile.expired()) { "设备连接已失效，请重新配对；旧草稿和未决请求仍隔离保留。" }
            val epoch = connectionEpoch.value
            return EchoApi(current.profile.origin, DeviceAuthorization(current.token, current.profile.serviceInstanceId),
                requireCurrent = { connectionEpoch.requireCurrent(epoch) }, onInvalidCredential = { invalidateConnection(it) }, connectTimeoutMs = if (shortRead) 8_000 else 15_000, readTimeoutMs = if (shortRead) 8_000 else 70_000)
        }
        val epoch = connectionEpoch.value
        return EchoApi(EndpointPolicy.validate(baseUrl, BuildConfig.DEBUG), requireCurrent = { connectionEpoch.requireCurrent(epoch) }, connectTimeoutMs = if (shortRead) 8_000 else 15_000, readTimeoutMs = if (shortRead) 8_000 else 70_000)
    }
    private fun localDraftAccess(): LocalDraftAccess {
        val scope = scopeKey()
        val active = credential
        val valid = !dataStorageBlocked && (!pairedMode || (active != null && active.profile.scope == pairedProfile?.scope && !active.profile.expired()))
        return LocalDraftAccess(dataContextId, scope, if (pairedMode) active?.profile?.scope else scope, valid, pairedProfile?.conversationId ?: state.conversation?.id)
    }
    fun currentLocalDraftReview(): LocalDraftReview? = localDraftReview(localDraftAccess(), state.draft, state.memoryDraft, state.followupDraft, state.moodDraft)
    fun canPresentLocalDraftReview(review: LocalDraftReview) = mayPresentDraftReview(review, localDraftAccess())
    private fun readScoped(key: String, default: String? = null): String? = try {
        if (pairedProfile == null) preferences.getString(key, default) else vault.read("data:" + key) ?: default
    } catch (error: Exception) { dataStorageBlocked = true; throw error }
    private fun writeScoped(key: String, value: String?): Boolean = try {
        val saved = if (pairedProfile != null) vault.write("data:" + key, value)
        else { val edit = preferences.edit(); if (value == null) edit.remove(key) else edit.putString(key, value); edit.commit() }
        if (!saved) dataStorageBlocked = true
        saved
    } catch (_: Exception) { dataStorageBlocked = true; false }
    private fun invalidateConnection(error: ApiError? = null) {
        credential = null; connectionEpoch.advance()
        val saved = runCatching { vault.lock(pairedProfile, retireCredential = error == null || error.status == 401) }.getOrDefault(false)
        // Keep an in-flight work lock until its captured operation has unwound.
        // Clearing private RAM must not enable a new pairing that an old finally could overwrite.
        state = EchoState(busy = state.busy, notice = if (saved) "设备连接已失效。旧草稿与未决请求已隔离保留，不会换身份重发；请在电脑核对后重新配对。" else "连接已停止，但未能完整保存失效标记。原加密内容未清除，请先在电脑撤销此设备并核对本机存储。")
        runCatching { vault.savedProfiles() }.onSuccess { savedConnections = it }
        connectionStatus = if (error?.code == "service_instance_mismatch") "服务身份已变化 · 需要重新配对" else "未连接 · 需要重新配对"
    }
    private var draftMigrationBlocked = false
    private fun pendingKey() = "pending-" + scopeKey()
    private fun savePending(turn: PendingTurn?) {
        check(writeScoped(pendingKey(), turn?.encode())) { "无法保存发送标识，请检查本机存储后再发送。" }
        state = state.copy(pending = turn)
    }
    private fun readPending(): PendingTurn? = try {
        readScoped(pendingKey())?.let { raw -> PendingTurn.decode(raw) ?: error("原发送账本无法读取；保留原内容，不创建新请求。") }
    } catch (_: Exception) { dataStorageBlocked = true; null }
    private fun scopeKey() = pairedProfile?.scope ?: MessageDigest.getInstance("SHA-256").digest(baseUrl.toByteArray()).take(12).joinToString("") { "%02x".format(it) }
    private fun draftKey() = "draft-" + scopeKey()
    private fun readDraft() = readScoped(draftKey(), "").orEmpty()
    private fun memoryDraftKey() = "memory-draft-" + scopeKey()
    private fun persistMemoryDraft(value: MemoryDraft?) {
        state = state.copy(memoryDraft = value)
        if (!writeScoped(memoryDraftKey(), value?.encode())) tell("未能持久保存记忆草稿；文字暂留在当前页面，请先复制，再继续。")
    }
    private fun readMemoryDraft() = readScoped(memoryDraftKey())?.let(MemoryDraft::decode)
    private fun readTopics() = TopicPolicy.decode(readScoped("topics-" + scopeKey(), "{}").orEmpty())
    private var updatesForeground = false
    private var presentationBlocked = false
    private val updates = ChangeCoordinator(context = ::updateContext, now = { android.os.SystemClock.elapsedRealtime() },
        publish = { plan, snapshot ->
            val current = updateContext()
            if (current == null || current.scope != plan.scope || current.blocked || current.revision != plan.revision) false
            else {
                state = state.copy(conversation = snapshot.conversation, moodEntries = snapshot.moods ?: state.moodEntries,
                    moodsLoaded = if (snapshot.moods != null) true else state.moodsLoaded,
                    followups = snapshot.followups ?: state.followups, boundary = snapshot.boundary ?: state.boundary,
                    actions = snapshot.actions ?: state.actions, nextStep = snapshot.nextStep ?: state.nextStep, revisions = emptyList())
                true
            }
        }, status = { value -> state = state.copy(updateStatus = value) })
    private fun updateContext(): UpdateContext? {
        val sid = state.conversation?.id ?: return null
        val blocked = state.busy || state.pending != null || state.draft.isNotBlank() || state.chatSending ||
            state.conversation?.messages?.any { it.deliveryPending } == true || state.editor != null ||
            state.memoryDraft != null || state.memoryEditorOpen || state.followupDraft != null || state.followupEditorOpen ||
            state.moodDraft?.let { it.dirty || it.locked } == true || state.moodEditorOpen || state.files.isNotEmpty() ||
            state.filesUncertain || state.sourcePreview != null || state.memoryOffer != null || state.quoteForReview != null ||
            presentationBlocked || dataStorageBlocked || connectionNeedsPairing
        return UpdateContext(dataContextId, sid, pairedProfile?.serviceInstanceId, updatesForeground, blocked, state.changesAvailable,
            state.copy(updateStatus = UpdateStatus.IDLE, notice = ""), state.moodsAvailable, state.followupsAvailable, state.boundaryAvailable, !pairedMode)
    }
    fun updatePresentationBlocked(value: Boolean) { presentationBlocked = value }
    fun foregroundUpdates(value: Boolean) { updatesForeground = value; if (!value) { updates.background(); if (state.updateStatus == UpdateStatus.CHECKING) state = state.copy(updateStatus = UpdateStatus.IDLE) } }
    suspend fun pollUpdates(force: Boolean = false) {
        if (pairedMode && credential?.profile?.expired() == true) { invalidateConnection(); return }
        if (connectionNeedsPairing || state.conversation == null) return
        val captured = runCatching { client(shortRead = true) }.getOrNull() ?: return
        updates.poll(captured::get, force)
    }
    fun checkUpdates() {
        if (!state.changesAvailable) { if (updateContext()?.blocked == false) refresh() else state = state.copy(updateStatus = UpdateStatus.PENDING); return }
        viewModelScope.launch { pollUpdates(force = true) }
    }
    private var sourceRevokeToken: String? = null
    private var moodStorageBlocked = false
    private var moodPersistenceFailed = false
    init {
        try {
            if (preferences.getBoolean("paired-blocked", false)) {
                pairedProfile = vault.read("locked-profile")?.let(PairingPolicy::profile)
                connectionStatus = "未连接 · 旧资料已隔离保留"
            } else {
                credential = vault.read("active-credential")?.let(PairingPolicy::decode)
                pairedProfile = credential?.profile
            }
            credential?.let { baseUrl = it.profile.origin }
            if (pairedMode && (credential == null || credential!!.profile.expired())) {
                if (credential != null) invalidateConnection()
                else state = EchoState(notice = "请在电脑生成此设备的配对令牌，再用 HTTPS 连接。旧地址草稿与未决请求不会自动迁移。")
            } else {
                // Only the original local debug origin may read the legacy origin-only namespace.
                if (!pairedMode) {
                    val legacyDraft = preferences.getString("draft", "").orEmpty()
                    if (!preferences.getBoolean("draft-scope-migrated", false)) {
                        val edit = preferences.edit()
                        if (!preferences.contains(draftKey()) && preferences.contains("draft")) edit.putString(draftKey(), legacyDraft)
                        draftMigrationBlocked = !edit.remove("draft").putBoolean("draft-scope-migrated", true).commit()
                    }
                }
                state = EchoState(draft = readDraft(), memoryDraft = readMemoryDraft(), followupDraft = readFollowupDraft(), topics = readTopics(), moodDraft = readMoodDraft())
                connectionStatus = if (pairedMode) "已配对此设备" else "本机开发连接"
                refresh()
            }
        } catch (_: Exception) {
            dataStorageBlocked = true; credential = null
            state = EchoState(notice = "本机加密凭据或草稿无法读取；内容仍保留，没有使用明文回退。请在电脑核对设备连接。")
            connectionStatus = "本机安全存储待核对"
        }
    }

    private fun moodKey() = "mood-draft-" + scopeKey()
    private fun readMoodDraft(): MoodDraft? {
        val raw = readScoped(moodKey())
        val parsed = raw?.let(MoodDraft::decode)
        moodStorageBlocked = raw != null && parsed == null
        return parsed
    }
    private fun persistMoodDraft(draft: MoodDraft?): Boolean {
        val saved = writeScoped(moodKey(), draft?.encode())
        moodPersistenceFailed = !saved
        state = state.copy(moodDraft = draft, moodLocalSaved = saved)
        if (!saved) tell("心情草稿尚未写入本机，文字暂留当前页面。请先复制；本次不提交，也不会切换后端地址。")
        return saved
    }
    private suspend fun loadMoods() {
        val sid = state.conversation?.id ?: return
        val origin = baseUrl
        state = state.copy(moodsLoaded = false)
        val records = moodRecords(api.get("/api/moods?session_id=" + encoded(sid)))
        if (origin == baseUrl && state.conversation?.id == sid) state = state.copy(moodEntries = records, moodsLoaded = true)
    }
    fun openMoods() = work {
        require(!moodStorageBlocked) { "本机心情草稿暂时无法读取，已保留原文件且不会提交新记录。请先核对本机存储。" }
        require(state.moodsAvailable) { "当前服务尚未支持心情记录。" }
        val sid = state.conversation?.id ?: return@work
        val existing = state.moodDraft
        require(existing == null || existing.sessionId == sid) { "草稿属于另一条后端对话，请先复制和核对；不会自动提交。" }
        state = state.copy(moodEditorOpen = true)
        loadMoods()
        if (state.moodDraft == null) {
            val day = java.time.LocalDate.now().toString()
            persistMoodDraft(MoodDraft.from(sid, day, state.moodEntries.find { it.date == day }))
        }
    }
    fun retryLocalMoodDraft() { if (!state.busy && persistMoodDraft(state.moodDraft)) tell("本机草稿已保存，没有提交到服务端。") }
    fun closeMoods() {
        if (moodPersistenceFailed) { tell("草稿还未写入本机，请先复制或再次保存本机草稿。当前页面为你保留。"); return }
        state = state.copy(moodEditorOpen = false)
    }
    fun chooseMoodDate(day: String) {
        if (!runCatching { java.time.LocalDate.parse(day).toString() == day }.getOrDefault(false)) { tell("请选择有效日期。"); return }
        if (state.busy || !state.moodsLoaded) return
        val sid = state.conversation?.id ?: return
        val previous = state.moodDraft
        if (previous?.dirty == true || previous?.locked == true) { tell("还有心情草稿未核对，先保留或明确放弃，再换日期。"); return }
        persistMoodDraft(MoodDraft.from(sid, day, state.moodEntries.find { it.date == day }))
    }
    fun editMood(x: Double? = null, y: Double? = null, note: String? = null) {
        val draft = state.moodDraft ?: return
        if (state.busy || draft.locked || !state.moodsLoaded) return
        persistMoodDraft(draft.copy(x = x ?: draft.x, y = y ?: draft.y, note = note ?: draft.note,
            xChosen = draft.xChosen || x != null, yChosen = draft.yChosen || y != null, dirty = true))
    }
    fun discardMoodDraft() {
        if (state.busy || state.moodDraft?.operation != null) { tell("保存或删除结果尚未核对，不能放弃冻结请求；请先读取核对。"); return }
        val draft = state.moodDraft ?: return
        persistMoodDraft(MoodDraft.from(draft.sessionId, draft.date, state.moodEntries.find { it.date == draft.date }))
    }
    fun rebaseMoodDraft() {
        val draft = state.moodDraft ?: return
        if (state.busy || !state.moodsLoaded || state.conversation?.id != draft.sessionId) return
        if (draft.operation != null && !draft.conflict) { tell("结果仍待核对。请先读取；不会把未知在途请求当作已停止。"); return }
        persistMoodDraft(draft.rebased(state.moodEntries.find { it.date == draft.date }))
        tell("已保留你的草稿，并采用刚核对的版本。再次保存仍由你决定。")
    }
    fun reconcileMood() = work {
        require(state.moodsAvailable) { "当前服务尚未支持心情记录。" }
        val draft = state.moodDraft
        if (draft == null) {
            loadMoods()
            val sid = state.conversation?.id ?: return@work
            val day = java.time.LocalDate.now().toString()
            persistMoodDraft(MoodDraft.from(sid, day, state.moodEntries.find { it.date == day }))
            return@work
        }
        val origin = baseUrl
        if (draft.ledgerOperation() != null) {
            require(state.moodLedgerAvailable) { "当前服务暂不支持核对原提交，请保留草稿并连接原服务。" }
            try { checkMoodOperation(draft, api, origin) }
            catch (error: Exception) { moodLedgerFailure(draft, origin, error) }
            return@work
        }
        loadMoods()
        if (origin != baseUrl || state.moodDraft != draft || state.conversation?.id != draft.sessionId) return@work
        val current = state.moodEntries.find { it.date == draft.date }
        if (draft.operation == "save" && draft.matches(current)) {
            persistMoodDraft(MoodDraft.from(draft.sessionId, draft.date, current))
            tell("已核对：当前记录与你提交的内容一致。")
        } else if (draft.operation == "delete" && current == null) {
            // Absence is a current observation, not proof of who performed deletion.
            persistMoodDraft(MoodDraft.from(draft.sessionId, draft.date, null))
            tell("已核对：目前没有这一天的记录。")
        } else if (draft.operation != null) {
            persistMoodDraft(draft)
            tell("当前记录与你的提交尚不一致；草稿保留。未知请求可能仍在途，不会自动重发。请继续只读核对，或复制草稿；结果明确前不会开放重新提交。")
        } else tell("已读取最新记录，编辑草稿没有被覆盖。")
    }
    fun saveMood() = work {
        require(state.moodsAvailable && state.moodsLoaded) { "请先读取心情记录。" }
        val draft = state.moodDraft ?: return@work
        require(draft.sessionId == state.conversation?.id)
        val frozen = draft.beginSave(state.moodLedgerAvailable); val origin = baseUrl; val client = api; var writeReturned = false
        check(persistMoodDraft(frozen)) { "本机草稿未持久保存，本次没有提交。" }
        if (frozen.ledgerOperation() != null) { applyMoodOperation(frozen, client, origin); return@work }
        try {
            val receipt = client.put("/api/moods/" + encoded(frozen.date), frozen.body()); writeReturned = true
            if (origin != baseUrl || state.moodDraft != frozen) return@work
            require(frozen.saveReceipt(receipt)) { "回执与本次记录不一致，请只读核对。" }
            loadMoods()
            if (origin != baseUrl || state.moodDraft != frozen) return@work
            val observed = state.moodEntries.find { it.date == frozen.date }
            require(frozen.matches(observed)) { "保存后的记录已变化，请核对。" }
            persistMoodDraft(MoodDraft.from(frozen.sessionId, frozen.date, observed))
            tell("已记录，仍由你决定是否带到聊天。")
        } catch (error: Exception) {
            if (error is CancellationException) throw error
            if (origin == baseUrl && state.moodDraft == frozen) {
                persistMoodDraft(if (writeReturned) frozen else frozen.afterFailure((error as? ApiError)?.status))
                state = state.copy(moodsLoaded = false)
                tell(when {
                    !writeReturned && (error as? ApiError)?.status == 409 -> "这一天已在其他窗口更改，草稿保留。先读取最新版本，再明确决定。"
                    !writeReturned && (error as? ApiError)?.status in listOf(400, 422) -> "服务未接受这次保存，草稿保留。先读取核对，再修改后提交。"
                    else -> "保存结果尚未确认，草稿和原提交保留。先读取核对，不自动重发。"
                })
            }
        }
    }
    fun deleteMood() = work {
        require(state.moodsAvailable && state.moodsLoaded)
        val draft = state.moodDraft ?: return@work
        require(draft.sessionId == state.conversation?.id && !draft.dirty)
        val frozen = draft.beginDelete(state.moodLedgerAvailable); val origin = baseUrl; val client = api; var writeReturned = false
        check(persistMoodDraft(frozen))
        if (frozen.ledgerOperation() != null) { applyMoodOperation(frozen, client, origin); return@work }
        try {
            val receipt = client.call("DELETE", "/api/moods/" + encoded(frozen.date) + "?session_id=" + encoded(frozen.sessionId) + "&expected_updated_at=" + encoded(frozen.expectedUpdatedAt!!)); writeReturned = true
            if (origin != baseUrl || state.moodDraft != frozen) return@work
            require(receipt.opt("deleted") == true) { "删除回执不明确。" }
            loadMoods()
            if (origin != baseUrl || state.moodDraft != frozen) return@work
            require(state.moodEntries.none { it.date == frozen.date }) { "记录仍存在，请核对。" }
            persistMoodDraft(MoodDraft.from(frozen.sessionId, frozen.date, null)); tell("已核对：目前没有这一天的记录。")
        } catch (error: Exception) {
            if (error is CancellationException) throw error
            if (origin == baseUrl && state.moodDraft == frozen) {
                persistMoodDraft(if (writeReturned) frozen else frozen.afterFailure((error as? ApiError)?.status)); state = state.copy(moodsLoaded = false)
                tell(if (!writeReturned && (error as? ApiError)?.status in listOf(400, 422))
                    "服务未接受这次删除，原记录和版本保留。请先重新读取核对。"
                    else "删除结果尚未确认，原记录和版本保留。先读取核对，不自动再次删除。")
            }
        }
    }
    private fun ownsMood(draft: MoodDraft, origin: String) = origin == baseUrl && state.conversation?.id == draft.sessionId && state.moodDraft == draft
    private fun moodLedgerFailure(draft: MoodDraft, origin: String, error: Exception) {
        if (error is CancellationException) throw error
        if (!ownsMood(draft, origin)) return
        state = state.copy(moodsLoaded = false)
        tell(if (draft.cancelRequested) "取消结果仍待核对，草稿和取消意图保留；不会再提交这个请求。请核对或再次取消。"
            else "这次提交的结果仍待核对，草稿和原请求已保留。可以核对、用原请求重试，或取消；不会自动重发。")
    }
    private suspend fun consumeMoodReceipt(draft: MoodDraft, receipt: MoodOperationReceipt, origin: String) {
        if (!ownsMood(draft, origin)) return
        if (receipt.state == "not_found") {
            tell(if (draft.cancelRequested) "服务暂未找到原请求，取消意图仍保留。请再次取消；不会重新提交。"
                else "服务暂未找到原请求，这不代表在途请求已停止。可由你选择原请求重试或取消。")
            return
        }
        loadMoods() // receipt is historical; separately read the current row before unlocking
        if (!ownsMood(draft, origin) || !state.moodsLoaded) return
        val next = draft.afterLedgerReceipt(receipt, state.moodEntries.find { it.date == draft.date })
        persistMoodDraft(next)
        tell(when {
            receipt.state == "cancelled" -> Shared.COPY_MOOD_RECOVERY_CANCELLED + "先核对当前记录，再决定继续编辑。"
            receipt.state == "conflict" -> "这一天已在其他窗口更改；草稿保留。请查看刚读取的记录，再明确采用当前版本。"
            next.conflict -> Shared.COPY_MOOD_RECOVERY_APPLIED + "当前记录后来已变化，草稿保留；先核对再决定。"
            draft.cancelRequested -> Shared.COPY_MOOD_RECOVERY_APPLIED
            else -> "已核对这次提交和当前记录，仍由你决定是否带到聊天。"
        })
    }
    private suspend fun checkMoodOperation(draft: MoodDraft, client: EchoApi, origin: String): MoodOperationReceipt {
        val identity = draft.ledgerOperation() ?: error("旧提交只支持读取记录核对。")
        val receipt = moodOperationReceipt(client.get("/api/mood-operations/" + encoded(identity.requestId) + "?session_id=" + encoded(draft.sessionId)), draft.sessionId, identity)
        consumeMoodReceipt(draft, receipt, origin)
        return receipt
    }
    private suspend fun applyMoodOperation(draft: MoodDraft, client: EchoApi, origin: String) {
        try {
            require(!draft.cancelRequested) { "已经决定取消的请求不会再次提交。" }
            val identity = draft.ledgerOperation() ?: error("原请求标识缺失。")
            val receipt = moodOperationReceipt(client.post("/api/mood-operations", identity.applyBody(draft.sessionId)), draft.sessionId, identity)
            require(receipt.state != "not_found") { "提交回执尚不能核对。" }
            consumeMoodReceipt(draft, receipt, origin)
        } catch (error: Exception) { moodLedgerFailure(draft, origin, error) }
    }
    fun retryMoodOperation() = work {
        val draft = state.moodDraft ?: return@work
        require(state.moodLedgerAvailable && !draft.cancelRequested && draft.ledgerOperation() != null) { "这份草稿暂不能重试提交。" }
        require(draft.sessionId == state.conversation?.id)
        val origin = baseUrl; val client = api
        try {
            val receipt = checkMoodOperation(draft, client, origin)
            if (receipt.state == "not_found" && ownsMood(draft, origin)) {
                check(persistMoodDraft(draft)) { "原请求尚未写入本机，本次没有重试。" }
                applyMoodOperation(draft, client, origin) // exact saved bytes and ID, never reconstruct
            }
        } catch (error: Exception) { moodLedgerFailure(draft, origin, error) }
    }
    fun cancelMoodOperation() = work {
        val draft = state.moodDraft ?: return@work
        require(state.moodLedgerAvailable && draft.sessionId == state.conversation?.id)
        val frozen = draft.requestCancellation(); val origin = baseUrl; val client = api
        check(persistMoodDraft(frozen)) { "取消意图尚未写入本机，本次没有发送。草稿和取消选择保留。" }
        try {
            val identity = frozen.ledgerOperation()!!
            val receipt = moodOperationReceipt(client.post("/api/mood-operations/" + encoded(identity.requestId) + "/cancel", identity.cancelBody(frozen.sessionId)), frozen.sessionId, identity)
            require(receipt.state != "not_found")
            consumeMoodReceipt(frozen, receipt, origin)
        } catch (error: Exception) { moodLedgerFailure(frozen, origin, error) }
    }
    fun moodToChat(): String? {
        val draft = state.moodDraft ?: return null
        if (state.busy || !state.moodsLoaded || draft.dirty || draft.locked) { tell("请先保存或核对当前记录，再决定带到聊天。"); return null }
        val record = state.moodEntries.find { it.date == draft.date && it.updatedAt == draft.expectedUpdatedAt } ?: return null
        return moodChatText(record)
    }

    private fun followupKey() = "followup-draft-" + scopeKey()
    private fun readFollowupDraft() = readScoped(followupKey())?.let(FollowupDraft::decode)
    private fun persistFollowupDraft(value: FollowupDraft?): Boolean {
        state = state.copy(followupDraft = value)
        val saved = writeScoped(followupKey(), value?.encode())
        if (!saved) tell("未能持久保存跟进草稿，请先复制文字再继续。")
        return saved
    }
    
    fun selectTopic(value: String) { state = state.copy(selectedTopic = value) }
    fun tagMessage(id: String, label: String) {
        runCatching { TopicPolicy.assign(state.topics, id, label) }.onSuccess {
            check(writeScoped("topics-" + scopeKey(), JSONObject(it).toString())) { "话题尚未保存，请先核对本机存储。" }
            state = state.copy(topics = it, selectedTopic = label.trim())
        }.onFailure { tell(it.message.orEmpty()) }
    }
    fun focusMessage(id: String) { state = state.copy(focusMessageId = id, selectedTopic = "全部") }
    fun clearMessageFocus() { state = state.copy(focusMessageId = null) }

    fun draft(value: String) { state = state.copy(draft = value); if (!writeScoped(draftKey(), value)) tell("草稿尚未写入安全存储，文字仍留在当前页；请先复制。") }
    fun tell(value: String) { state = state.copy(notice = value) }
    fun preferences(value: Comfort) {
        comfort = value.copy(lightIntensity = value.lightIntensity.coerceIn(Shared.MIN_LIGHT_INTENSITY, Shared.MAX_LIGHT_INTENSITY))
        preferences.edit().putBoolean("reduce_motion", comfort.reduceMotion).putBoolean("reduce_transparency", comfort.reduceTransparency).putFloat("light_intensity", comfort.lightIntensity).apply()
    }
    fun endpoint(value: String) {
        if (moodPersistenceFailed && !persistMoodDraft(state.moodDraft)) { tell("心情草稿未写入本机，已保留当前页面；请先复制或保存，暂不切换地址。"); return }
        if (draftMigrationBlocked) { tell("草稿迁移尚未保存，请先复制文字并重启应用后再更换地址。"); return }
        if (state.busy || state.pending != null) { tell("先核对当前发送状态，再更改后端地址。"); return }
        runCatching { EndpointPolicy.validate(value, BuildConfig.DEBUG).also { require(it.startsWith("http:")) { "HTTPS 需要填写设备令牌并验证配对。" } } }.onSuccess {
            check(vault.useLocal(it, pairedProfile)) { "地址尚未保存，保持原连接。" }
            credential = null; pairedProfile = null; connectionEpoch.advance(); connectionStatus = "本机开发连接"
            baseUrl = it
            loadSavedConnections()
            state = EchoState(draft = readDraft(), memoryDraft = readMemoryDraft(), followupDraft = readFollowupDraft(), topics = readTopics(), moodDraft = readMoodDraft()); refresh()
        }.onFailure { tell(it.message.orEmpty()) }
    }
    fun loadSavedConnections() {
        runCatching { vault.savedProfiles() }.onSuccess { savedConnections = it }.onFailure { tell("旧连接身份暂时无法读取，原加密资料仍保留，没有删除。") }
    }
    fun restoreSavedConnection(profile: PairedProfile) {
        if (state.busy || dataStorageBlocked) return
        val saved = runCatching { vault.savedCredential(profile) }.getOrElse { tell("本机加密凭据无法读取；原资料仍保留，没有明文回退。"); return }
        if (saved == null) { tell("这份身份的本机令牌已移除或失效。可填写仍有效的原设备令牌；否则请在电脑核对原记录，不会换身份重发。"); return }
        pairDevice(profile.origin, saved.token, profile)
    }
    fun removeSavedConnection(profile: PairedProfile) {
        if (state.busy) return
        runCatching { check(vault.eraseSavedProfile(profile)) { "本机移除未保存，原内容仍保留。" } }.onSuccess {
            if (pairedProfile?.scope == profile.scope && credential == null) { pairedProfile = null; dataStorageBlocked = false; state = EchoState(); connectionEpoch.advance() }
            loadSavedConnections(); tell("已移除此身份的本机草稿与未决请求副本；没有撤销服务端许可，也没有取消已发送的操作，请在电脑核对。")
        }.onFailure { tell(it.message.orEmpty()) }
    }
    fun pairDevice(address: String, rawToken: String, recovery: PairedProfile? = null) {
        if (state.busy || dataStorageBlocked || moodPersistenceFailed) { tell("请先完成当前操作并核对本机草稿保存，再配对设备。"); return }
        val token = rawToken.trim()
        val origin = runCatching { PairingPolicy.origin(address).also { require(PairingPolicy.validToken(token)) { "设备令牌格式不正确。" } } }.getOrElse { tell(it.message.orEmpty()); return }
        val epoch = connectionEpoch.value
        viewModelScope.launch {
            state = state.copy(busy = true)
            try {
                val verifier = EchoApi(origin, DeviceAuthorization(token), requireCurrent = { connectionEpoch.requireCurrent(epoch) }, onInvalidCredential = { error ->
                    if (recovery != null && error.status == 401) {
                        check(vault.retireSavedCredential(recovery)) { "失效凭据移除尚未保存，请先在电脑核对。" }
                        if (credential?.profile?.scope == recovery.scope) invalidateConnection(error)
                    }
                })
                val verified = PairingPolicy.verify(origin, token, verifier.get("/api/paired-device"))
                val accepted = recovery?.let { PairingPolicy.restore(verified, it) } ?: verified
                connectionEpoch.requireCurrent(epoch)
                check(vault.activate(accepted, pairedProfile)) { "配对已验证，但未能安全保存凭据；原连接仍保留。" }
                // Activate only after the complete receipt and encrypted write succeeded.
                credential = accepted; pairedProfile = accepted.profile; baseUrl = origin
                preferences.edit().putString("endpoint", origin).commit()
                connectionEpoch.advance(); connectionStatus = "已配对此设备"
                state = EchoState(draft = readDraft(), memoryDraft = readMemoryDraft(), followupDraft = readFollowupDraft(), topics = readTopics(), moodDraft = readMoodDraft(), busy = true)
                reload()
                loadSavedConnections()
                tell(if (recovery == null) "已接回你自己的回响。旧身份草稿与未决请求没有迁移。" else "已验证并恢复原设备身份。旧草稿与原请求标识保留，请明确核对；没有自动重发。")
            } catch (error: Exception) {
                if (connectionEpoch.accepts(epoch)) tell("配对未完成，原连接与草稿仍保留。" + (error.message ?: "请核对 HTTPS 与设备令牌。"))
                else if (credential != null) tell("设备已配对，暂未读到完整内容；可点重新连接。" + error.message.orEmpty())
            } finally { state = state.copy(busy = false) }
        }
    }
    fun disconnectDevice() {
        if (state.busy || !pairedMode) return
        invalidateConnection()
        tell("已停止使用此设备令牌。原加密草稿和未决请求保留在原身份下；这不会撤销电脑上的设备许可，请在电脑撤销。")
    }
    private fun work(block: suspend () -> Unit) {
        if (state.busy) return
        if (dataStorageBlocked) { tell("本机安全存储无法核对，未发送请求；原内容仍保留。"); return }
        if (pairedMode && (credential == null || credential!!.profile.expired())) { if (credential != null) invalidateConnection(); else tell("设备尚未连接，请先在设置中验证配对。旧未决请求仍保留。"); return }
        val epoch = connectionEpoch.value
        viewModelScope.launch { state = state.copy(busy = true); try { block() } catch (error: Exception) { if (connectionEpoch.accepts(epoch)) tell(error.message ?: "操作未能完成，请核对连接。") } finally {
            if (!connectionEpoch.accepts(epoch) && pairedMode && credential == null) state = EchoState(notice = "设备连接已停止。旧草稿和未决请求已隔离保留，请在电脑核对后重新配对。")
            else state = state.copy(busy = false)
        } }
    }
    private suspend fun reload() {
        credential?.let { existing ->
            val verified = PairingPolicy.verify(existing.profile.origin, existing.token, api.get("/api/paired-device"), generation = existing.profile.credentialGeneration)
            if (verified.profile.serviceInstanceId != existing.profile.serviceInstanceId || verified.profile.conversationId != existing.profile.conversationId || verified.profile.deviceId != existing.profile.deviceId) {
                invalidateConnection(ApiError(409, "服务或设备身份已变化。", "service_instance_mismatch"))
                error("服务或设备身份已变化，请重新配对。")
            }
        }
        val current = conversation(api.get("/api/conversation"))
        require(pairedProfile == null || pairedProfile?.conversationId == current.id) { "服务返回了另一条对话；没有恢复本机草稿或发送请求。" }
        require(state.conversation == null || state.conversation?.id == current.id) { "服务的主对话发生变化，已保留草稿并停止更新。请核对后端地址与数据。" }
        state = state.copy(conversation = current, pending = readPending())
        state.memoryDraft?.takeIf { it.id != null }?.let { draft ->
            val latest = current.memories.find { it.id == draft.id }
            if (latest?.version != draft.expectedVersion) persistMemoryDraft(draft.withConflict(latest))
        }
        val actions = if (pairedMode) emptyList() else savedActions(api.get("/api/actions?session_id=${encoded(current.id)}"))
        val next = if (pairedMode) JSONObject() else api.get("/api/next-step?session_id=${encoded(current.id)}")
        val capabilities = try { api.get("/api/capabilities") } catch (error: ApiError) { if (error.status == 404) JSONObject() else throw error }
        val features = capabilities.optJSONObject("features")
        state = state.copy(actions = actions, nextStep = next.str("step"), memoryVersioning = features?.optBoolean("memory_expected_version_patch") == true && features?.optBoolean("memory_expected_version_delete") == true, followupsAvailable = features?.optBoolean("in_app_one_time_followups") == true, targetedDeliveryStop = features?.optBoolean("chat_delivery_targeted_stop") == true, recurringFollowups = features?.optBoolean("in_app_recurring_followups") == true, boundedFollowups = features?.optBoolean("bounded_followup_contact") == true, boundaryAvailable = features?.optBoolean("companion_boundaries") == true, moodsAvailable = features?.opt("daily_mood_entries") == true, moodLedgerAvailable = features?.opt("mood_operation_ledger") == true, changesAvailable = features?.opt("conversation_change_cursor") == true)
        state = state.copy(descriptors = api.get("/api/onboarding/sources").rows("sources").filter { !pairedMode || it.str("id") == "local_files" })
        if (state.followupsAvailable) loadFollowups()
        if (state.boundaryAvailable) loadBoundary()
    }
    fun refresh() = work {
        reload()
        state.pending?.takeIf { it.sessionId == state.conversation?.id }?.let { turn -> consume(api.get("/api/chat/turn/${encoded(turn.id)}?session_id=${encoded(turn.sessionId)}"), turn.id) }
    }
    /** Reconcile server-timed delivery without resending or replacing newer local state. */
    suspend fun refreshDelivery() {
        val before = state.conversation ?: return
        if (state.busy || before.messages.none { it.deliveryPending }) return
        val origin = baseUrl
        try {
            val snapshot = conversation(api.get("/api/conversation"))
            if (!state.busy && baseUrl == origin && state.conversation == before && snapshot.id == before.id)
                state = state.copy(conversation = snapshot)
        } catch (error: Exception) {
            if (error is CancellationException) throw error
            if (baseUrl == origin && state.conversation == before) tell("暂时没能更新正在发送的内容，已有文字仍保留。")
        }
    }
    fun stopDelivery(message: Message) = work {
        val before = state.conversation ?: return@work
        val attempt = DeliveryStopAttempt(baseUrl, before.id, message.id)
        // Old services have the same URL but may ignore message_id. Never probe
        // them with a mutation: only the explicit targeted-stop flag permits it.
        require(attempt.canStart(state.targetedDeliveryStop, baseUrl, before) && state.pending == null) { "这条回复已变化，或服务尚不支持精确停止；请先刷新核对。" }
        val client = api
        var receipt: JSONObject? = null
        var problem = ""
        try { val request = attempt.request(); receipt = client.post(request.path, request.body) }
        catch (error: Exception) { problem = error.message.orEmpty() }
        if (baseUrl != attempt.endpoint || state.conversation != before) return@work
        val fresh = try { conversation(client.get("/api/conversation")) } catch (error: Exception) { problem = error.message.orEmpty(); null }
        if (baseUrl != attempt.endpoint || state.conversation != before) return@work
        if (fresh?.id == attempt.sessionId) state = state.copy(conversation = fresh)
        tell(if (attempt.reconciled(receipt, fresh)) "这条回复已停止展开，已显示的话仍保留。"
            else "停止展开的结果待核对；已尝试刷新，不会自动再次停止。" + if (problem.isNotBlank()) " $problem" else "")
    }
    private suspend fun loadBoundary() {
        val sid = state.conversation?.id ?: return
        val value = try { companionBoundary(api.get("/api/companion-boundary?session_id=" + encoded(sid))) }
        catch (error: Exception) { if (state.conversation?.id == sid) state = state.copy(boundary = null); throw error }
        if (state.conversation?.id == sid) state = state.copy(boundary = value)
    }
    fun refreshBoundary() = work { if (state.boundaryAvailable) loadBoundary() }
    fun changeBoundary(mode: String) = work {
        require(state.boundaryAvailable) { "当前服务尚未支持统一陪伴边界。" }
        val sid = state.conversation?.id ?: return@work
        val origin = baseUrl; val client = api
        val current = state.boundary ?: error("先重新读取陪伴边界，再选择。")
        val change = boundaryChange(sid, current, mode)
        try {
            val receipt = companionBoundary(client.put("/api/companion-boundary", change.body()))
            require(change.matches(receipt)) { "设置回执待核对。" }
            if (baseUrl == origin && state.conversation?.id == sid) {
                state = state.copy(boundary = receipt)
                tell(if (mode == "active") "已恢复按约定轻问，失效的旧队列不会补发。" else "先安静陪着；聊天和待办仍可查看。")
            }
        } catch (error: Exception) {
            if (baseUrl != origin || state.conversation?.id != sid) return@work
            state = state.copy(boundary = null)
            runCatching { loadBoundary() }
            tell(if ((error as? ApiError)?.status == 409) "边界已在其他端变化，已尝试刷新；请核对后再选择。"
                 else "设置结果需核对，已尝试读取当前状态；不会自动重试。")
        }
    }
    private suspend fun loadFollowups() {
        val sid = state.conversation?.id ?: return
        val records = followups(api.get("/api/followups?session_id=${encoded(sid)}")).filter { it.sessionId == sid }
        state = state.copy(followups = records)
        state.followupDraft?.matching(records)?.let { persistFollowupDraft(null); state = state.copy(followupEditorOpen = false); tell("已核对，上次跟进保存成功。") }
    }
    fun refreshFollowups() = work { if (state.followupsAvailable) loadFollowups() }
    fun openFollowup() {
        val sid = state.conversation?.id ?: return
        if (state.followupDraft == null) persistFollowupDraft(FollowupDraft(sid, timeZone = java.time.ZoneId.systemDefault().id, contactFieldsIncluded = state.boundedFollowups))
        state = state.copy(followupEditorOpen = true)
    }
    fun closeFollowup() { state = state.copy(followupEditorOpen = false) }
    fun editFollowup(content: String? = null, dueAt: String? = null, repeatRule: String? = null, timeZone: String? = null,
                     quietStart: String? = null, quietEnd: String? = null, allowContact: Boolean? = null,
                     window: Int? = null, topic: String? = null) {
        val draft = state.followupDraft?.takeIf { it.requestId.isEmpty() } ?: return
        persistFollowupDraft(draft.copy(content = content ?: draft.content, dueAt = if (timeZone != null && timeZone != draft.timeZone) "" else dueAt ?: draft.dueAt,
            repeatRule = repeatRule ?: draft.repeatRule, timeZone = timeZone ?: draft.timeZone,
            quietStart = quietStart ?: draft.quietStart, quietEnd = quietEnd ?: draft.quietEnd,
            allowContact = allowContact ?: draft.allowContact, contactWindowMinutes = window ?: draft.contactWindowMinutes,
            contactTopic = topic ?: draft.contactTopic, contactFieldsIncluded = state.boundedFollowups))
    }
    fun discardFollowup() { if (state.followupDraft?.requestId?.isNotEmpty() == true) { tell("原保存请求仍待核对，不能丢弃标识。请刷新跟进列表。"); return }; persistFollowupDraft(null); closeFollowup() }
    fun saveFollowup() = work {
        require(state.followupsAvailable) { "当前服务尚未支持本机跟进，请更新服务后刷新。" }
        val sid = state.conversation?.id ?: return@work
        val original = state.followupDraft ?: return@work
        require(original.sessionId == sid) { "这份跟进属于此前对话，文字保留；请先核对服务数据。" }
        if (original.requestId.isNotEmpty()) { loadFollowups(); if (state.followupDraft == null) return@work }
        require(original.repeatRule == "once" || state.recurringFollowups) { "当前服务尚未支持每日跟进，请更新服务后再试。" }
        require(!original.allowContact || state.boundedFollowups) { "当前服务尚未支持有界轻问，请更新服务。" }
        val attempt = original.beginSave()
        val draft = attempt.request
        check(persistFollowupDraft(draft)) { "请求标识未能保存，没有发送跟进；请先复制文字再继续。" }
        try {
            val saved = followup(api.post("/api/followups", draft.body()))
            require(saved.id.isNotEmpty() && draft.matching(listOf(saved)) != null) { "跟进回执不完整，保存结果仍需核对。" }
        } catch (error: Exception) {
            val retained = attempt.afterFailure((error as? ApiError)?.status, (error as? ApiError)?.code.orEmpty())
            persistFollowupDraft(retained)
            tell(if (retained.requestId.isEmpty()) "这次明确未保存：${error.message.orEmpty()}。文字保留，可以修改后重新确认。"
                else "跟进保存结果需核对：${error.message.orEmpty()}。原请求标识与文字保留，不会自动换编号或重试。")
            return@work
        }
        persistFollowupDraft(null); closeFollowup()
        try { loadFollowups(); tell("已保存。只在打开回响时查看，不会发送手机通知。") }
        catch (_: Exception) { tell("已收到保存回执；列表暂时未能刷新，请稍后再看。不会重复保存。") }
    }
    fun changeFollowup(item: Followup, status: String) = work {
        require(item.sessionId == state.conversation?.id && item.status == "pending" && item.supportsNativeTransitions && status in setOf("done", "cancelled", "paused", "resumed") && (item.repeatRule == "once" || state.recurringFollowups) && (status in setOf("done", "cancelled") || state.recurringFollowups)) { "此跟进请在 Web 端管理，或刷新后核对状态。" }
        try {
            val request = followupTransitionRequest(item, status)
            val changed = followup(api.post(request.path, request.body))
            require(followupTransitionMatches(item, status, changed)) { "回执状态待核对。" }
            loadFollowups(); tell(when (status) { "done" -> if (item.repeatRule == "daily") "本次已完成，下次时间已更新。" else "已标记完成。"; "paused" -> "已暂停这条跟进。"; "resumed" -> "已恢复这条跟进，错过的窗口不会补问。"; else -> "已取消这次跟进。" })
        } catch (error: Exception) { loadFollowups(); tell("更新结果需核对，已刷新列表；不会自动再执行。${error.message.orEmpty()}") }
    }
    fun bringToChat(text: String) { draft(listOf(state.draft, text).filter { it.isNotBlank() }.joinToString("\n")) }
    fun send() {
        if (dataStorageBlocked) { tell("原发送账本或安全存储待核对，未创建新请求；原内容仍保留。"); return }
        if (pairedMode && (credential == null || credential!!.profile.expired())) { if (credential != null) invalidateConnection(); else tell("请先核对设备连接，没有创建发送请求。"); return }
        val conversation = state.conversation ?: return
        val text = state.draft.trim()
        if (state.busy || state.pending != null || text.isBlank()) return
        if (text.codePointCount(0, text.length) > 4000) { tell("这段话已保留，请缩短到 4000 字再发送。"); return }
        val turn = PendingTurn.new(conversation.id, text, memoryProposals = memoryProposals)
        runCatching { savePending(turn) }.onFailure { tell(it.message.orEmpty()); return }
        draft(""); sendPending(turn)
    }
    private fun restoreBudgetRejected(expectedId: String) {
        val turn = state.pending?.takeIf { it.id == expectedId && it.sessionId == state.conversation?.id } ?: return
        bringToChat(turn.text)
        savePending(null)
        tell("近 60 分钟聊天额度已用完，这次没有保存为用户消息。原话已放回输入框，请稍后再发送；不会自动重试。")
    }
    private fun consume(obj: JSONObject, expectedId: String) {
        val pending = state.pending ?: return
        if (pending.id != expectedId || pending.sessionId != state.conversation?.id) return
        if (isDefinitiveBudgetRejection(errorCode = obj.str("error_code"))) { restoreBudgetRejected(expectedId); return }
        val outcome = obj.optJSONObject("result") ?: obj
        if (outcome.has("messages")) {
            val current = state.conversation ?: return
            val fresh = current.copy(messages = messages(outcome), memories = memories(outcome))
            state = state.copy(conversation = fresh, memoryOffer = if (memoryProposals && !outcome.optBoolean("cancelled")) quoteOffer(outcome, pending, fresh) else null, notice = if (outcome.optBoolean("cancelled")) "已停止这次回复，已发送的话仍保留。" else "")
            savePending(null)
        } else tell(when (obj.str("status")) { "unknown" -> "服务端不能确认这次回复是否完成。请核对记录，不会自动重发。"; else -> "这次回复仍在处理中；可稍后核对或停止。" })
    }
    private fun sendPending(turn: PendingTurn) = work {
        state = state.copy(chatSending = true)
        try {
            val result = api.post("/api/chat", turn.body())
            val current = state.pending
            if (current?.id != turn.id) return@work
            if (current.cancelWanted) consume(api.post("/api/chat/turn/${encoded(turn.id)}/cancel", json("session_id" to turn.sessionId)), turn.id) else consume(result, turn.id)
        } catch (error: Exception) {
            if (error is ApiError && isDefinitiveBudgetRejection(httpStatus = error.status)) { restoreBudgetRejected(turn.id); return@work }
            // Never invent success or create a second request ID after a response is lost.
            tell("发送结果尚未确认。原话和标识保存在本机，请点「核对状态」。${error.message.orEmpty()}")
        } finally { state = state.copy(chatSending = false) }
    }
    fun recover() = work {
        val turn = state.pending ?: return@work
        consume(api.get("/api/chat/turn/${encoded(turn.id)}?session_id=${encoded(turn.sessionId)}"), turn.id)
    }
    fun retrySameId() = work {
        val turn = state.pending ?: return@work
        val record = api.get("/api/chat/turn/${encoded(turn.id)}?session_id=${encoded(turn.sessionId)}")
        consume(record, turn.id)
        if (state.pending != null) tell("原发送仍未确认，已保留同一个标识；不会再次发送。请核对记录或停止后再决定。")
    }
    fun cancelTurn() {
        val turn = state.pending ?: return
        val epoch = connectionEpoch.value
        val client = runCatching { api }.getOrElse { tell(it.message.orEmpty()); return }
        runCatching { savePending(turn.copy(cancelWanted = true)) }.onFailure { tell(it.message.orEmpty()); return }
        viewModelScope.launch {
            try { consume(client.post("/api/chat/turn/${encoded(turn.id)}/cancel", json("session_id" to turn.sessionId)), turn.id) }
            catch (_: Exception) { if (connectionEpoch.accepts(epoch)) tell("已记下停止请求，结果仍待核对；不会自动重发。") }
        }
    }
    fun returnUncertainText() = work {
        val turn = state.pending ?: return@work
        val sid = state.conversation?.id ?: return@work
        if (turn.sessionId == sid) {
            val record = api.get("/api/chat/turn/${encoded(turn.id)}?session_id=${encoded(turn.sessionId)}")
            if (record.has("result")) { consume(record, turn.id); tell("已核对并取回原回复，无需重复发送。"); return@work }
            require(mayReturnTextAfterReview(turn.sessionId, sid, record.str("status"))) { "原请求仍在处理中，请先停止或继续核对；没有换标识重新发送。" }
        }
        reload(); bringToChat(turn.text); savePending(null)
        tell("已重新读取当前记录，并把原话放回输入框。请先核对是否已经保存，再决定发送。")
    }
    private suspend fun memoryChange(memory: Memory, block: suspend () -> Unit): Boolean {
        require(state.memoryVersioning) { "当前服务尚未提供记忆版本核对，已停止修改。请更新服务后刷新；原文仍保留。" }
        try { block(); reload(); return true }
        catch (error: ApiError) {
            if (error.status == 409) {
                reload()
                state.memoryDraft?.takeIf { it.id == memory.id }?.let { draft -> persistMemoryDraft(draft.withConflict(state.conversation?.memories?.find { it.id == memory.id })) }
                tell("这条记忆已在其他地方更新。已刷新最新版本，原来的修改保留；请重新核对后再决定，不会覆盖。")
                return false
            } else throw error
        }
    }
    fun confirmMemory(memory: Memory) = work { memoryChange(memory) { val request = memoryPatchRequest(memory, confirm = true); api.call("PATCH", request.path, request.body) } }
    fun forget(memory: Memory) = work { if (memoryChange(memory) { api.call("DELETE", memoryDeletePath(memory)) }) tell("已忘掉这条；关联来源可能暂停，请查看连接页。") }
    fun history(memory: Memory) = work { state = state.copy(revisions = api.get("/api/memory/${encoded(memory.id)}/history").rows("revisions")) }
    fun dismissMemoryOffer() { state = state.copy(memoryOffer = null) }
    fun dismissQuoteReview() { state = state.copy(quoteForReview = null) }
    fun prepareQuoteCandidate() {
        val review = state.quoteForReview ?: return
        if (state.memoryDraft != null) { tell("已有记忆草稿保留，请先处理；这句原话也仍保留在聊天中。"); return }
        runCatching { review.candidate(state.conversation) }.onSuccess { draft ->
            persistMemoryDraft(draft)
            state = state.copy(quoteForReview = null, memoryEditorOpen = true)
            tell("原话已放入编辑框，尚未保存；请整理后明确保存为候选记忆。")
        }.onFailure { tell(it.message.orEmpty()) }
    }
    fun rememberQuote(message: Message) = work {
        require(state.pending == null) { "先核对当前发送状态，再选择原话。" }
        val review = quoteReview(message, state.conversation) ?: error("原话已变化，请先刷新核对。")
        state = state.copy(quoteForReview = null)
        try {
            val request = quoteRequest(review)
            val saved = memory(api.post(request.path, request.body))
            require(review.matches(state.conversation) && quoteReceiptMatches(review, saved)) { "原话保存回执尚未确认，请在记忆中核对。" }
            state = state.copy(memoryOffer = null)
            reload(); tell("已记下这句原话，可在记忆中修改或忘掉。")
        } catch (error: Exception) {
            val manual = (error as? ApiError)?.let { quoteReviewAfterRejection(message, state.conversation, it.status) }
            if (manual != null) {
                state = state.copy(quoteForReview = manual, memoryOffer = null)
                tell("这句尚未直接选存。原话保留，可以整理为候选记忆，再由你明确保存；不会自动记下。")
            } else tell("原话保存结果待核对，请在记忆中查看；不会自动重试。${error.message.orEmpty()}")
        }
    }
    fun openMemoryEditor(memory: Memory? = null) {
        if (state.memoryDraft != null) { state = state.copy(memoryEditorOpen = true); tell("先接着处理已保留的记忆草稿；关闭不会丢失文字。"); return }
        persistMemoryDraft((memory?.let(MemoryDraft::editing) ?: MemoryDraft()).copy(sessionId = state.conversation?.id.orEmpty()))
        state = state.copy(memoryEditorOpen = true)
    }
    fun closeMemoryEditor() { state = state.copy(memoryEditorOpen = false) }
    fun discardMemoryDraft() { persistMemoryDraft(null); state = state.copy(memoryEditorOpen = false) }
    fun editMemoryDraft(text: String) { state.memoryDraft?.let { persistMemoryDraft(it.copy(text = text)) } }
    fun rebaseMemoryDraft() { runCatching { state.memoryDraft?.rebase() }.onSuccess { if (it != null) persistMemoryDraft(it) }.onFailure { tell(it.message.orEmpty()) } }
    fun saveMemoryDraft() = work {
        val draft = state.memoryDraft ?: return@work
        val sid = state.conversation?.id ?: return@work
        require(draft.sessionId == sid) { "这份草稿属于此前的对话，文字保留；请先核对服务数据，不能接入当前对话。" }
        require(draft.id == null || (draft.expectedVersion ?: 0) >= 1) { "没有可核对的版本；请保留文字并重新打开这条记忆。" }
        require(draft.id == null || state.memoryVersioning) { "当前服务尚未提供记忆版本核对，草稿保留；请更新服务后刷新。" }
        require(draft.text.isNotBlank() && draft.text.codePointCount(0, draft.text.length) <= 2000) { "记忆内容需为 1–2000 字；草稿保留。" }
        require(!draft.conflict && !draft.uncertain) { "请先核对当前版本或保存结果；不会覆盖或重复创建。" }
        try {
            if (draft.id == null) { val request = manualMemoryRequest(draft, sid); api.post(request.path, request.body) }
            else api.call("PATCH", "/api/memory/${encoded(draft.id)}", json("text" to draft.text, "expected_version" to draft.expectedVersion))
            persistMemoryDraft(null); state = state.copy(memoryEditorOpen = false); reload()
            tell(if (draft.id == null) "已加入待确认记忆；你可以核对后点「是的」。" else "已保存纠正；相关来源和派生内容将重新核对。")
        } catch (error: Exception) {
            if (error is ApiError && error.status == 409) {
                reload(); persistMemoryDraft(draft.withConflict(state.conversation?.memories?.find { it.id == draft.id }))
                tell("这条记忆已有更新。最新内容与原草稿都保留，请核对后决定；不会自动重试。")
            } else {
                if (error !is ApiError || error.status >= 500) persistMemoryDraft(draft.copy(uncertain = true))
                tell("保存未确认，文字保留。请刷新记忆核对；不会自动重复保存。${error.message.orEmpty()}")
            }
        }
    }
    fun sources() = work { state = state.copy(descriptors = api.get("/api/onboarding/sources").rows("sources").filter { !pairedMode || it.str("id") == "local_files" }) }
    fun revoke(source: Source) = work {
        val sid = state.conversation?.id ?: return@work
        val attempt = SourceRevocationAttempt(baseUrl, sid, source)
        if (!attempt.canStart(baseUrl, state.conversation)) { tell("这份资料已变化，请刷新连接列表重新核对；没有发出移除请求。"); return@work }
        val client = api
        sourceRevokeToken = attempt.token
        state = state.copy(nextStep = "") // do not keep showing a suggestion based on this attempted withdrawal
        try {
            var receipt: JSONObject? = null
            var problem = ""
            try { receipt = client.post("/api/source/revoke", attempt.body()) }
            catch (error: Exception) { problem = error.message.orEmpty() }
            if (!attempt.isCurrent(baseUrl, state.conversation?.id, sourceRevokeToken)) return@work
            // A false/missing/unknown receipt never removes a local row. Only a
            // read of the same conversation may update the displayed sources.
            val fresh = try { conversation(client.get("/api/conversation")) } catch (error: Exception) { problem = error.message.orEmpty(); null }
            if (!attempt.isCurrent(baseUrl, state.conversation?.id, sourceRevokeToken)) return@work
            if (fresh?.id == sid) state = state.copy(conversation = fresh)
            when (attempt.outcome(receipt, fresh, baseUrl, state.conversation?.id, sourceRevokeToken)) {
                SourceRevokeOutcome.CONFIRMED -> tell("已移除这份资料；其他来源和你的原话仍保留。")
                SourceRevokeOutcome.UNRESOLVED -> tell("移除结果尚待核对；未根据这份回执确认移除。已尝试只读刷新当前资料列表，不会自动再次移除。" + if (problem.isNotBlank()) " $problem" else "")
                SourceRevokeOutcome.OBSOLETE -> Unit
            }
        } finally { if (sourceRevokeToken == attempt.token) sourceRevokeToken = null }
    }
    fun selectedFiles(files: List<SelectedText>) {
        if (files.map { it.name }.distinct().size != files.size) { tell("文件重名，请分开选择，便于区分来源。"); return }
        state = state.copy(files = files, filesUncertain = false)
    }
    fun dismissFiles() { state = state.copy(files = emptyList(), filesUncertain = false) }
    fun attachFiles() = work {
        val sid = state.conversation?.id ?: return@work
        require(state.pending == null) { "先核对这次聊天，再接入资料。" }
        if (state.filesUncertain) return@work
        val files = JSONArray(state.files.map { json("name" to it.name, "text" to it.text) })
        try { val result = api.post("/api/local-files/confirm", json("session_id" to sid, "files" to files)); require(conversation(result).id == sid); state = state.copy(conversation = conversation(result), files = emptyList()); reload(); tell("资料已接入当前对话。") }
        catch (error: Exception) { state = state.copy(filesUncertain = true); tell("接入结果未确认，请先刷新已接入资料核对，再决定是否重新选择。${error.message.orEmpty()}") }
    }
    fun previewSource(id: String, target: String = "") = work {
        require(!pairedMode) { "手机配对连接不运行电脑 CLI 或系统读取；请在电脑接入资料。" }
        require(state.pending == null) { "先核对这次聊天，再接入资料。" }
        val descriptor = state.descriptors.find { it.str("id") == id } ?: error("来源目录已变化，请刷新。")
        require(SourcePolicy.mayPreview(id, descriptor.str("status"), target)) { "此来源尚不具备只读条件；未发起授权或读取。" }
        val request = SourcePolicy.preview(id, target)
        val result = api.post(request.path, request.body)
        require(result.optBoolean("ok", true)) { result.str("error", "未能读取这份资料。") + " " + result.str("hint") }
        require(sourceReview(result, id).canAttach) { "没有可核对的真实内容；不会接入空资料。" }
        state = state.copy(sourcePreview = SourcePreview(id, result, target))
    }
    fun dismissSource() { state = state.copy(sourcePreview = null) }
    fun attachSource() = work {
        val preview = state.sourcePreview ?: return@work
        if (preview.uncertain) return@work
        require(state.pending == null) { "先核对这次聊天，再接入资料。" }
        val review = sourceReview(preview.result, preview.sourceId)
        require(review.canAttach) { "没有可核对的资料内容，请关闭后重新读取预览。" }
        val sid = state.conversation?.id ?: return@work
        val request = SourcePolicy.attach(preview.sourceId, preview.url, review.previewId, sid)
        try { val result = conversation(api.post(request.path, request.body)); require(result.id == sid); state = state.copy(conversation = result, sourcePreview = null); reload() }
        catch (error: Exception) { state = state.copy(sourcePreview = preview.copy(uncertain = true)); tell("接入结果未确认，请刷新已接入资料核对。${error.message.orEmpty()}") }
    }
    fun newAction(kind: String) { if (pairedMode) { tell("手机配对连接不执行电脑动作，请在电脑上核对。"); return }; state = state.copy(editor = ActionEditor(kind = kind)) }
    fun savedAction(action: SavedAction) {
        if (pairedMode) { tell("配对连接不执行电脑动作。"); return }
        if (action.sessionId != state.conversation?.id) return
        when (actionRoute(action.status)) {
            ActionRoute.CONFIRM_EXISTING -> state = state.copy(editor = ActionEditor(kind = action.kind, title = action.title, detail = action.detail, whenText = action.whenText, existingId = action.id, immutable = true))
            ActionRoute.CHECK_ONLY -> { refresh(); tell("只重新读取本机状态，不会再次执行系统写入。") }
            ActionRoute.INSPECT -> tell("已保存的完整内容与回执见任务详情。")
        }
    }
    fun editAction(editor: ActionEditor) { if (!state.busy && state.editor?.token == editor.token && !editor.immutable) state = state.copy(editor = editor) }
    fun closeAction() { val pendingCommit = state.editor?.committing == true; state = state.copy(editor = null); if (pendingCommit) tell("保存请求已发出，关闭窗口不代表取消保存。请到任务中核对。") }
    fun commitAction() = work {
        require(!pairedMode) { "配对连接不执行电脑动作。" }
        val original = state.editor ?: return@work
        val sid = state.conversation?.id ?: return@work
        if (original.uncertain) return@work
        require(original.title.isNotBlank() && original.title.length <= 200) { "填写 1–200 字标题。" }
        require(original.detail.length <= 2000 && (original.kind != "message" || original.detail.isNotBlank())) { "填写有效正文（最多 2000 字）。" }
        require(original.kind != "calendar" || original.existingId != null || original.whenText.isNotBlank()) { "填写日期时间，例如 2026-10-30T10:00。" }
        var current = original
        try {
            val id = original.existingId ?: api.post("/api/action", json("session_id" to sid, "kind" to original.kind, "title" to original.title, "detail" to original.detail, "when" to original.whenText)).getString("id")
            if (state.editor?.token != original.token) { reload(); return@work }
            current = original.copy(existingId = id)
            state = state.copy(editor = current)
            if (original.existingId != null) {
                val latest = savedActions(api.get("/api/actions?session_id=${encoded(sid)}")).find { it.id == id && it.sessionId == sid }
                require(latest?.status == "previewed") { "此记录已处理或待核对，未再次保存。" }
            }
            if (state.editor?.token != original.token) return@work
            state = state.copy(editor = current.copy(committing = true))
            val result = api.post("/api/action/${encoded(id)}/commit", json("real" to false))
            require(result.str("status") == "committed") { "结果待核对，请在任务中刷新状态。" }
            if (state.editor?.token == original.token) state = state.copy(editor = null)
            reload(); tell(if (original.kind == "message") "草稿已保存在本机，未发送。" else "已保存在本机，未写入系统。")
        } catch (error: Exception) {
            if (state.editor?.token == original.token) state = state.copy(editor = current.copy(uncertain = true))
            tell("保存结果未确认，请刷新任务核对，暂勿重复保存。${error.message.orEmpty()}")
        }
    }
}
