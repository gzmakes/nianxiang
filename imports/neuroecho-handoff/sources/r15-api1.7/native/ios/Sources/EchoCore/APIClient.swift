import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public enum EchoAPIError: LocalizedError, Sendable {
    case http(Int, String)
    case codedHTTP(Int, String, String)
    case message(String)
    public var errorDescription: String? {
        switch self { case .http(_, let message), .codedHTTP(_, _, let message), .message(let message): return message }
    }
    public var statusCode: Int? {switch self {case .http(let code,_),.codedHTTP(let code,_,_):return code;default:return nil}}
    public var errorCode: String? {if case .codedHTTP(_,let code,_) = self {return code};return nil}
}

private final class EchoRejectRedirects: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession,task: URLSessionTask,willPerformHTTPRedirection response: HTTPURLResponse,newRequest request: URLRequest,completionHandler: @escaping @Sendable (URLRequest?) -> Void) {completionHandler(nil)}
}

/// Model keys remain on the service. A paired device bearer is scoped to one
/// verified service identity, never attached to a redirect or query string.
public final class EchoAPI: @unchecked Sendable {
    public let baseURL: URL
    private let session: URLSession
    private let authorization: EchoDeviceAuthorization?
    private let redirects=EchoRejectRedirects()
    private let handlerLock=NSLock()
    private var authenticationFailure: (@Sendable (EchoAuthenticationFailure) -> Void)?
    public var isRemote: Bool {baseURL.scheme == "https"}
    public var storageNamespace: String {authorization?.profile?.namespace ?? baseURL.absoluteString}
    private var decoder: JSONDecoder { let value = JSONDecoder(); value.keyDecodingStrategy = .convertFromSnakeCase; return value }
    public init(baseURL: String, session: URLSession? = nil, authorization: EchoDeviceAuthorization? = nil) throws {
        self.baseURL = try Self.validatedBaseURL(baseURL)
        guard authorization == nil || self.baseURL.scheme == "https" else {throw EchoAPIError.message("设备令牌只用于 HTTPS 连接。")}
        if let profile=authorization?.profile {guard profile.origin == self.baseURL.absoluteString else {throw EchoAPIError.message("设备令牌不属于这个地址。")}}
        self.authorization=authorization
        self.session = session ?? URLSession(configuration:.ephemeral)
    }
    public func setAuthenticationFailureHandler(_ handler: @escaping @Sendable (EchoAuthenticationFailure)->Void) {handlerLock.lock();authenticationFailure=handler;handlerLock.unlock()}
    public func invalidateDeviceAuthorization() {authorization?.invalidate()}
    public func assertDeviceAuthorizationUsable() throws {if isRemote {_ = try authorization?.header();guard authorization != nil else {throw EchoAPIError.message("请先连接设备。")}}}
    private func reportAuthenticationFailure(_ profile: EchoDeviceProfile,code: String) {handlerLock.lock();let handler=authenticationFailure;handlerLock.unlock();handler?(.init(profile:profile,code:code))}
    public static func validatedBaseURL(_ text: String) throws -> URL {
        guard let parts = URLComponents(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              let url = parts.url, let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/",
              parts.scheme == "https" || (parts.scheme == "http" && ["127.0.0.1", "localhost", "::1"].contains(host)) else {
            throw EchoAPIError.message("请填写服务的 HTTPS 地址，或模拟器使用的 http://127.0.0.1:18787。请勿包含账号、路径或密钥。")
        }
        return url
    }
    private func endpoint(_ path: String, query: [URLQueryItem] = []) throws -> URL {
        guard var parts = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else { throw EchoAPIError.message("服务地址无效") }
        parts.path = path; parts.queryItems = query.isEmpty ? nil : query
        // Query parsers treat literal '+' as space. Preserve exact ISO CAS
        // tokens, including +00:00, when sending a version through DELETE.
        parts.percentEncodedQuery = parts.percentEncodedQuery?.replacingOccurrences(of:"+",with:"%2B")
        guard let url = parts.url else { throw EchoAPIError.message("请求地址无效") }
        return url
    }
    private func raw(_ path: String, method: String = "GET", body: [String: Any]? = nil, query: [URLQueryItem] = []) async throws -> (Data, Int) {
        if isRemote {
            guard let authorization else {throw EchoAPIError.message("这个 HTTPS 服务需要设备连接；没有发送匿名请求。")}
            guard authorization.profile != nil || path == "/api/paired-device" else {throw EchoAPIError.message("请先验证设备连接，尚未读取对话。")}
            if path == "/api/actions" || path == "/api/action" || path.hasPrefix("/api/action/") || path.hasPrefix("/api/lark/") || path.hasPrefix("/api/notion/") || path.hasPrefix("/api/onboarding/real/") {throw EchoAPIError.message("这项电脑本机操作不向设备连接开放；没有发送请求。")}
        }
        var request = URLRequest(url: try endpoint(path, query: query))
        request.httpMethod = method; request.timeoutInterval = 45
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let authorization {request.setValue(try authorization.header(),forHTTPHeaderField:"Authorization");if let profile=authorization.profile {request.setValue(profile.serviceInstanceID,forHTTPHeaderField:"X-Echo-Service-Instance")}}
        if let body { request.httpBody = try JSONSerialization.data(withJSONObject: body); request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        let (data, response) = try await session.data(for: request,delegate:redirects)
        guard let response = response as? HTTPURLResponse else { throw EchoAPIError.message("服务没有返回 HTTP 响应。") }
        guard (200...299).contains(response.statusCode) else {
            let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            let detail = object?["detail"] as? String
            let code=object?["error_code"] as? String
            if let profile=authorization?.profile, response.statusCode == 401 || (response.statusCode == 409 && code == "service_instance_mismatch") {
                authorization?.invalidate();reportAuthenticationFailure(profile,code:code ?? "paired_authentication_required")
            }
            if let code {throw EchoAPIError.codedHTTP(response.statusCode,code,detail ?? "服务请求未成功，请核对连接；已有草稿保留。")}
            throw EchoAPIError.http(response.statusCode, detail ?? "服务请求失败（\(response.statusCode)），请检查连接后重试；已有内容仍保留。")
        }
        // An old in-flight success must not escape after its identity is retired.
        try assertDeviceAuthorizationUsable()
        return (data, response.statusCode)
    }
    private func read<T: Decodable>(_ type: T.Type, _ path: String, method: String = "GET", body: [String: Any]? = nil, query: [URLQueryItem] = []) async throws -> T {
        let (data, _) = try await raw(path, method: method, body: body, query: query)
        do { return try decoder.decode(type, from: data) }
        catch { throw EchoAPIError.message("服务返回的格式暂不兼容，尚未确认结果。请检查服务版本并重新核对。") }
    }
    public func conversation() async throws -> EchoConversation { try await read(EchoConversation.self, "/api/conversation") }
    public func pairedDevice() async throws -> EchoPairedDevice {
        let value=try await read(EchoPairedDevice.self,"/api/paired-device")
        guard value.isValid,authorization?.profile?.matches(value) != false else {throw EchoAPIError.message("设备回执身份或有效期不匹配，没有启用连接。")}
        return value
    }
    /// R14 replacement reads distinguish an explicit empty/null collection
    /// from an omitted/malformed field, so a bad reply cannot look like deletion.
    public func changeConversationSnapshot() async throws -> EchoConversation {
        let (data,_)=try await raw("/api/conversation")
        guard let object=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any],
              object["messages"] is [Any],object["memories"] is [Any],let context=object["context"],
              context is NSNull || (context as? [String:Any])?["sources"] is [Any] else {throw EchoAPIError.message("更新快照的集合不完整，未把缺失内容当作删除。")}
        do {return try decoder.decode(EchoConversation.self,from:data)} catch {throw EchoAPIError.message("更新快照格式暂不兼容，已有内容保留。")}
    }
    public func conversationChanges(after: String? = nil) async throws -> EchoConversationChanges {
        if let after, !EchoConversationChanges.validCursor(after) {throw EchoAPIError.message("更新游标无效，没有发送请求。")}
        let value=try await read(EchoConversationChanges.self,"/api/conversation/changes",query:after.map {[.init(name:"after",value:$0)]} ?? [])
        guard value.isValid else {throw EchoAPIError.message("更新回执格式暂不兼容，已有内容与游标保留。")}
        if let profile=authorization?.profile {guard value.serviceInstanceId == profile.serviceInstanceID,value.conversationId == profile.conversationID else {throw EchoAPIError.message("更新回执不属于当前设备身份，没有读取新快照。")}}
        return value
    }
    public func capabilities() async throws -> EchoCapabilities { try await read(EchoCapabilities.self,"/api/capabilities") }
    public func moods(sessionID: String) async throws -> [EchoMood] {
        struct Result: Decodable {let moods:[EchoMood]}
        let result=try await read(Result.self,"/api/moods",query:[.init(name:"session_id",value:sessionID)]).moods
        guard result.allSatisfy(\.isValid), Set(result.map(\.date)).count == result.count else {throw EchoAPIError.message("心情记录格式待核对，已有草稿保留。")}
        return result
    }
    public func saveMood(sessionID: String, mutation: EchoMoodMutation) async throws -> EchoMood {
        guard !mutation.hasLedgerIdentity else {throw EchoAPIError.message("不能把账本请求改用旧保存接口。")}
        guard mutation.kind == .save, EchoMood.validDay(mutation.day), mutation.x.isFinite, mutation.y.isFinite, (-1...1).contains(mutation.x), (-1...1).contains(mutation.y), mutation.note.unicodeScalars.count <= 1000 else {throw EchoAPIError.message("请核对日期、两个已选位置和最多1000字的文字。")}
        let result=try await read(EchoMood.self,"/api/moods/\(mutation.day)",method:"PUT",body:["session_id":sessionID,"x":mutation.x,"y":mutation.y,"note":mutation.note,"confirmed":true,"expected_updated_at":mutation.expectedUpdatedAt as Any? ?? NSNull()])
        guard mutation.matches(result) else {throw EchoAPIError.message("保存回执不匹配，先只读核对；没有重新保存。")}
        return result
    }
    public func deleteMood(sessionID: String, mutation: EchoMoodMutation) async throws {
        guard !mutation.hasLedgerIdentity else {throw EchoAPIError.message("不能把账本请求改用旧删除接口。")}
        struct Result: Decodable {let deleted:Bool}
        guard mutation.kind == .delete, EchoMood.validDay(mutation.day), let token=mutation.expectedUpdatedAt, EchoFollowup.parse(token) != nil else {throw EchoAPIError.message("先读取这一天的最新记录再确认删除。")}
        let result=try await read(Result.self,"/api/moods/\(mutation.day)",method:"DELETE",query:[.init(name:"session_id",value:sessionID),.init(name:"expected_updated_at",value:token)])
        guard result.deleted else {throw EchoAPIError.message("没有收到明确删除回执，请只读核对。")}
    }
    public func applyMoodOperation(sessionID: String, mutation: EchoMoodMutation) async throws -> EchoMoodOperation {
        guard mutation.validLedgerIdentity, let id=mutation.requestID,let raw=mutation.operationJSON else {throw EchoAPIError.message("原请求身份不完整；不会重新编号或发送。")}
        let result=try await read(EchoMoodOperation.self,"/api/mood-operations",method:"POST",body:["session_id":sessionID,"request_id":id,"operation_json":raw,"confirmed":true])
        guard result.matches(sessionID:sessionID,mutation:mutation), result.state != "not_found" else {throw EchoAPIError.message("提交回执尚未匹配，请核对这次提交。")}
        return result
    }
    public func moodOperation(sessionID: String, mutation: EchoMoodMutation) async throws -> EchoMoodOperation {
        guard mutation.validLedgerIdentity,let id=mutation.requestID else {throw EchoAPIError.message("原请求身份不完整，请人工核对草稿。")}
        let result=try await read(EchoMoodOperation.self,"/api/mood-operations/\(id)",query:[.init(name:"session_id",value:sessionID)])
        guard result.matches(sessionID:sessionID,mutation:mutation) else {throw EchoAPIError.message("核对回执不属于原请求，未解除保护。")}
        return result
    }
    public func cancelMoodOperation(sessionID: String, mutation: EchoMoodMutation) async throws -> EchoMoodOperation {
        guard mutation.validLedgerIdentity,let id=mutation.requestID,let hash=mutation.operationHash else {throw EchoAPIError.message("原请求身份不完整，不会发送取消。")}
        let result=try await read(EchoMoodOperation.self,"/api/mood-operations/\(id)/cancel",method:"POST",body:["session_id":sessionID,"operation_sha256":hash,"kind":mutation.kind.rawValue,"confirmed":true])
        guard result.matches(sessionID:sessionID,mutation:mutation),result.state != "not_found" else {throw EchoAPIError.message("尚未确认取消；原草稿与取消意图仍保留。")}
        return result
    }
    public func boundary(sessionID: String) async throws -> EchoCompanionBoundary {
        try await read(EchoCompanionBoundary.self,"/api/companion-boundary",query:[.init(name:"session_id",value:sessionID)])
    }
    public func updateBoundary(sessionID: String, expectedRevision: Int, mode: String, until: Date?, timeZone: String) async throws -> EchoCompanionBoundary {
        guard expectedRevision >= 0, ["active","paused","until"].contains(mode), TimeZone(identifier:timeZone) != nil,
              mode == "until" ? (until.map {$0 > Date()} ?? false) : until == nil else {throw EchoAPIError.message("请核对安静方式、未来时间与时区。")}
        let value: Any=until.map {ISO8601DateFormatter().string(from:$0) as Any} ?? NSNull()
        let result=try await read(EchoCompanionBoundary.self,"/api/companion-boundary",method:"PUT",body:["session_id":sessionID,"expected_revision":expectedRevision,"confirmed":true,"mode":mode,"until":value,"time_zone":timeZone])
        guard result.revision > expectedRevision, result.mode == mode, result.timeZone == timeZone,
              mode == "until" ? EchoFollowup.parse(result.until) == EchoFollowup.parse(value as? String) : result.until == nil else {throw EchoAPIError.message("安静设置回执尚未匹配，请只读刷新核对。")}
        return result
    }
    public func stopDelivery(sessionID: String, messageID: String) async throws -> EchoDeliveryStop {
        guard !messageID.isEmpty else {throw EchoAPIError.message("先核对正在呈现的那条回复。")}
        let result = try await read(EchoDeliveryStop.self,"/api/session/\(sessionID)/delivery/stop",method:"POST",body:["message_id":messageID])
        guard result.ok, result.messageId == messageID,
              ["stopped","message_id_required","not_current","not_pending"].contains(result.reason),
              !result.stopped || result.confirms(messageID) else {throw EchoAPIError.message("停止呈现的回执不匹配，请重新读取对话核对。")}
        return result
    }
    public func followups(sessionID: String) async throws -> [EchoFollowup] {
        struct Response: Decodable {let followups:[EchoFollowup]}
        return try await read(Response.self,"/api/followups",query:[.init(name:"session_id",value:sessionID)]).followups
    }
    public func createFollowup(_ pending: EchoPendingFollowup) async throws -> EchoFollowup {
        guard pending.origin == storageNamespace else {throw EchoAPIError.message("跟进仍属于原服务，请回到原地址核对。")}
        let result = try await read(EchoFollowup.self,"/api/followups",method:"POST",body:pending.body)
        guard result.matches(pending), result.hasKnownStatus, !result.id.isEmpty else {throw EchoAPIError.message("跟进回执不匹配或状态未知，请刷新列表核对。")}
        return result
    }
    public func changeFollowup(id: String, sessionID: String, status: String) async throws -> EchoFollowup {
        guard ["done","cancelled"].contains(status) else {throw EchoAPIError.message("只可标记完成或取消。")}
        let result = try await read(EchoFollowup.self,"/api/followups/\(id)",method:"PATCH",body:["session_id":sessionID,"status":status])
        guard result.id == id, result.sessionId == sessionID, result.status == status else {throw EchoAPIError.message("跟进更新回执不匹配，请刷新列表核对。")}
        return result
    }
    public func changeFollowup(_ item: EchoFollowup, status: String) async throws -> EchoFollowup {
        guard item.status == "pending", item.supportsNativeTransitions, ["done","cancelled","paused","resumed"].contains(status),
              !(status == "done" && item.repeatRule == "daily" && (!item.due || item.paused == true)) else {throw EchoAPIError.message("跟进状态已变化，请刷新后再操作。")}
        var body: [String:Any]=["session_id":item.sessionId,"status":status]
        if status == "done" && item.repeatRule == "daily" {body["occurrence_at"]=item.dueAt}
        let result=try await read(EchoFollowup.self,"/api/followups/\(item.id)",method:"PATCH",body:body)
        guard result.confirmsTransition(from:item,target:status) else {throw EchoAPIError.message("跟进更新回执不匹配，请刷新列表核对。")}
        return result
    }
    public func nextStep(sessionID: String) async throws -> EchoNextStep { try await read(EchoNextStep.self, "/api/next-step", query: [.init(name: "session_id", value: sessionID)]) }
    public func actions(sessionID: String) async throws -> [EchoAction] {
        struct Response: Decodable { let actions: [EchoAction] }
        return try await read(Response.self, "/api/actions", query: [.init(name: "session_id", value: sessionID)]).actions
    }
    public func sources() async throws -> [EchoCatalogSource] {
        struct Response: Decodable { let sources: [EchoCatalogSource] }
        return try await read(Response.self, "/api/onboarding/sources", query: [.init(name: "force", value: "1")]).sources
    }
    public func send(_ turn: EchoPendingTurn) async throws -> EchoChatSubmission {
        var body: [String:Any]=["session_id":turn.sessionID,"text":turn.text,"request_id":turn.requestID,"memory_proposals":turn.memoryProposals ?? false]
        if let timeZone=turn.timeZone {body["time_zone"]=timeZone}
        let (data, status) = try await raw("/api/chat", method: "POST", body:body)
        if status != 202, let result = try? decoder.decode(EchoChatResult.self, from: data) { return .completed(result) }
        let record = try decoder.decode(EchoTurnRecord.self, from: data)
        return record.result.map(EchoChatSubmission.completed) ?? .pending(record)
    }
    public func recover(_ turn: EchoPendingTurn) async throws -> EchoTurnRecord {
        try await read(EchoTurnRecord.self, "/api/chat/turn/\(turn.requestID)", query: [.init(name: "session_id", value: turn.sessionID)])
    }
    public func cancel(_ turn: EchoPendingTurn) async throws -> EchoTurnRecord {
        try await read(EchoTurnRecord.self, "/api/chat/turn/\(turn.requestID)/cancel", method: "POST", body: ["session_id": turn.sessionID])
    }
    /// Read-only reconciliation before the user ends a terminal unknown wait.
    /// A running/completed request cannot be released through this path.
    public func reviewBeforeEndingLocalWait(_ turn: EchoPendingTurn) async throws -> EchoConversation {
        let record = try await recover(turn)
        guard record.requestId == turn.requestID, record.sessionId == turn.sessionID,
              record.permitsEndingLocalWait else {
            throw EchoAPIError.message("原请求的状态已经变化，请先核对状态；没有清除等待或重新发送。")
        }
        let snapshot = try await conversation()
        guard snapshot.session.id == turn.sessionID else {
            throw EchoAPIError.message("主对话发生变化，原发送状态仍保留，请核对服务数据。")
        }
        return snapshot
    }
    public func updateMemory(id: String, text: String? = nil, confirm: Bool = false, expectedVersion: Int? = nil) async throws -> EchoMemory {
        var body: [String: Any] = [:]; if let text { body["text"] = text }; if confirm { body["status"] = "confirmed" }
        if let expectedVersion { body["expected_version"] = expectedVersion }
        return try await read(EchoMemory.self, "/api/memory/\(id)", method: "PATCH", body: body)
    }
    public func deleteMemory(id: String, expectedVersion: Int? = nil) async throws {
        _ = try await raw("/api/memory/\(id)", method: "DELETE", query: expectedVersion.map { [.init(name:"expected_version",value:String($0))] } ?? [])
    }
    public func addMemory(sessionID: String, text: String) async throws -> EchoMemory {
        let text = text.trimmingCharacters(in:.whitespacesAndNewlines)
        guard !text.isEmpty, text.unicodeScalars.count <= 2000 else { throw EchoAPIError.message("记忆内容需为 1–2000 字。") }
        return try await read(EchoMemory.self,"/api/memory",method:"POST",body:["session_id":sessionID,"kind":"fact","text":text,"source":"用户手动添加"])
    }
    public func saveQuote(sessionID: String, messageID: String) async throws -> EchoMemory {
        try await read(EchoMemory.self,"/api/memory/proposal",method:"POST",body:["session_id":sessionID,"message_id":messageID,"confirm":true])
    }
    public func history(memoryID: String) async throws -> [EchoRevision] {
        struct Response: Decodable { let revisions: [EchoRevision] }
        return try await read(Response.self, "/api/memory/\(memoryID)/history").revisions
    }
    public func attachFiles(_ files: [EchoSelectedFile], sessionID: String) async throws -> EchoConversation {
        guard (1...3).contains(files.count) else { throw EchoAPIError.message("一次请选择 1–3 份文本文件。") }
        return try await read(EchoConversation.self, "/api/local-files/confirm", method: "POST", body: ["session_id": sessionID, "files": files.map { ["name": $0.name, "text": $0.text] }])
    }
    public func previewSource(_ id: String, target: String = "") async throws -> EchoPreview {
        if id == "feishu" { return try await read(EchoPreview.self, "/api/lark/preview", method: "POST", body: ["url": target]) }
        if id == "notion" { return try await read(EchoPreview.self, "/api/notion/preview", method: "POST", body: ["url": target, "method": "cli"]) }
        var body: [String: Any] = ["source_id": id]; if id == "git" { body["path"] = target }
        return try await read(EchoPreview.self, "/api/onboarding/real/read", method: "POST", body: body)
    }
    public func attachSource(_ id: String, target: String, previewID: String, sessionID: String) async throws -> EchoConversation {
        if id == "feishu" { return try await read(EchoConversation.self, "/api/lark/attach", method: "POST", body: ["url": target, "preview_id": previewID, "session_id": sessionID]) }
        if id == "notion" { return try await read(EchoConversation.self, "/api/notion/start", method: "POST", body: ["preview_id": previewID, "session_id": sessionID]) }
        return try await read(EchoConversation.self, "/api/onboarding/real/start", method: "POST", body: ["source_id": id, "preview_id": previewID, "session_id": sessionID])
    }
    public func revokeSource(id: String, sessionID: String) async throws {
        struct Response: Decodable { let ok: Bool; let reason: String? }
        let result = try await read(Response.self, "/api/source/revoke", method: "POST", body: ["source_id": id, "session_id": sessionID])
        guard result.ok else { throw EchoAPIError.message(result.reason ?? "这份资料尚未确认撤回，请刷新连接列表核对。") }
    }
    public func createAction(sessionID: String, kind: String, title: String, detail: String, when: String) async throws -> EchoAction {
        try await read(EchoAction.self, "/api/action", method: "POST", body: ["session_id": sessionID, "kind": kind, "title": title, "detail": detail, "when": when])
    }
    public func commitAction(id: String) async throws -> EchoAction {
        try await read(EchoAction.self, "/api/action/\(id)/commit", method: "POST", body: ["real": false])
    }
    public func requirePreviewedAction(id: String, sessionID: String) async throws -> EchoAction {
        let records = try await actions(sessionID: sessionID)
        guard let action = records.first(where: { $0.id == id }), action.status == "previewed",
              action.sessionId == nil || action.sessionId == sessionID else {
            throw EchoAPIError.message("这条记录已处理或结果待确认，请返回任务列表核对；不会新建或再次写入。")
        }
        return action
    }
}
