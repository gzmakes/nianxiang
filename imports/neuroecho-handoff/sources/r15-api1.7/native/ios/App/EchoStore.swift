import SwiftUI

@MainActor final class EchoStore: ObservableObject {
    @Published var conversation: EchoConversation? {didSet {conversationRevision &+= 1;changeReadBarrier &+= 1}}
    @Published var actions: [EchoAction] = [] {didSet {changeReadBarrier &+= 1}}
    @Published var nextStep: EchoNextStep?
    @Published private(set) var capabilities: EchoCapabilities?
    @Published private(set) var capabilityReadFailed=false
    @Published private(set) var readingCapabilities=false
    private var capabilityReadAttempt: UUID?
    @Published private(set) var followups: [EchoFollowup] = [] {didSet {changeReadBarrier &+= 1}}
    @Published private(set) var pendingFollowup: EchoPendingFollowup?
    @Published private(set) var followupDraft: EchoPendingFollowup?
    @Published private(set) var followupNotice: String?
    @Published private(set) var followupForm: EchoFollowupFormDraft?
    @Published private(set) var boundary: EchoCompanionBoundary? {didSet {changeReadBarrier &+= 1}}
    @Published var draft = "" { didSet {if oldValue != draft {changeReadBarrier &+= 1}; if !suppressDraftPersistence {defaults.set(draft,forKey:draftKey)} } }
    @Published var memoryProposals = false { didSet { defaults.set(memoryProposals,forKey:"echo.native.memory-proposals") } }
    @Published private(set) var topics: [String:String] = [:]
    @Published var selectedTopic = "全部"
    @Published var jumpToMessageID: String?
    @Published var jumpRequestID = UUID()
    @Published var pending: EchoPendingTurn? {didSet {changeReadBarrier &+= 1}}
    @Published var busy = false {didSet {if oldValue != busy {changeReadBarrier &+= 1}}}
    @Published var retryAllowed = false
    @Published var canEndLocalWait = false
    @Published var error: String?
    @Published private(set) var quoteNeedsManualReview = false
    @Published private(set) var endpoint: String
    @Published private(set) var deviceProfile: EchoDeviceProfile?
    @Published private(set) var connectionNotice: String?
    @Published private(set) var connectionFailureCode: String?
    @Published private(set) var verifyingDevice=false
    @Published private(set) var deviceConnected=false
    @Published private(set) var savedDeviceProfiles: [EchoDeviceProfile] = []
    @Published private(set) var forgottenDeviceGenerations: Set<UUID> = []
    @Published private(set) var changeSyncStatus: EchoChangeSyncStatus = .idle
    @Published private(set) var remoteReadRevision=0
    @Published private(set) var remoteMoods: [EchoMood] = []
    private var changePoll=EchoChangePollState()
    private var changeReadBarrier=0
    private var editReadLeases=Set<UUID>()
    private var changeServiceInstanceID: String?
    private var changeMonitoringActive=false
    private var changeMonitoringTask: Task<Void,Never>?
    private var changeMonitoringID: UUID?
    var canDiscoverChanges: Bool {capabilities?.features["conversation_change_cursor"] == true && sessionID != nil && (!isRemote || deviceConnected)}
    var changesWaiting: Bool {changePoll.pending}
    var changeNoticeKind: EchoChangeNoticeKind {EchoChangeNoticeKind.resolve(status:changeSyncStatus,capabilitiesKnown:capabilities != nil,capabilityReadFailed:capabilityReadFailed,changesWaiting:changesWaiting)}
    var heldChangeCursor: String? {changePoll.cursor}
    private var safeForChangeRead: Bool {!busy && !verifyingDevice && pending == nil && pendingFollowup == nil && editReadLeases.isEmpty && draft.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty && conversation?.messages.contains(where:{$0.deliveryPending == true}) != true}
    private(set) var api: EchoAPI
    private var generation = UUID()
    private var followupSequence = 0
    private var boundarySequence = 0
    private var conversationRevision = 0
    private let defaults: UserDefaults
    private let credentialStore: EchoDeviceCredentialStore
    private let apiFactory: (String,EchoDeviceAuthorization?) throws -> EchoAPI
    private let automaticChangePolling: Bool
    private var suppressDraftPersistence=false
    private var connectionAttempt=UUID()
    var scopeIdentity: String {deviceProfile?.namespace ?? endpoint}
    var isRemote: Bool {api.isRemote}
    private var identitySuffix: String {deviceProfile.map {"."+Data($0.namespace.utf8).base64EncodedString()} ?? ""}
    private var pendingKey: String {"echo.native.pending-turn.v1"+identitySuffix}
    private var pendingFollowupKey: String {"echo.native.pending-followup.v1"+identitySuffix}
    private var followupDraftKey: String {"echo.native.followup-draft.v1"+identitySuffix}
    private var legacyFollowupDraftKey: String {"echo.native.followup-rejected-draft.v1"+identitySuffix}
    private var draftKey: String { "echo.native.draft.v1." + Data(scopeIdentity.utf8).base64EncodedString() }
    private var topicsKey: String { "echo.native.topics.v1." + Data(scopeIdentity.utf8).base64EncodedString() }
    private var followupFormKey: String {"echo.native.followup-form.v1." + Data(scopeIdentity.utf8).base64EncodedString()}
    init(defaults: UserDefaults = .standard,credentialStore: EchoDeviceCredentialStore? = nil,automaticChangePolling: Bool = true,apiFactory: @escaping (String,EchoDeviceAuthorization?) throws -> EchoAPI = {try EchoAPI(baseURL:$0,authorization:$1)}) {
        self.defaults = defaults
        self.credentialStore=credentialStore ?? EchoKeychainDeviceCredentialStore();self.apiFactory=apiFactory;self.automaticChangePolling=automaticChangePolling
        let saved = defaults.string(forKey: "echo.native.endpoint") ?? "http://127.0.0.1:18787"
        let client = (try? apiFactory(saved,nil)) ?? (try! EchoAPI(baseURL: "http://127.0.0.1:18787"))
        api = client; endpoint = client.baseURL.absoluteString
        if let data=defaults.data(forKey:"echo.native.device-profile.v1"),let profile=try? JSONDecoder().decode(EchoDeviceProfile.self,from:data),profile.origin == endpoint {deviceProfile=profile;connectionNotice="点「恢复设备连接」后才读取本应用保存的设备凭据。"}
        if let data=defaults.data(forKey:"echo.native.device-profiles.v1"),let profiles=try? JSONDecoder().decode([EchoDeviceProfile].self,from:data) {savedDeviceProfiles=profiles}
        if let profile=deviceProfile,!savedDeviceProfiles.contains(profile) {savedDeviceProfiles.append(profile)}
        if let data=defaults.data(forKey:"echo.native.device-forgotten.v1"),let ids=try? JSONDecoder().decode([UUID].self,from:data) {forgottenDeviceGenerations=Set(ids)}
        memoryProposals = defaults.bool(forKey:"echo.native.memory-proposals")
        if !isRemote || deviceProfile != nil {loadScopedLocalState()}
    }
    private func loadScopedLocalState() {
        suppressDraftPersistence=true;defer {suppressDraftPersistence=false}
        draft=defaults.string(forKey:draftKey) ?? ""
        pending=nil;pendingFollowup=nil;followupDraft=nil;followupForm=nil
        topics = (defaults.dictionary(forKey:topicsKey) as? [String:String] ?? [:]).filter { EchoWorkspace.normalizedTopic($0.value) != nil }
        if let data = defaults.data(forKey: pendingKey), let value = try? JSONDecoder().decode(EchoPendingTurn.self, from: data), value.origin == scopeIdentity { pending = value }
        if let data = defaults.data(forKey:pendingFollowupKey), let value = try? JSONDecoder().decode(EchoPendingFollowup.self,from:data), value.origin == scopeIdentity { pendingFollowup = value }
        if let data = (defaults.data(forKey:followupDraftKey) ?? defaults.data(forKey:legacyFollowupDraftKey)), let value = try? JSONDecoder().decode(EchoPendingFollowup.self,from:data), value.origin == scopeIdentity { followupDraft = value }
        if let data=defaults.data(forKey:followupFormKey), let value=try? JSONDecoder().decode(EchoFollowupFormDraft.self,from:data), value.origin == scopeIdentity {followupForm=value}
    }
    var sessionID: String? { conversation?.session.id }
    var sources: [EchoSource] { conversation?.context?.sources ?? [] }
    var topicLabels: [String] { EchoWorkspace.topicLabels(assignments:topics) }
    var visibleMessages: [EchoMessage] { (conversation?.messages ?? []).filter { selectedTopic == "全部" || EchoWorkspace.topic(for:$0.id,assignments:topics) == selectedTopic } }
    func setTopic(_ label: String, for messageID: String) {
        guard let label = EchoWorkspace.normalizedTopic(label), conversation?.messages.contains(where:{$0.id == messageID}) == true else { return }
        topics[messageID] = label; defaults.set(topics,forKey:topicsKey); selectedTopic = label
    }
    func focusMessage(_ id: String) { selectedTopic = "全部"; jumpToMessageID = id; jumpRequestID = UUID() }
    func connect(to address: String? = nil) async {
        guard !busy,!verifyingDevice else { return }
        guard address.map({(try? EchoAPI.validatedBaseURL($0))?.scheme != "https"}) ?? !isRemote else {connectionNotice="HTTPS 服务请使用设备连接；没有匿名读取或重新提交。";return}
        if let address {
            guard pending == nil, pendingFollowup == nil, followupDraft == nil else { error = "请先核对原服务的聊天、跟进保存状态和待修改草稿，再更改地址。"; return }
            do {
                let replacement=try apiFactory(address,nil);api.invalidateDeviceAuthorization();api = replacement; deviceProfile=nil;deviceConnected=false;endpoint = api.baseURL.absoluteString; defaults.set(endpoint, forKey: "echo.native.endpoint");defaults.removeObject(forKey:"echo.native.device-profile.v1")
                draft = defaults.string(forKey:draftKey) ?? ""
                topics = (defaults.dictionary(forKey:topicsKey) as? [String:String] ?? [:]).filter { EchoWorkspace.normalizedTopic($0.value) != nil }
                selectedTopic = "全部"; jumpToMessageID = nil
                followupDraft = nil
                followupForm=nil
                if let data=defaults.data(forKey:followupFormKey), let value=try? JSONDecoder().decode(EchoFollowupFormDraft.self,from:data), value.origin == scopeIdentity {followupForm=value}
                if let data = (defaults.data(forKey:followupDraftKey) ?? defaults.data(forKey:legacyFollowupDraftKey)), let value = try? JSONDecoder().decode(EchoPendingFollowup.self,from:data), value.origin == scopeIdentity {followupDraft = value}
            }
            catch { self.error = error.localizedDescription; return }
            resetChangeReadIdentity()
            capabilityReadAttempt=nil;readingCapabilities=false;capabilityReadFailed=false
            conversation = nil; actions = []; nextStep = nil; capabilities = nil; followups = []; followupNotice = nil; boundary=nil; generation = UUID()
        }
        let epoch = generation, client = api
        busy = true; error = nil
        defer { if epoch == generation { busy = false } }
        do {
            let snapshot = try await client.conversation()
            guard epoch == generation else { return }
            conversation = snapshot
            if let pending, pending.sessionID != snapshot.session.id { self.error = "服务的主对话发生变化，原发送状态仍需在原服务核对。" }
            if !client.isRemote {
                async let taskList = client.actions(sessionID: snapshot.session.id)
                async let next = client.nextStep(sessionID: snapshot.session.id)
                let (tasks, step) = try await (taskList, next)
                guard epoch == generation else { return }; actions = tasks; nextStep = step
            }
            _ = await rereadCapabilities()
        } catch { if epoch == generation { self.error = "暂时没能连上回响：\(error.localizedDescription)" } }
    }
    /// Explicit GET-only recovery. An old response cannot change a newly paired
    /// identity, even when both devices use the same canonical conversation.
    @discardableResult func rereadCapabilities() async -> Bool {
        guard !readingCapabilities,sessionID != nil,!isRemote || deviceConnected else {return false}
        let epoch=generation,client=api,sid=sessionID,scope=scopeIdentity,attempt=UUID()
        capabilityReadAttempt=attempt;readingCapabilities=true
        defer {if epoch == generation,capabilityReadAttempt == attempt {readingCapabilities=false;capabilityReadAttempt=nil}}
        do {
            let metadata=try await client.capabilities()
            guard epoch == generation,scope == scopeIdentity,sid == sessionID,capabilityReadAttempt == attempt,!Task.isCancelled else {return false}
            capabilities=metadata;capabilityReadFailed=false
            if !canDiscoverChanges {changeSyncStatus = .unsupported}
            else if changeSyncStatus == .unsupported {changeSyncStatus = .idle}
            setChangeMonitoringActive(changeMonitoringActive)
            return true
        } catch {
            guard epoch == generation,scope == scopeIdentity,sid == sessionID,capabilityReadAttempt == attempt,!Task.isCancelled else {return false}
            capabilityReadFailed=true
            if capabilities != nil {changeSyncStatus = .offline}
            return false
        }
    }
    /// Unlike lifecycle refresh, this also lets the person retry an unread
    /// capability list. It never removes editor leases or resubmits mutations.
    func checkUpdatesExplicitly() async {
        guard changeMonitoringActive,!busy,!verifyingDevice else {return}
        let epoch=generation
        guard await rereadCapabilities(),epoch == generation,changeMonitoringActive else {return}
        if canDiscoverChanges {await checkForChanges();return}
        // Old services have no metadata-only protocol. Keep their content read
        // deferred while an editor, draft or uncertain request is active.
        guard safeForChangeRead else {return}
        await refreshFromForeground()
    }
    /// Foreground reconciliation only reads state. Never resends a pending turn.
    func refreshFromForeground() async {
        if canDiscoverChanges {await checkForChanges();return}
        guard !busy else { return }
        guard !isRemote || deviceConnected else {return}
        // Without a capability receipt there is no evidence of an old service.
        // The explicit check button can retry metadata without changing drafts.
        guard editReadLeases.isEmpty,conversation == nil || capabilities != nil else {return}
        let epoch=generation
        if conversation == nil { await connect() }
        else {
            busy = true
            do {try await refresh()} catch {if epoch == generation {self.error = "暂时未能更新，已有内容保留：\(error.localizedDescription)"}}
            guard epoch == generation else {return}
            busy = false
        }
        guard epoch == generation else {return}
        if pending != nil { await recoverPending() }
        guard epoch == generation else {return}
        await refreshFollowups()
        await refreshBoundary()
    }
    func refresh() async throws {
        let epoch = generation, client = api
        let snapshot = try await client.conversation()
        guard epoch == generation else { return }
        if let old = sessionID, old != snapshot.session.id { throw EchoAPIError.message("主对话发生变化，已停止更新，请核对服务数据。") }
        if client.isRemote {
            guard deviceConnected,deviceProfile?.conversationID == snapshot.session.id else {throw EchoAPIError.message("设备连接与主对话不匹配，请重新核对。")}
            conversation=snapshot;actions=[];nextStep=nil;return
        }
        async let tasks = client.actions(sessionID: snapshot.session.id)
        async let next = client.nextStep(sessionID: snapshot.session.id)
        let (records, step) = try await (tasks, next)
        guard epoch == generation else { return }
        conversation = snapshot; actions = records; nextStep = step
    }
    func accept(_ snapshot: EchoConversation, expectedID: String) throws {
        guard snapshot.session.id == expectedID, sessionID == expectedID else { throw EchoAPIError.message("返回的对话不匹配，结果仍需核对。") }
        conversation = snapshot
    }
    /// Read server-controlled delivery progress only. A concurrent user action,
    /// endpoint change or newer snapshot makes this response stale.
    func refreshDelivery() async {
        guard !busy, let sid = sessionID,
              conversation?.messages.contains(where: { $0.deliveryPending == true }) == true else { return }
        let epoch = generation, revision = conversationRevision, client = api
        do {
            let snapshot = try await client.conversation()
            guard !Task.isCancelled, !busy, epoch == generation, revision == conversationRevision,
                  sessionID == sid, snapshot.session.id == sid else { return }
            conversation = snapshot
        } catch {
            if !Task.isCancelled, !busy, epoch == generation, revision == conversationRevision, sessionID == sid { self.error = "暂时没能更新正在发送的内容，已有文字仍保留。" }
        }
    }
    /// Stops only the displayed assistant message. This never cancels a model
    /// turn, and a POST acknowledgement alone cannot replace the GET check.
    func stopDelivery(messageID: String) async {
        guard !busy, pending == nil, let sid=sessionID,
              capabilities?.features["chat_delivery_targeted_stop"] == true,
              let current=conversation?.messages.last(where:{$0.role == "assistant"}), current.id == messageID, current.deliveryPending == true else {return}
        let epoch=generation, revision=conversationRevision, client=api
        busy=true; defer { if epoch == generation {busy=false} }
        var acknowledgement: EchoDeliveryStop?
        do { acknowledgement=try await client.stopDelivery(sessionID:sid,messageID:messageID) }
        catch { if epoch == generation {self.error="停止呈现的结果尚未确认，正在重新读取对话。"} }
        do {
            let snapshot=try await client.conversation()
            guard epoch == generation, revision == conversationRevision, sessionID == sid, snapshot.session.id == sid else {return}
            conversation=snapshot
            let displayed=snapshot.messages.last(where:{$0.role == "assistant"})
            if acknowledgement?.confirms(messageID) == true, displayed?.id == messageID, displayed?.deliveryPending == false {
                error="已停止展开这条回复；已显示的文字保留。这不等于取消模型请求。"
            } else {error="尚未确认停止这条回复，已重新读取当前对话；没有再次发送停止请求。"}
        } catch { if epoch == generation {self.error="停止结果仍需核对，对话暂时读不到；不会自动重发停止请求。"} }
    }
    private func persistPending() {
        if let pending, let data = try? JSONEncoder().encode(pending) { defaults.set(data, forKey: pendingKey) }
        else { defaults.removeObject(forKey: pendingKey) }
    }
    func send() async {
        guard let sid = sessionID, pending == nil, !busy else { return }
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, text.unicodeScalars.count <= 4_000 else { error = "请写下 1–4000 字，再发送。"; return }
        let turn = EchoPendingTurn(sessionID: sid, text: text, origin: scopeIdentity,memoryProposals:memoryProposals,timeZone:capabilities?.features["companion_boundaries"] == true ? TimeZone.current.identifier : nil)
        pending = turn; persistPending(); draft = ""; retryAllowed = false; canEndLocalWait = false
        await submitPending(turn)
    }
    private func submitPending(_ turn: EchoPendingTurn) async {
        let epoch=generation,client=api
        busy = true; error = nil
        do {let result=try await client.send(turn);guard epoch == generation else {return};try await settle(result,turn:turn)}
        catch {
            guard epoch == generation,pending?.requestID == turn.requestID else {return}
            if (error as? EchoAPIError)?.statusCode == 429 {
                draft = draft.isEmpty ? turn.text : turn.text + "\n" + draft; pending = nil; persistPending()
                canEndLocalWait = false
                self.error = error.localizedDescription
            } else { self.error = "发送结果未确认。文字仍保存在本机，请核对状态；不会自动重发。" }
        }
        if epoch == generation {busy = false}
    }
    func retryPending() async {
        guard let turn = pending, retryAllowed, !turn.cancelWanted, !busy, turn.origin == scopeIdentity, sessionID == turn.sessionID else { return }
        retryAllowed = false
        await submitPending(turn)
    }
    private func settle(_ result: EchoChatSubmission, turn: EchoPendingTurn) async throws {
        guard pending?.requestID == turn.requestID,turn.origin == scopeIdentity,sessionID == turn.sessionID else {return}
        let epoch=generation,client=api
        switch result {
        case .pending(let record):
            retryAllowed = false
            canEndLocalWait = record.permitsEndingLocalWait
            if record.status == "unknown" { error = "服务端无法确认这次回复是否完成。请核对聊天记录；不会重新执行。" }
            else { error = "服务端仍在处理。可以继续输入，核对后再发送。" }
        case .completed:
            var notice: String?
            if pending?.cancelWanted == true {
                let stopped = try await client.cancel(turn)
                guard epoch == generation else {return}
                canEndLocalWait = stopped.permitsEndingLocalWait
                guard stopped.result != nil else { error = stopped.cancellationNotice; return }
                notice = stopped.cancellationNotice
            }
            try await refresh()
            guard epoch == generation else {return}
            pending = nil; persistPending(); retryAllowed = false; canEndLocalWait = false; error = notice
        }
    }
    func recoverPending() async {
        guard let turn = pending, !busy, turn.origin == scopeIdentity else { return }
        let epoch=generation,client=api
        busy = true
        defer {if epoch == generation {busy = false}}
        do {
            let record = try await client.recover(turn)
            guard epoch == generation,pending?.requestID == turn.requestID else {return}
            if record.errorCode == "budget_exceeded" {
                draft = draft.isEmpty ? turn.text : turn.text + "\n" + draft; pending = nil; persistPending()
                canEndLocalWait = false
                error = "近60分钟的聊天额度已用完。请稍后再试，文字仍保留。"; return
            }
            if let result = record.result { try await settle(.completed(result), turn: turn) }
            else { try await settle(.pending(record), turn: turn); try await refresh() }
        } catch {
            guard epoch == generation else {return}
            retryAllowed = (error as? EchoAPIError)?.statusCode == 404 && !turn.cancelWanted
            self.error = "尚未核对成功：\(error.localizedDescription) 原发送标识和文字仍保留。"
        }
    }
    func cancelPending() async {
        guard var turn = pending, turn.origin == scopeIdentity else { return }
        let epoch=generation,client=api
        turn.cancelWanted = true; pending = turn; persistPending(); retryAllowed = false
        do {
            let record = try await client.cancel(turn)
            guard epoch == generation,pending?.requestID == turn.requestID else { return }
            canEndLocalWait = record.permitsEndingLocalWait
            if record.result != nil {try await refresh();guard epoch == generation else {return};pending = nil; persistPending(); canEndLocalWait = false; error = record.cancellationNotice }
            else { error = record.cancellationNotice }
        } catch {if epoch == generation {self.error = "停止结果尚未确认，请核对状态；已发出的请求可能继续完成。"}}
    }
    func endLocalWaitAfterReview() async {
        guard let turn = pending, canEndLocalWait, !busy, turn.origin == scopeIdentity, sessionID == turn.sessionID else { return }
        let client = api,origin = scopeIdentity,epoch=generation
        busy = true
        defer {if epoch == generation {busy = false}}
        do {
            let snapshot = try await client.reviewBeforeEndingLocalWait(turn)
            guard epoch == generation,pending?.requestID == turn.requestID,scopeIdentity == origin, sessionID == turn.sessionID else { return }
            try accept(snapshot, expectedID:turn.sessionID)
            draft = draft.isEmpty ? turn.text : turn.text + "\n" + draft
            pending = nil; persistPending(); retryAllowed = false; canEndLocalWait = false
            error = "已结束本机等待，原请求结果仍未确认，并不代表服务端已取消。原话已放回输入框，请先核对记录再决定；没有重新发送。"
        } catch {if epoch == generation {self.error = "尚不能结束本机等待：\(error.localizedDescription) 原请求标识和文字仍保留。"}}
    }
    func carryToChat(_ text: String) { draft = draft.isEmpty ? text : draft + "\n" + text }
    func refreshBoundary() async {
        guard let sid=sessionID, capabilities?.features["companion_boundaries"] == true else {return}
        let client=api, epoch=generation
        boundarySequence += 1; let sequence=boundarySequence
        do {let value=try await client.boundary(sessionID:sid); guard epoch == generation, sessionID == sid, sequence == boundarySequence else {return}; boundary=value}
        catch {if epoch == generation, sequence == boundarySequence {self.error="主动联系边界暂未更新，请在设置中只读核对。"}}
    }
    func saveFollowupForm(_ value: EchoFollowupFormDraft?) {
        guard value == nil || (pendingFollowup == nil && value?.origin == scopeIdentity && value?.sessionID == sessionID) else {return}
        followupForm=value
        if let value, let data=try? JSONEncoder().encode(value) {defaults.set(data,forKey:followupFormKey)}
        else {defaults.removeObject(forKey:followupFormKey)}
        // A definitively rejected draft is editable, unlike an uncertain turn.
        // Once edited, the newer form must win when the sheet is reopened.
        if value != nil, followupDraft != nil {followupDraft=nil;persistFollowupDraft()}
    }
    func refreshFollowups() async {
        guard let sid = sessionID else {return}
        let client = api, epoch = generation
        followupSequence += 1; let sequence = followupSequence
        do {
            let records = try await client.followups(sessionID:sid)
            guard epoch == generation, sessionID == sid, sequence == followupSequence else {return}
            followups = records.filter {$0.sessionId == sid}
            if let pendingFollowup, let acknowledged = followups.first(where:{$0.matches(pendingFollowup) && $0.hasKnownStatus}) {
                self.pendingFollowup = nil; persistFollowup()
                followupNotice = "已核对保存记录：\(acknowledged.statusLabel)。打开回响时显示，不会发系统通知。"
            } else if let pendingFollowup, followups.contains(where:{$0.requestId == pendingFollowup.requestID}) {
                followupNotice = "同一请求的内容或时间不匹配，请保留原请求并核对服务记录。"
            }
        } catch { if epoch == generation, sequence == followupSequence {followupNotice = "跟进暂时读不到：\(error.localizedDescription) 已有内容保留。"} }
    }
    private func persistFollowup() {
        if let pendingFollowup, let data = try? JSONEncoder().encode(pendingFollowup) {defaults.set(data,forKey:pendingFollowupKey)}
        else {defaults.removeObject(forKey:pendingFollowupKey)}
    }
    private func persistFollowupDraft() {
        if let followupDraft, let data = try? JSONEncoder().encode(followupDraft) {defaults.set(data,forKey:followupDraftKey)}
        else {defaults.removeObject(forKey:followupDraftKey)}
        defaults.removeObject(forKey:legacyFollowupDraftKey)
    }
    @discardableResult func saveFollowup(content: String, date: Date, repeatRule: String = "once", timeZone: String = TimeZone.current.identifier, quietStart: String? = nil, quietEnd: String? = nil, allowContact: Bool = false, contactWindowMinutes: Int = 30, contactTopic: String? = nil) async -> Bool {
        guard let sid = sessionID, pendingFollowup == nil, !busy else {return false}
        guard repeatRule == "once" || capabilities?.features["in_app_recurring_followups"] == true else {followupNotice="当前服务未声明周期跟进能力，草稿保留。";return false}
        do {
            let bounded=capabilities?.features["bounded_followup_contact"] == true
            guard bounded || !allowContact else {followupNotice="当前服务未声明联系窗口能力，不会保存主动联系同意。";return false}
            let topic=contactTopic?.trimmingCharacters(in:.whitespacesAndNewlines)
            pendingFollowup = try EchoPendingFollowup(sessionID:sid,content:content,date:date,origin:scopeIdentity,repeatRule:repeatRule,timeZone:timeZone,quietStart:quietStart,quietEnd:quietEnd,allowContact:bounded ? allowContact : nil,contactWindowMinutes:bounded ? contactWindowMinutes : nil,contactTopic:bounded ? (topic?.isEmpty == false ? topic : content) : nil)
            persistFollowup(); followupDraft = nil; persistFollowupDraft()
            saveFollowupForm(nil)
            await retryFollowup(initialAttempt:true)
            return pendingFollowup == nil && followupDraft == nil
        }
        catch {followupNotice = error.localizedDescription;return false}
    }
    func retryFollowup(initialAttempt: Bool = false) async {
        guard let request = pendingFollowup, !busy, request.origin == scopeIdentity, request.sessionID == sessionID else {return}
        followupSequence += 1
        let epoch=generation,client=api
        busy = true;defer {if epoch == generation {busy = false}}
        do {
            let result = try await client.createFollowup(request)
            guard epoch == generation,pendingFollowup?.requestID == request.requestID,sessionID == request.sessionID else {return}
            pendingFollowup = nil; persistFollowup()
            followupNotice = "已保存\(result.repeatRule == "daily" ? "每日" : "一次")跟进：\(result.statusLabel)。当前 iOS 只提供任务查看，不自动轻问或发系统通知。"
            await refreshFollowups()
        } catch {
            guard epoch == generation,pendingFollowup?.requestID == request.requestID else {return}
            let status = (error as? EchoAPIError)?.statusCode
            if initialAttempt && (status == 400 || status == 422) {
                // The local API validates before inserting and serializes each
                // request key. Only a first, explicitly rejected attempt is
                // safe to release: a prior timeout may still commit later.
                followupDraft = request; persistFollowupDraft()
                pendingFollowup = nil; persistFollowup()
                followupNotice = "这次未保存：\(error.localizedDescription) 内容已保留，可以修改时间后重新确认。"
            } else {
                followupNotice = "保存结果尚未确认：\(error.localizedDescription) 请刷新列表或显式使用同一请求重试，不要重复新建。"
            }
        }
    }
    func changeFollowup(_ item: EchoFollowup, status: String) async {
        guard !busy, item.sessionId == sessionID, item.status == "pending", item.supportsNativeTransitions else {return}
        followupSequence += 1
        let epoch=generation,client=api
        busy = true;defer {if epoch == generation {busy = false}}
        do {_ = try await client.changeFollowup(item,status:status);guard epoch == generation else {return};followupNotice = status == "done" ? (item.repeatRule == "daily" ? "已完成本次，下次时间已更新。" : "已标记完成。") : status == "paused" ? "已暂停这条跟进。" : status == "resumed" ? "已恢复这条跟进；不会补发错过的联系。" : "已取消这条跟进。" }
        catch {guard epoch == generation else {return};followupNotice = "更新结果需核对：\(error.localizedDescription) 不会自动重试。"}
        guard epoch == generation else {return}
        await refreshFollowups()
    }
    func rememberQuote(_ message: EchoMessage) async {
        quoteNeedsManualReview = false
        guard let sid = sessionID, message.role == "user", !busy, pending == nil,
              conversation?.messages.contains(where:{$0.id == message.id}) == true else { return }
        let epoch=generation,client=api
        busy = true
        defer {if epoch == generation {busy = false}}
        do {
            let memory = try await client.saveQuote(sessionID:sid,messageID:message.id)
            guard epoch == generation else {return}
            guard memory.sourceMessageId == message.id,sessionID == sid else { throw EchoAPIError.message("原话来源未匹配，保存结果需要核对。") }
            try await refresh();if epoch == generation {error = nil}
        } catch {
            guard epoch == generation else {return}
            quoteNeedsManualReview = (error as? EchoAPIError)?.statusCode == 409
            self.error = quoteNeedsManualReview ? "这句尚未直接选存：\(error.localizedDescription) 可以整理为待确认记忆，再由你确认。" : "记忆保存结果需核对：\(error.localizedDescription) 请在记忆中查看，不会自动重试。"
        }
    }
    // Device credentials are read only from explicit Connect / Restore UI actions.
    private func makeDeviceClient(_ address: String,authorization: EchoDeviceAuthorization) throws -> EchoAPI {
        let client=try apiFactory(address,authorization)
        client.setAuthenticationFailureHandler {[weak self] failure in Task {@MainActor in self?.deviceAuthenticationFailed(failure)}}
        return client
    }
    private func clearPrivateMemory() {
        resetChangeReadIdentity()
        capabilityReadAttempt=nil;readingCapabilities=false;capabilityReadFailed=false
        generation=UUID();error=nil;quoteNeedsManualReview=false;conversation=nil;actions=[];nextStep=nil;capabilities=nil;followups=[];boundary=nil;followupNotice=nil
        suppressDraftPersistence=true;draft="";suppressDraftPersistence=false
        pending=nil;pendingFollowup=nil;followupDraft=nil;followupForm=nil;topics=[:];selectedTopic="全部";jumpToMessageID=nil
        retryAllowed=false;canEndLocalWait=false;busy=false
    }
    private func saveDeviceMetadata(_ profile: EchoDeviceProfile) throws {
        var profiles=savedDeviceProfiles;profiles.removeAll {$0.credentialGeneration == profile.credentialGeneration};profiles.append(profile)
        let encoded=try JSONEncoder().encode(profile),history=try JSONEncoder().encode(profiles),oldHistory=defaults.data(forKey:"echo.native.device-profiles.v1"),old=defaults.data(forKey:"echo.native.device-profile.v1"),oldEndpoint=defaults.string(forKey:"echo.native.endpoint")
        defaults.set(encoded,forKey:"echo.native.device-profile.v1");defaults.set(profile.origin,forKey:"echo.native.endpoint")
        defaults.set(history,forKey:"echo.native.device-profiles.v1")
        guard defaults.data(forKey:"echo.native.device-profile.v1") == encoded,defaults.string(forKey:"echo.native.endpoint") == profile.origin,defaults.data(forKey:"echo.native.device-profiles.v1") == history else {
            if let old {defaults.set(old,forKey:"echo.native.device-profile.v1")} else {defaults.removeObject(forKey:"echo.native.device-profile.v1")}
            if let oldEndpoint {defaults.set(oldEndpoint,forKey:"echo.native.endpoint")} else {defaults.removeObject(forKey:"echo.native.endpoint")}
            if let oldHistory {defaults.set(oldHistory,forKey:"echo.native.device-profiles.v1")} else {defaults.removeObject(forKey:"echo.native.device-profiles.v1")}
            throw EchoCredentialStoreError.unavailable
        }
        savedDeviceProfiles=profiles
    }
    private func activateDevice(_ profile: EchoDeviceProfile,client: EchoAPI,snapshot: EchoConversation,capabilities: EchoCapabilities?) {
        api.invalidateDeviceAuthorization();clearPrivateMemory();deviceProfile=profile;api=client;endpoint=profile.origin;deviceConnected=true
        loadScopedLocalState();conversation=snapshot;self.capabilities=capabilities
        capabilityReadFailed=capabilities == nil
        connectionFailureCode=nil;connectionNotice="已连接到你的回响。只使用这份设备许可；电脑上的 CLI、系统动作与模型设置不向手机开放。";error=nil
    }
    @discardableResult func connectDevice(address: String,token: String) async -> Bool {
        guard !busy,!verifyingDevice else {return false}
        guard pending == nil,pendingFollowup == nil,followupDraft == nil else {connectionNotice="原连接有未决请求。请先核对；也可明确退出本机连接并保留原身份的草稿，不会移给新设备。";return false}
        let attempt=UUID();connectionAttempt=attempt;verifyingDevice=true;connectionFailureCode=nil;connectionNotice="正在核对设备连接，原连接暂时保留。"
        defer {if connectionAttempt == attempt {verifyingDevice=false}}
        do {
            let url=try EchoAPI.validatedBaseURL(address)
            guard url.scheme == "https" else {throw EchoAPIError.message("设备连接仅支持 HTTPS；本机 HTTP 开发连接另有入口。")}
            let clean=token.trimmingCharacters(in:.whitespacesAndNewlines)
            let verifier=try makeDeviceClient(url.absoluteString,authorization:EchoDeviceAuthorization(token:clean))
            let receipt=try await verifier.pairedDevice()
            guard connectionAttempt == attempt,!Task.isCancelled else {return false}
            let profile=EchoDeviceProfile(origin:verifier.baseURL.absoluteString,receipt:receipt)
            let client=try makeDeviceClient(profile.origin,authorization:EchoDeviceAuthorization(token:clean,profile:profile))
            let snapshot=try await client.conversation()
            guard snapshot.session.id == profile.conversationID else {throw EchoAPIError.message("验证的设备与返回的对话不一致，没有切换连接。")}
            guard connectionAttempt == attempt,!Task.isCancelled else {return false}
            let metadata=try? await client.capabilities()
            guard connectionAttempt == attempt,!Task.isCancelled else {return false}
            try client.assertDeviceAuthorizationUsable()
            try credentialStore.save(clean,for:profile)
            do {
                guard try credentialStore.read(for:profile) == clean else {throw EchoCredentialStoreError.unavailable}
                try saveDeviceMetadata(profile)
            } catch {try? credentialStore.remove(for:profile);throw error}
            activateDevice(profile,client:client,snapshot:snapshot,capabilities:metadata);return true
        } catch {
            if connectionAttempt == attempt {connectionNotice="连接没有启用，原连接与草稿保留。"+error.localizedDescription}
            return false
        }
    }
    @discardableResult func restoreDeviceConnection(_ selected: EchoDeviceProfile? = nil) async -> Bool {
        guard let profile=selected ?? deviceProfile,!busy,!verifyingDevice,savedDeviceProfiles.contains(profile),!forgottenDeviceGenerations.contains(profile.credentialGeneration) else {return false}
        let prior=deviceProfile
        let attempt=UUID();connectionAttempt=attempt;verifyingDevice=true
        defer {if connectionAttempt == attempt {verifyingDevice=false}}
        do {
            let token=try credentialStore.read(for:profile)
            let client=try makeDeviceClient(profile.origin,authorization:EchoDeviceAuthorization(token:token,profile:profile))
            let receipt=try await client.pairedDevice();guard profile.matches(receipt) else {throw EchoAPIError.message("原设备所属服务已变化，请重新连接；不会迁移原请求。")}
            let snapshot=try await client.conversation();guard snapshot.session.id == profile.conversationID else {throw EchoAPIError.message("返回的主对话不匹配，没有启用连接。")}
            guard connectionAttempt == attempt,!Task.isCancelled else {return false}
            let metadata=try? await client.capabilities()
            guard connectionAttempt == attempt,deviceProfile == prior,!Task.isCancelled else {return false}
            try client.assertDeviceAuthorizationUsable()
            try saveDeviceMetadata(profile)
            activateDevice(profile,client:client,snapshot:snapshot,capabilities:metadata);return true
        } catch {if connectionAttempt == attempt {connectionNotice=error.localizedDescription};return false}
    }
    func cancelDeviceVerification() {
        connectionAttempt=UUID();verifyingDevice=false
    }
    func disconnectDevice(forgetCredential: Bool) {
        guard let profile=deviceProfile else {return}
        connectionAttempt=UUID();verifyingDevice=false;connectionFailureCode=nil;api.invalidateDeviceAuthorization();deviceConnected=false
        var removed = !forgetCredential
        if forgetCredential {do {try credentialStore.remove(for:profile);rememberForgotten(profile);removed=true} catch {connectionNotice=error.localizedDescription}}
        clearPrivateMemory()
        if removed {
            connectionNotice=forgetCredential ? "已移除本机设备凭据。电脑端许可需在电脑上撤销；原身份的草稿与未决状态仍留本机，不会发送到新连接。" : "已退出本机连接；草稿与未决状态仍按原身份保留。不会取消服务端已经发出的操作。"
        }
    }
    private func deviceAuthenticationFailed(_ failure: EchoAuthenticationFailure) {
        guard deviceProfile == failure.profile else {
            // Only a known app-owned old account can be cleaned. Its late401
            // cannot clear the new profile, token, UI or request state.
            if failure.code == "paired_authentication_required",savedDeviceProfiles.contains(failure.profile) {do {try credentialStore.remove(for:failure.profile);rememberForgotten(failure.profile)} catch {}}
            return
        }
        connectionFailureCode=failure.code
        api.invalidateDeviceAuthorization();deviceConnected=false
        var cleanup=""
        if failure.code == "paired_authentication_required" {
            do {try credentialStore.remove(for:failure.profile);rememberForgotten(failure.profile)} catch {cleanup=" 本机凭据清理未完成，解锁后可再次移除。"}
        }
        clearPrivateMemory()
        connectionNotice=(failure.code == "service_instance_mismatch" ? "服务实例已变化；原连接已停用，原身份凭据与草稿仍保留供回原实例核对，不会移给新数据库。" : "设备连接已失效，请在电脑端检查许可后重新连接。")+cleanup
    }
    private func rememberForgotten(_ profile: EchoDeviceProfile) {
        forgottenDeviceGenerations.insert(profile.credentialGeneration)
        if let data=try? JSONEncoder().encode(Array(forgottenDeviceGenerations)) {defaults.set(data,forKey:"echo.native.device-forgotten.v1")}
    }
    func forgetSavedDeviceCredential(_ profile: EchoDeviceProfile) {
        guard savedDeviceProfiles.contains(profile) else {return}
        if deviceProfile == profile {disconnectDevice(forgetCredential:true);return}
        do {try credentialStore.remove(for:profile);rememberForgotten(profile);connectionNotice="已移除所选旧连接的本机令牌；当前连接不变。没有向电脑发送撤销，也没有迁移或删除它的草稿。"}
        catch {connectionNotice=error.localizedDescription}
    }
    /// Reads only this app's local draft keys for an already known profile.
    /// No vault/network access, activation, migration or request reconstruction.
    func localDraftArchive(for profile: EchoDeviceProfile) -> EchoLocalDraftArchive? {
        guard savedDeviceProfiles.contains(profile) || deviceProfile == profile else {return nil}
        return EchoLocalDraftArchive.read(defaults:defaults,profile:profile)
    }

    // R14: no cursor is persisted; new process/identity must baseline again.
    func protectChangeReads(_ id: UUID,active: Bool) {
        let changed = active ? editReadLeases.insert(id).inserted : editReadLeases.remove(id) != nil
        if changed {changeReadBarrier &+= 1}
    }
    func setChangeMonitoringActive(_ active: Bool) {
        changeMonitoringActive=active
        if !active {changeMonitoringTask?.cancel();changePoll.interrupt();return}
        guard canDiscoverChanges else {if capabilities != nil {changeSyncStatus = .unsupported};return}
        guard automaticChangePolling,changeMonitoringTask == nil else {return}
        let id=UUID();changeMonitoringID=id
        changeMonitoringTask=Task {[weak self] in
            guard let self else {return}
            defer {
                if self.changeMonitoringID == id {
                    self.changeMonitoringTask=nil;self.changeMonitoringID=nil
                    if self.changeMonitoringActive && self.canDiscoverChanges {self.setChangeMonitoringActive(true)}
                }
            }
            while !Task.isCancelled,self.changeMonitoringActive,self.canDiscoverChanges {
                await self.checkForChanges()
                do {try await Task.sleep(for:.seconds(self.changePoll.delaySeconds))} catch {break}
            }
        }
    }
    private func resetChangeReadIdentity() {
        changeMonitoringTask?.cancel();changePoll.bind(UUID().uuidString)
        changeServiceInstanceID=nil;remoteMoods=[];changeSyncStatus = .idle
    }
    /// Metadata first, then staged GETs, then one stability GET. Never a POST,
    /// automatic ledger replay, draft adoption or optimistic cursor advancement.
    func checkForChanges() async {
        guard changeMonitoringActive else {return}
        guard canDiscoverChanges,let sid=sessionID else {if capabilities != nil {changeSyncStatus = .unsupported};return}
        let client=api,epoch=generation,scope=scopeIdentity+"|"+sid
        guard let ticket=changePoll.begin(scope:scope) else {return}
        defer {changePoll.finish(ticket)}
        let barrier=changeReadBarrier
        if !changePoll.pending {changeSyncStatus = .checking}
        do {
            let metadata=try await client.conversationChanges(after:ticket.after)
            guard epoch == generation,changePoll.accepts(ticket),!Task.isCancelled else {return}
            guard metadata.conversationId == sid,changeServiceInstanceID.map({$0 == metadata.serviceInstanceId}) ?? true else {throw EchoAPIError.message("更新属于另一份服务身份，保留原内容，请重新核对连接。")}
            guard ticket.after != nil || metadata.resetRequired else {throw EchoAPIError.message("初次更新没有完整基线，未保存游标。")}
            // Even empty metadata cannot claim a baseline before its full read.
            if let after=ticket.after,!metadata.resetRequired,metadata.domains.isEmpty,metadata.cursor != after {throw EchoAPIError.message("空更新回执改变了游标，未推进未读内容。") }
            let needsRead=ticket.after == nil || metadata.resetRequired || !metadata.domains.isEmpty
            if !needsRead {
                if changePoll.commit(ticket,cursor:metadata.cursor) {changeSyncStatus = .idle}
                return
            }
            changePoll.discovered(ticket);changeSyncStatus = .pending
            guard Set(metadata.domains).isSubset(of:EchoConversationChanges.knownDomains) else {throw EchoAPIError.message("存在尚不支持的更新域，保留原游标和内容。请更新客户端后核对。")}
            guard safeForChangeRead,barrier == changeReadBarrier else {return}
            let snapshot=try await client.changeConversationSnapshot()
            guard snapshot.session.id == sid else {throw EchoAPIError.message("更新快照不是原主对话，未替换内容。")}
            guard epoch == generation,changePoll.accepts(ticket),!Task.isCancelled,safeForChangeRead,barrier == changeReadBarrier else {return}
            var newFollowups=followups,newBoundary=boundary,newMoods=remoteMoods,newActions=actions,newNext=nextStep
            if capabilities?.features["in_app_one_time_followups"] == true && (metadata.resetRequired || metadata.domains.contains("followups")) {newFollowups=try await client.followups(sessionID:sid)}
            guard epoch == generation,changePoll.accepts(ticket),!Task.isCancelled,safeForChangeRead,barrier == changeReadBarrier else {return}
            guard newFollowups.allSatisfy({$0.sessionId == sid && !$0.id.isEmpty}) else {throw EchoAPIError.message("跟进更新不属于原主对话，未采用更新。")}
            if capabilities?.features["companion_boundaries"] == true && (metadata.resetRequired || metadata.domains.contains("boundary")) {newBoundary=try await client.boundary(sessionID:sid)}
            guard epoch == generation,changePoll.accepts(ticket),!Task.isCancelled,safeForChangeRead,barrier == changeReadBarrier else {return}
            if capabilities?.features["daily_mood_entries"] == true && (metadata.resetRequired || metadata.domains.contains("moods")) {newMoods=try await client.moods(sessionID:sid)}
            guard epoch == generation,changePoll.accepts(ticket),!Task.isCancelled,safeForChangeRead,barrier == changeReadBarrier else {return}
            if !client.isRemote && (metadata.resetRequired || metadata.domains.contains("actions")) {newActions=try await client.actions(sessionID:sid);newNext=try await client.nextStep(sessionID:sid)}
            guard epoch == generation,changePoll.accepts(ticket),!Task.isCancelled,safeForChangeRead,barrier == changeReadBarrier else {return}
            guard epoch == generation,changePoll.accepts(ticket),!Task.isCancelled,safeForChangeRead,barrier == changeReadBarrier else {return}
            guard client.isRemote || newActions.allSatisfy({$0.sessionId == sid && !$0.id.isEmpty}) else {throw EchoAPIError.message("动作更新不属于原主对话，未采用更新。")}
            let stable=try await client.conversationChanges(after:metadata.cursor)
            guard epoch == generation,changePoll.accepts(ticket),!Task.isCancelled,safeForChangeRead,barrier == changeReadBarrier else {return}
            guard stable.serviceInstanceId == metadata.serviceInstanceId,stable.conversationId == sid else {throw EchoAPIError.message("复核时连接身份变化，未提交更新。")}
            guard !stable.resetRequired,stable.domains.isEmpty,stable.cursor == metadata.cursor else {return}
            // MainActor has no await in this commit. Replace arrays, including
            // deletions/withdrawals; a partial read never escapes to current UI.
            conversation=snapshot;followups=newFollowups;boundary=newBoundary;remoteMoods=newMoods
            actions=client.isRemote ? [] : newActions;nextStep=client.isRemote ? nil : newNext
            changeServiceInstanceID=metadata.serviceInstanceId
            if changePoll.commit(ticket,cursor:metadata.cursor) {remoteReadRevision &+= 1;changeSyncStatus = .updated}
        } catch {
            guard epoch == generation,changePoll.accepts(ticket),!Task.isCancelled else {return}
            changePoll.failed(ticket);changeSyncStatus = .offline
        }
    }

}
