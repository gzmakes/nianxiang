import EchoCore
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

// Portable Foundation contract checks for CLT hosts without XCTest or an iOS SDK.
private let checksLock = NSLock()
private var failureCount = 0
private func fail(_ message: String) { checksLock.lock(); failureCount += 1; checksLock.unlock(); print("FAIL: \(message)") }
private func XCTFail(_ message: String) { fail(message) }
private func XCTAssertEqual<T: Equatable>(_ lhs: @autoclosure () throws -> T, _ rhs: @autoclosure () throws -> T) { do { if try lhs() != rhs() {fail("equality assertion")} } catch {fail("unexpected assertion error")} }
private func XCTAssertTrue(_ value: @autoclosure () throws -> Bool) {do {if try !value() {fail("expected true")}} catch {fail("assertion threw")} }
private func XCTAssertFalse(_ value: @autoclosure () throws -> Bool) {do {if try value() {fail("expected false")}} catch {fail("assertion threw")} }
private func XCTAssertNil<T>(_ value: @autoclosure () throws -> T?) {do {if try value() != nil {fail("expected nil")}} catch {fail("assertion threw")} }
private func XCTAssertNotNil<T>(_ value: @autoclosure () throws -> T?) {do {if try value() == nil {fail("expected a value")}} catch {fail("assertion threw")} }
private func XCTAssertNoThrow<T>(_ value: @autoclosure () throws -> T) {do {_ = try value()} catch {fail("expected no error")} }
private func XCTAssertThrowsError<T>(_ value: @autoclosure () throws -> T) {do {_ = try value();fail("expected rejection")} catch {} }

private final class MockProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, String))!
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do { let (code, text) = try Self.handler(request)
            let response = HTTPURLResponse(url:request.url!,statusCode:code,httpVersion:nil,headerFields:["Content-Type":"application/json"])!
            client?.urlProtocol(self,didReceive:response,cacheStoragePolicy:.notAllowed)
            client?.urlProtocol(self,didLoad:Data(text.utf8)); client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self,didFailWithError:error) }
    }
    override func stopLoading() {}
}
final class EchoCoreTests {
    private let snapshot = #"{"session":{"id":"canonical","mode":"empty"},"messages":[],"memories":[],"bookmark":null,"context":null}"#
    private func api(_ handler: @escaping (URLRequest) throws -> (Int,String)) throws -> EchoAPI {
        MockProtocol.handler = handler
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [MockProtocol.self]
        return try EchoAPI(baseURL:"http://127.0.0.1:18787",session:URLSession(configuration:config))
    }
    private func body(_ request: URLRequest) throws -> [String:Any] {
        let data: Data
        if let value = request.httpBody { data = value }
        else if let stream = request.httpBodyStream { stream.open(); defer {stream.close()}; var value = Data(); var buffer = [UInt8](repeating:0,count:1024); while stream.hasBytesAvailable { let count = stream.read(&buffer,maxLength:buffer.count); if count <= 0 {break}; value.append(buffer,count:count) }; data = value }
        else { return [:] }
        return try JSONSerialization.jsonObject(with:data) as! [String:Any]
    }
    func testConfiguredAddressAcceptsOnlyExplicitHTTPSOrLoopbackHTTP() throws {
        XCTAssertNoThrow(try EchoAPI.validatedBaseURL("http://127.0.0.1:18787"))
        XCTAssertNoThrow(try EchoAPI.validatedBaseURL("https://echo.example.invalid"))
        for value in ["http://192.168.1.2:18787","https://user:password@example.invalid","https://example.invalid/api","https://example.invalid?token=secret","file:///tmp/server"] { XCTAssertThrowsError(try EchoAPI.validatedBaseURL(value)) }
    }
    func testBootstrapUsesOnlyCanonicalGETAndDoesNotCreateAConversation() async throws {
        let data = snapshot; var calls = 0
        let client = try api { request in calls += 1; XCTAssertEqual(request.httpMethod,"GET"); XCTAssertEqual(request.url?.path,"/api/conversation"); XCTAssertNil(request.value(forHTTPHeaderField:"Authorization")); return (200,data) }
        let result = try await client.conversation(); XCTAssertEqual(result.session.id,"canonical"); XCTAssertEqual(calls,1)
    }
    func testChatUsesStableRequestIDAndExactTextWithoutModelSecrets() async throws {
        var calls = 0
        let client = try api { request in calls += 1; XCTAssertEqual(request.url?.path,"/api/chat"); let body = try self.body(request); XCTAssertEqual(body["session_id"] as? String,"canonical"); XCTAssertEqual(body["request_id"] as? String,"stable-turn-0001"); XCTAssertEqual(body["text"] as? String,"合成的一句话"); XCTAssertEqual(body["memory_proposals"] as? Bool,false); XCTAssertNil(body["api_key"]); return (200,#"{"messages":[],"memories":[],"reply":"合成回复"}"#) }
        let turn = EchoPendingTurn(sessionID:"canonical",text:"合成的一句话",origin:"http://127.0.0.1:18787",requestID:"stable-turn-0001")
        if case .completed(let value) = try await client.send(turn) { XCTAssertEqual(value.reply,"合成回复") } else { XCTFail("expected completed") }; XCTAssertEqual(calls,1)
    }
    func testAcceptedPendingResponseDoesNotSilentlyResend() async throws {
        var calls = 0
        let client = try api { request in calls += 1; XCTAssertEqual(request.httpMethod,"POST"); return (202,#"{"request_id":"stable-turn-0001","session_id":"canonical","status":"running","cancel_requested":false}"#) }
        if case .pending(let record) = try await client.send(.init(sessionID:"canonical",text:"合成",origin:"http://127.0.0.1:18787",requestID:"stable-turn-0001")) { XCTAssertEqual(record.status,"running") } else { XCTFail("expected pending") }; XCTAssertEqual(calls,1)
    }
    func testRecoveryOnlyReadsTheSameTurnAndCanonicalID() async throws {
        let client = try api { request in XCTAssertEqual(request.httpMethod,"GET"); XCTAssertEqual(request.url?.path,"/api/chat/turn/stable-turn-0001"); XCTAssertEqual(URLComponents(url:request.url!,resolvingAgainstBaseURL:false)?.queryItems?.first?.value,"canonical"); return (200,#"{"request_id":"stable-turn-0001","session_id":"canonical","status":"completed","result":{"messages":[],"cancelled":false}}"#) }
        let value = try await client.recover(.init(sessionID:"canonical",text:"保留的文字",origin:"http://127.0.0.1:18787",requestID:"stable-turn-0001")); XCTAssertNotNil(value.result)
    }
    func testCancelDoesNotRetransmitTextOrCreateAnotherTurn() async throws {
        let client = try api { request in XCTAssertEqual(request.httpMethod,"POST"); XCTAssertEqual(request.url?.path,"/api/chat/turn/stable-turn-0001/cancel"); XCTAssertEqual(try self.body(request).count,1); return (200,#"{"request_id":"stable-turn-0001","session_id":"canonical","status":"cancelled","result":{"messages":[],"cancelled":true}}"#) }
        let value = try await client.cancel(.init(sessionID:"canonical",text:"合成",origin:"http://127.0.0.1:18787",requestID:"stable-turn-0001")); XCTAssertEqual(value.result?.cancelled,true)
    }

    func testCompletedCancelReceiptNeverClaimsItWasStopped() async throws {
        let client = try api { request in
            XCTAssertEqual(request.url?.path,"/api/chat/turn/stable-turn-0001/cancel")
            return (200,#"{"request_id":"stable-turn-0001","session_id":"canonical","status":"completed","result":{"messages":[],"cancelled":false}}"#)
        }
        let record = try await client.cancel(.init(sessionID:"canonical",text:"合成",origin:"http://127.0.0.1:18787",requestID:"stable-turn-0001"))
        XCTAssertFalse(record.cancellationNotice.contains("已停止")); XCTAssertTrue(record.cancellationNotice.contains("未能撤回"))
        XCTAssertFalse(record.permitsEndingLocalWait)
    }
    func testUnknownReviewOnlyReadsOriginalTurnAndCanonicalSnapshot() async throws {
        var paths = [String](); let data = snapshot
        let client = try api { request in
            XCTAssertEqual(request.httpMethod,"GET"); paths.append(request.url!.path)
            if paths.count == 1 { return (200,#"{"request_id":"stable-turn-0001","session_id":"canonical","status":"unknown","cancel_requested":true}"#) }
            return (200,data)
        }
        let current = try await client.reviewBeforeEndingLocalWait(.init(sessionID:"canonical",text:"保留原话",origin:"http://127.0.0.1:18787",requestID:"stable-turn-0001",cancelWanted:true))
        XCTAssertEqual(current.session.id,"canonical")
        XCTAssertEqual(paths,["/api/chat/turn/stable-turn-0001","/api/conversation"])
    }
    func testRunningRequestCannotEndLocalWaitOrCreateAnotherSend() async throws {
        var calls = 0
        let client = try api { request in calls += 1; XCTAssertEqual(request.httpMethod,"GET"); return (200,#"{"request_id":"stable-turn-0001","session_id":"canonical","status":"running"}"#) }
        do { _ = try await client.reviewBeforeEndingLocalWait(.init(sessionID:"canonical",text:"合成",origin:"http://127.0.0.1:18787",requestID:"stable-turn-0001")); XCTFail("must retain running pending") }
        catch { XCTAssertEqual(calls,1) }
    }
    func testCompletedRequestMustBeRecoveredInsteadOfAbandoned() async throws {
        var calls = 0
        let client = try api { request in calls += 1; XCTAssertEqual(request.httpMethod,"GET"); return (200,#"{"request_id":"stable-turn-0001","session_id":"canonical","status":"completed","result":{"messages":[],"cancelled":false}}"#) }
        do { _ = try await client.reviewBeforeEndingLocalWait(.init(sessionID:"canonical",text:"合成",origin:"http://127.0.0.1:18787",requestID:"stable-turn-0001")); XCTFail("must recover completed result") }
        catch { XCTAssertEqual(calls,1) }
    }
    func testUnknownReviewRejectsChangedCanonicalConversation() async throws {
        var calls = 0
        let client = try api { request in calls += 1; XCTAssertEqual(request.httpMethod,"GET"); if calls == 1 { return (200,#"{"request_id":"stable-turn-0001","session_id":"canonical","status":"unknown"}"#) }; return (200,#"{"session":{"id":"different"},"messages":[],"memories":[]}"#) }
        do { _ = try await client.reviewBeforeEndingLocalWait(.init(sessionID:"canonical",text:"合成",origin:"http://127.0.0.1:18787",requestID:"stable-turn-0001")); XCTFail("must retain original pending") }
        catch { XCTAssertEqual(calls,2) }
    }
    func testFileSelectionEnforcesNamesAndUnicodeScalarLimit() throws {
        let file = try EchoSelectedFile(name:"合成.txt",text:String(repeating:"🙂",count:4_001)); XCTAssertEqual(file.text.unicodeScalars.count,4_000)
        for name in ["../private.txt","folder/file.txt","secret.env","bad\n.txt"] { XCTAssertThrowsError(try EchoSelectedFile(name:name,text:"合成")) }
        XCTAssertThrowsError(try EchoSelectedFile(name:"plain.txt",text:"\0private"))
    }
    func testSelectedFilesAttachToCanonicalWithoutReadingPathsOrCreatingSession() async throws {
        let data = snapshot
        let client = try api { request in XCTAssertEqual(request.url?.path,"/api/local-files/confirm"); let body = try self.body(request); XCTAssertEqual(body["session_id"] as? String,"canonical"); let files = body["files"] as! [[String:String]]; XCTAssertEqual(files,[ ["name":"chosen.txt","text":"explicit synthetic text"] ]); return (200,data) }
        let value = try await client.attachFiles([try EchoSelectedFile(name:"chosen.txt",text:"explicit synthetic text")],sessionID:"canonical"); XCTAssertEqual(value.session.id,"canonical")
    }
    func testFileBatchCannotExceedThree() async throws {
        var calls = 0; let client = try api {_ in calls += 1; return (500,"")}
        do { _ = try await client.attachFiles((0..<4).map {try EchoSelectedFile(name:"\($0).txt",text:"合成")},sessionID:"canonical"); XCTFail("must reject") } catch { XCTAssertEqual(calls,0) }
    }
    func testMemoryConfirmationHistoryAndDeletionUseRealEndpoints() async throws {
        var methods = [String]()
        let client = try api { request in methods.append(request.httpMethod!); XCTAssertTrue(request.url!.path.hasPrefix("/api/memory/memory-1")); if request.httpMethod == "PATCH" { XCTAssertEqual(try self.body(request)["status"] as? String,"confirmed"); return (200,#"{"id":"memory-1","kind":"fact","text":"合成偏好","status":"confirmed","version":2,"source":"用户手动添加"}"#) }; if request.httpMethod == "DELETE" {return (200,#"{"ok":true}"#)}; return (200,#"{"revisions":[]}"#) }
        let value = try await client.updateMemory(id:"memory-1",confirm:true); XCTAssertEqual(value.version,2)
        _ = try await client.history(memoryID:"memory-1"); try await client.deleteMemory(id:"memory-1"); XCTAssertEqual(methods,["PATCH","GET","DELETE"])
    }
    func testPreviewAndAttachAreSeparateExplicitOperations() async throws {
        var paths = [String](); let data = snapshot
        let client = try api { request in paths.append(request.url!.path); let body = try self.body(request); if paths.count == 1 { XCTAssertEqual(body["url"] as? String,"https://example.feishu.cn/docx/chosen"); return (200,#"{"ok":true,"preview_id":"reviewed","title":"合成资料","preview":"合成开头"}"#) }; XCTAssertEqual(body["preview_id"] as? String,"reviewed"); XCTAssertEqual(body["session_id"] as? String,"canonical"); return (200,data) }
        let preview = try await client.previewSource("feishu",target:"https://example.feishu.cn/docx/chosen"); XCTAssertEqual(paths.count,1)
        _ = try await client.attachSource("feishu",target:"https://example.feishu.cn/docx/chosen",previewID:preview.requireID(),sessionID:"canonical"); XCTAssertEqual(paths,["/api/lark/preview","/api/lark/attach"])
    }
    func testNotionUsesExistingCLIWithoutTokenOrNewLogin() async throws {
        let client = try api { request in XCTAssertEqual(request.url?.path,"/api/notion/preview"); let body = try self.body(request); XCTAssertEqual(body["method"] as? String,"cli"); XCTAssertNil(body["token"]); return (200,#"{"ok":false,"error":"尚未登录","hint":"先在Mac配置"}"#) }
        let preview = try await client.previewSource("notion",target:"https://notion.so/chosen"); XCTAssertThrowsError(try preview.requireID())
    }
    func testRevokeChecksActualAcknowledgementAndCanonicalSourceID() async throws {
        let client = try api { request in XCTAssertEqual(request.url?.path,"/api/source/revoke"); let body = try self.body(request); XCTAssertEqual(body["source_id"] as? String,"source-1"); XCTAssertEqual(body["session_id"] as? String,"canonical"); return (200,#"{"ok":false,"reason":"合成的来源状态已变化"}"#) }
        do { try await client.revokeSource(id:"source-1",sessionID:"canonical"); XCTFail("must not report success") } catch { XCTAssertTrue(error.localizedDescription.contains("来源状态")) }
    }
    func testActionCommitAlwaysUsesRealFalse() async throws {
        let client = try api { request in XCTAssertEqual(request.url?.path,"/api/action/existing-preview/commit"); XCTAssertEqual(try self.body(request)["real"] as? Bool,false); return (200,#"{"id":"existing-preview","kind":"message","title":"合成草稿","status":"committed","real":0}"#) }
        let result = try await client.commitAction(id:"existing-preview"); XCTAssertEqual(result.statusLabel,"草稿已保存 · 未发送")
    }
    private func decodedAction(status: String, kind: String = "calendar", real: Int = 0) throws -> EchoAction {
        let data = try JSONSerialization.data(withJSONObject: ["id":"synthetic-action", "session_id":"canonical", "kind":kind, "title":"合成动作", "status":status, "real":real])
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(EchoAction.self, from:data)
    }
    func testDecodedCommittedActionsDistinguishDraftLocalAndSystemResults() throws {
        XCTAssertEqual(try decodedAction(status:"committed",kind:"message").statusLabel,"草稿已保存 · 未发送")
        XCTAssertEqual(try decodedAction(status:"committed",real:0).statusLabel,"已保存到回响服务 · 未写入系统")
        XCTAssertEqual(try decodedAction(status:"committed",real:1).statusLabel,"已写入 Mac 系统")
    }
    func testDecodedNonCommittedActionsNeverClaimSavedOrSystemWritten() throws {
        for kind in ["message", "calendar"] {
            for real in [0,1] {
                for status in ["cancelled", "rejected", "future-status-v2", "", "unknown", "executing"] {
                    let action = try decodedAction(status:status,kind:kind,real:real)
                    XCTAssertEqual(action.statusLabel,"结果待核对 · 不会自动重试")
                    XCTAssertFalse(action.statusLabel.contains("已保存"))
                    XCTAssertFalse(action.statusLabel.contains("已写入"))
                }
                XCTAssertEqual(try decodedAction(status:"previewed",kind:kind,real:real).statusLabel,"待你确认")
                XCTAssertEqual(try decodedAction(status:"failed",kind:kind,real:real).statusLabel,"未能完成")
            }
        }
    }
    func testUnknownExistingActionOnlyReadsAndCannotPassConfirmationGuard() async throws {
        var calls = 0
        let client = try api { request in calls += 1; XCTAssertEqual(request.httpMethod,"GET"); XCTAssertEqual(request.url?.path,"/api/actions"); return (200,#"{"actions":[{"id":"existing-preview","session_id":"canonical","kind":"calendar","title":"合成","status":"unknown"}]}"#) }
        do { _ = try await client.requirePreviewedAction(id:"existing-preview",sessionID:"canonical"); XCTFail("must reject") } catch { XCTAssertEqual(calls,1) }
    }
    func testPreviewedActionGuardKeepsItsOriginalIDAndRejectsAnotherConversation() async throws {
        let client = try api { _ in (200,#"{"actions":[{"id":"existing-preview","session_id":"canonical","kind":"calendar","title":"合成","status":"previewed"}]}"#) }
        let item = try await client.requirePreviewedAction(id:"existing-preview",sessionID:"canonical"); XCTAssertEqual(item.id,"existing-preview")
        do { _ = try await client.requirePreviewedAction(id:"existing-preview",sessionID:"other"); XCTFail("must reject") } catch { }
    }
    func testHTTPBudgetErrorIsActionableAndNotMisrepresentedAsSuccess() async throws {
        let client = try api { _ in (429,#"{"detail":"近60分钟达到40轮，请稍后再试；内容仍保留。"}"#) }
        do { _ = try await client.conversation(); XCTFail("must fail") } catch let error as EchoAPIError { XCTAssertEqual(error.statusCode,429); XCTAssertTrue(error.localizedDescription.contains("近60分钟")) }
    }

    func testPendingMemoryPreferenceSurvivesPersistenceAndUsesSamePayload() async throws {
        let turn = EchoPendingTurn(sessionID:"canonical",text:"合成原话",origin:"http://127.0.0.1:18787",requestID:"stable-pref",memoryProposals:true)
        let restored = try JSONDecoder().decode(EchoPendingTurn.self,from:JSONEncoder().encode(turn))
        var payloads = [String]()
        let client = try api { request in
            let value = try self.body(request)
            XCTAssertEqual(value["memory_proposals"] as? Bool,true)
            XCTAssertEqual(value["request_id"] as? String,"stable-pref")
            payloads.append(String(data:try JSONSerialization.data(withJSONObject:value,options:.sortedKeys),encoding:.utf8)!)
            return (200,#"{"messages":[]}"#)
        }
        _ = try await client.send(turn); _ = try await client.send(restored)
        XCTAssertEqual(payloads.count,2); XCTAssertEqual(payloads.first,payloads.last)
    }
    func testLegacyPendingRequestKeepsMemoryPreferenceOff() async throws {
        let old = Data(#"{"requestID":"old-turn","sessionID":"canonical","text":"合成旧草稿","origin":"http://127.0.0.1:18787","cancelWanted":false}"#.utf8)
        let turn = try JSONDecoder().decode(EchoPendingTurn.self,from:old)
        let client = try api { request in XCTAssertEqual(try self.body(request)["memory_proposals"] as? Bool,false); return (200,#"{"messages":[]}"#) }
        _ = try await client.send(turn)
    }
    func testManualMemoryIsExplicitCandidateAndValidatesTextBeforePosting() async throws {
        var calls = 0
        let client = try api { request in
            calls += 1; XCTAssertEqual(request.httpMethod,"POST"); XCTAssertEqual(request.url?.path,"/api/memory")
            let body = try self.body(request)
            XCTAssertEqual(body["session_id"] as? String,"canonical"); XCTAssertEqual(body["text"] as? String,"合成偏好")
            XCTAssertEqual(body["source"] as? String,"用户手动添加"); XCTAssertNil(body["status"]); XCTAssertNil(body["confirm"])
            return (200,#"{"id":"manual","kind":"fact","text":"合成偏好","status":"candidate","version":1,"source":"用户手动添加"}"#)
        }
        let memory = try await client.addMemory(sessionID:"canonical",text:"  合成偏好\n")
        XCTAssertEqual(memory.status,"candidate")
        for text in [" ",String(repeating:"字",count:2001)] { do { _ = try await client.addMemory(sessionID:"canonical",text:text); XCTFail("must reject") } catch {} }
        XCTAssertEqual(calls,1)
    }
    func testQuoteMemoryOnlyConfirmsTheExplicitOriginalMessage() async throws {
        let client = try api { request in
            XCTAssertEqual(request.url?.path,"/api/memory/proposal")
            let body = try self.body(request)
            XCTAssertEqual(body["session_id"] as? String,"canonical"); XCTAssertEqual(body["message_id"] as? String,"user-original"); XCTAssertEqual(body["confirm"] as? Bool,true)
            XCTAssertNil(body["text"])
            return (200,#"{"id":"quote","kind":"fact","text":"合成原话","status":"confirmed","version":1,"source":"对话原话 · 用户选存","source_message_id":"user-original"}"#)
        }
        let result = try await client.saveQuote(sessionID:"canonical",messageID:"user-original")
        XCTAssertEqual(result.sourceMessageId,"user-original")
    }
    func testMemoryCASUsesExactVersionAndConflictDoesNotRetry() async throws {
        var calls = 0
        let client = try api { request in
            calls += 1
            if request.httpMethod == "PATCH" { XCTAssertEqual(try self.body(request)["expected_version"] as? Int,4) }
            else { XCTAssertEqual(request.httpMethod,"DELETE"); XCTAssertEqual(URLComponents(url:request.url!,resolvingAgainstBaseURL:false)?.queryItems?.first?.value,"4") }
            return (409,#"{"detail":"版本已变化","error_code":"memory_version_conflict","expected_version":4,"current_version":5}"#)
        }
        do { _ = try await client.updateMemory(id:"memory-1",text:"保留编辑",expectedVersion:4); XCTFail("must conflict") } catch let error as EchoAPIError { XCTAssertEqual(error.statusCode,409) }
        XCTAssertEqual(calls,1)
        do { try await client.deleteMemory(id:"memory-1",expectedVersion:4); XCTFail("must conflict") } catch let error as EchoAPIError { XCTAssertEqual(error.statusCode,409) }
        XCTAssertEqual(calls,2)
    }
    func testUnifiedLocalSearchIncludesMemoryAndMessagesButNotDeletedMemory() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let data = Data(#"{"session":{"id":"canonical"},"messages":[{"id":"same","role":"user","text":"合成Coffee偏好"}],"memories":[{"id":"same","kind":"fact","text":"合成coffee记忆","status":"confirmed","version":2,"source":"用户手动添加"},{"id":"deleted","kind":"fact","text":"coffee已忘掉","status":"deleted","version":1,"source":"用户手动添加"}]}"#.utf8)
        let snapshot = try decoder.decode(EchoConversation.self,from:data)
        let hits = EchoWorkspace.search(snapshot,query:" COFFEE ")
        XCTAssertEqual(hits.count,2); XCTAssertEqual(hits.map(\.id),["message:same","memory:same"])
        XCTAssertEqual(EchoWorkspace.search(snapshot,query:" ").count,0)
        XCTAssertEqual(EchoWorkspace.search(nil,query:"coffee").count,0)
    }
    func testTopicViewsRemainLocalLabelsWithDailyDefault() {
        XCTAssertEqual(EchoWorkspace.topic(for:"unlabelled",assignments:[:]),"日常")
        XCTAssertEqual(EchoWorkspace.normalizedTopic(" 周五方案 "),"周五方案")
        XCTAssertNil(EchoWorkspace.normalizedTopic("全部")); XCTAssertNil(EchoWorkspace.normalizedTopic(String(repeating:"字",count:21)))
        XCTAssertEqual(EchoWorkspace.topicLabels(assignments:["m":"周五方案","n":"日常"]),["全部","日常","周五方案"])
    }

    func testCapabilitiesMetadataNeverProbesOrClaimsAuthorization() async throws {
        var calls = 0
        let client = try api { request in
            calls += 1; XCTAssertEqual(request.httpMethod,"GET"); XCTAssertEqual(request.url?.path,"/api/capabilities")
            return (200,#"{"contract_version":"1.1.0","deployment_mode":"local_single_user","service_platform":"linux","features":{"memory_expected_version_patch":true,"remote_user_authentication":false,"realtime_multi_device_sync":false},"platform_status":{"apple_calendar":"platform_unsupported"},"connection_status":"not_probed"}"#)
        }
        let value = try await client.capabilities()
        XCTAssertEqual(value.features["remote_user_authentication"],false)
        XCTAssertEqual(value.features["realtime_multi_device_sync"],false)
        XCTAssertEqual(value.platformStatus["apple_calendar"],"platform_unsupported")
        XCTAssertEqual(value.connectionStatus,"not_probed"); XCTAssertEqual(calls,1)
    }
    func testSourcePreviewRequiresActualTextOrItemBeforeConfirmation() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        for value in [
            #"{"ok":true,"preview_id":"p","title":"只有标题","understanding":{"facts":["生成理解"]}}"#,
            #"{"ok":true,"preview_id":"p","preview":" ","items":[{"title":"","summary":" "} ]}"#
        ] {
            let preview = try decoder.decode(EchoPreview.self,from:Data(value.utf8))
            XCTAssertFalse(preview.hasReviewableContent); XCTAssertThrowsError(try preview.requireID())
        }
        let value = #"{"ok":true,"preview_id":"reviewed","items":[{"title":"真实日历条目","summary":"只读摘要"}],"understanding":{"facts":["资料事实"],"inferences":["待确认推测"],"questions":["待核对问题"]}}"#
        let preview = try decoder.decode(EchoPreview.self,from:Data(value.utf8))
        XCTAssertEqual(try preview.requireID(),"reviewed")
        XCTAssertEqual(preview.understanding?.inferences,["待确认推测"])
    }
    func testFollowupRejectsInvalidDraftBeforeAnyNetworkRequest() async throws {
        let now = Date(timeIntervalSince1970:1_000)
        XCTAssertThrowsError(try EchoPendingFollowup(sessionID:"canonical",content:" ",date:now.addingTimeInterval(60),origin:"http://127.0.0.1:18787",now:now))
        XCTAssertThrowsError(try EchoPendingFollowup(sessionID:"canonical",content:"合成",date:now,origin:"http://127.0.0.1:18787",now:now))
        var calls = 0
        let client = try api { _ in calls += 1; return (500,"{}") }
        let pending = try EchoPendingFollowup(sessionID:"canonical",content:"合成",date:now.addingTimeInterval(60),origin:"https://other.example.invalid",now:now)
        do { _ = try await client.createFollowup(pending); XCTFail("must reject another origin") } catch {}
        do { _ = try await client.changeFollowup(id:"f",sessionID:"canonical",status:"sent"); XCTFail("must reject unknown transition") } catch {}
        XCTAssertEqual(calls,0)
    }
    func testFollowupDoesNotAcceptMismatchedOrUnknownReceipt() async throws {
        let date = Date(timeIntervalSince1970:2_000)
        let pending = try EchoPendingFollowup(sessionID:"canonical",content:"合成跟进",date:date,origin:"http://127.0.0.1:18787",requestID:"stable-followup",now:Date(timeIntervalSince1970:1_000))
        for (content,status) in [("内容不同","pending"),("合成跟进","future-status")] {
            var calls = 0
            let client = try api { _ in
                calls += 1
                let body: [String:Any] = ["id":"f","session_id":"canonical","request_id":"stable-followup","content":content,"due_at":pending.dueAt,"status":status,"due":false]
                return (200,String(data:try JSONSerialization.data(withJSONObject:body),encoding:.utf8)!)
            }
            do {_ = try await client.createFollowup(pending); XCTFail("must not claim saved")} catch {}
            XCTAssertEqual(calls,1)
        }
    }
    func testUnexpectedHTMLDoesNotExposeRawServerResponse() async throws {
        let client = try api { _ in (500,"<html>synthetic-private-response</html>") }
        do { _ = try await client.conversation(); XCTFail("must fail") } catch { XCTAssertFalse(error.localizedDescription.contains("synthetic-private")) }
    }
    func testFollowupContractKeepsConfirmationAndStableRequestID() async throws {
        var methods: [String] = []
        let pending = #"{"id":"fup-1","session_id":"canonical","request_id":"fixed-request","content":"合成跟进","due_at":"2030-01-01T00:00:00+00:00","status":"pending","due":false}"#
        let client = try api { request in
            methods.append(request.httpMethod!)
            XCTAssertNil(request.value(forHTTPHeaderField:"Authorization"))
            if request.httpMethod == "GET" {
                XCTAssertEqual(request.url?.path,"/api/followups")
                XCTAssertEqual(URLComponents(url:request.url!,resolvingAgainstBaseURL:false)?.queryItems?.first?.value,"canonical")
                return (200,"{\"followups\":[\(pending)]}")
            }
            let payload = try self.body(request)
            XCTAssertEqual(payload["session_id"] as? String,"canonical")
            if request.httpMethod == "POST" {
                XCTAssertEqual(request.url?.path,"/api/followups")
                XCTAssertEqual(payload["content"] as? String,"合成跟进")
                XCTAssertEqual(payload["confirmed"] as? Bool,true)
                XCTAssertEqual(payload["request_id"] as? String,"fixed-request")
                XCTAssertEqual(payload["due_at"] as? String,"2030-01-01T00:00:00Z")
                return (200,pending)
            }
            XCTAssertEqual(request.url?.path,"/api/followups/fup-1")
            let status = payload["status"] as? String ?? ""
            XCTAssertTrue(["done","cancelled"].contains(status))
            return (200,"{\"id\":\"fup-1\",\"session_id\":\"canonical\",\"request_id\":\"fixed-request\",\"content\":\"合成跟进\",\"due_at\":\"2030-01-01T00:00:00+00:00\",\"status\":\"\(status)\",\"due\":false}")
        }
        let due = ISO8601DateFormatter().date(from:"2030-01-01T00:00:00Z")!
        let request = try EchoPendingFollowup(sessionID:"canonical",content:"合成跟进",date:due,origin:"http://127.0.0.1:18787",requestID:"fixed-request",now:Date(timeIntervalSince1970:0))
        _ = try await client.createFollowup(request)
        _ = try await client.createFollowup(request)
        let listed = try await client.followups(sessionID:"canonical")
        let changed = try await client.changeFollowup(id:"fup-1",sessionID:"canonical",status:"done")
        let cancelled = try await client.changeFollowup(id:"fup-1",sessionID:"canonical",status:"cancelled")
        XCTAssertEqual(listed.first?.due,false)
        XCTAssertEqual(changed.status,"done")
        XCTAssertEqual(cancelled.status,"cancelled")
        XCTAssertEqual(methods,["POST","POST","GET","PATCH","PATCH"])
    }
    func testKnownRepeatingFollowupsAndQuietState() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let base = #"{"id":"f","session_id":"s","request_id":"r","content":"跟进","due_at":"2030-01-01T00:00:00Z","status":"pending","due":true"#
        func decode(_ suffix: String) throws -> EchoFollowup { try decoder.decode(EchoFollowup.self,from:Data((base + suffix + "}").utf8)) }
        let legacy = try decode("")
        let daily = try decode(#", "repeat_rule":"daily", "paused":true"#)
        let future = try decode(#", "repeat_rule":"weekly", "quiet":true"#)
        XCTAssertTrue(legacy.supportsNativeTransitions); XCTAssertTrue(legacy.isAvailableNow)
        XCTAssertTrue(daily.supportsNativeTransitions); XCTAssertFalse(daily.isAvailableNow)
        XCTAssertFalse(future.supportsNativeTransitions); XCTAssertFalse(future.isAvailableNow)
        let conflicting = try decode(#", "repeat_rule":"once", "paused":true, "available":true"#)
        XCTAssertFalse(conflicting.isAvailableNow)
        let unavailable = try decode(#", "available":false"#)
        XCTAssertFalse(unavailable.isAvailableNow)
    }
    func testDeliveryPartsAreOrderedAndLegacyMessagesStillDecode() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        func decode(_ text: String) throws -> EchoMessage {try decoder.decode(EchoMessage.self,from:Data(text.utf8))}
        let legacy=try decode(#"{"id":"legacy","role":"assistant","text":"原来的一段"}"#)
        XCTAssertEqual(legacy.displayParts,["原来的一段"]); XCTAssertNil(legacy.deliveryPending)
        let delivered=try decode(#"{"id":"parts","role":"assistant","text":"第一句\n\n第二句","bubbles":["第一句","第二句"],"delivery_pending":true,"delivery_next_ms":800}"#)
        XCTAssertEqual(delivered.displayParts,["第一句","第二句"]); XCTAssertEqual(delivered.deliveryPending,true); XCTAssertEqual(delivered.deliveryNextMs,800)
        let user=try decode(#"{"id":"user","role":"user","text":"原话","bubbles":["不能替换用户原话"]}"#)
        XCTAssertEqual(user.displayParts,["原话"])
    }
    func testTargetedDeliveryStopSendsMessageIDAndRejectsUnconfirmedSuccess() async throws {
        var calls=0
        for (json,accepted,stopped) in [
            (#"{"ok":true,"stopped":true,"message_id":"assistant-current","reason":"stopped"}"#,true,true),
            (#"{"ok":true,"stopped":false,"message_id":"assistant-current","reason":"not_current"}"#,true,false),
            (#"{"ok":true,"stopped":true,"message_id":"other","reason":"stopped"}"#,false,false),
            (#"{"ok":true,"stopped":true,"message_id":"assistant-current","reason":"not_pending"}"#,false,false),
            (#"{"ok":true}"#,false,false)
        ] {
            let client=try api {request in
                calls += 1; XCTAssertEqual(request.httpMethod,"POST"); XCTAssertEqual(request.url?.path,"/api/session/canonical/delivery/stop")
                let body=try self.body(request); XCTAssertEqual(body["message_id"] as? String,"assistant-current"); XCTAssertEqual(body.count,1)
                return (200,json)
            }
            do {let value=try await client.stopDelivery(sessionID:"canonical",messageID:"assistant-current"); XCTAssertTrue(accepted); XCTAssertEqual(value.confirms("assistant-current"),stopped)}
            catch {XCTAssertFalse(accepted)}
        }
        XCTAssertEqual(calls,5)
    }
    func testFeishuRequiresCompleteSnapshotAndReportsTruncation() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        func decode(_ body: String, _ length: Int?, _ extracted: Int?, _ truncated: Bool?, id: String = "reviewed") throws -> EchoPreview {
            var value: [String:Any] = ["ok":true, "preview_id":id, "preview":body]
            if let length { value["length"] = length }; if let extracted { value["extracted_length"] = extracted }; if let truncated { value["truncated"] = truncated }
            return try decoder.decode(EchoPreview.self,from:JSONSerialization.data(withJSONObject:value))
        }
        let body = " 前缀😀e\u{301}\n结尾 "
        let count = body.unicodeScalars.count
        let complete = try decode(body,count,count,false)
        XCTAssertEqual(try complete.requireID(for:"feishu"),"reviewed")
        XCTAssertEqual(complete.preview,body)
        XCTAssertTrue(complete.feishuPreviewScope?.contains("全部") == true)
        let bounded = try decode(String(repeating:"字",count:12000),12000,12001,true)
        XCTAssertEqual(try bounded.requireID(for:"feishu"),"reviewed")
        XCTAssertTrue(bounded.feishuPreviewScope?.contains("其余内容不会接入") == true)
        for bad in [try decode(body,nil,nil,nil), try decode(body,count+1,count+1,false),
                    try decode(body,count,count+1,false), try decode(body,count,count,true),
                    try decode(body,count,count,false,id:""), try decode("  ",2,2,false),
                    try decode(String(repeating:"字",count:12001),12001,12001,false)] {
            XCTAssertThrowsError(try bad.requireID(for:"feishu"))
        }
        // Other connector previews remain governed by their own existing rules.
        XCTAssertEqual(try decode(body,nil,nil,nil).requireID(for:"notion"),"reviewed")
    }
    func testDailyFollowupSendsOccurrenceAndChecksReceipt() async throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let item = try decoder.decode(EchoFollowup.self,from:Data(#"{"id":"f","session_id":"s","request_id":"r","content":"跟进","due_at":"2030-01-01T00:00:00Z","status":"pending","due":true,"repeat_rule":"daily","paused":false}"#.utf8))
        let client = try api { request in
            let payload = try self.body(request)
            XCTAssertEqual(payload["occurrence_at"] as? String,"2030-01-01T00:00:00Z")
            return (200,#"{"id":"f","session_id":"s","request_id":"r","content":"跟进","due_at":"2030-01-02T00:00:00Z","status":"pending","due":false,"repeat_rule":"daily","paused":false,"last_occurrence_at":"2030-01-01T00:00:00+00:00"}"#)
        }
        let result = try await client.changeFollowup(item,status:"done")
        XCTAssertTrue(result.confirmsTransition(from:item,target:"done"))
        XCTAssertFalse(result.confirmsTransition(from:item,target:"paused"))
        let malformed = try decoder.decode(EchoFollowup.self,from:Data(#"{"id":"f","session_id":"s","request_id":"r","content":"跟进","due_at":"2030-01-02T00:00:00Z","status":"pending","due":false,"repeat_rule":"daily"}"#.utf8))
        XCTAssertFalse(malformed.confirmsTransition(from:item,target:"done"))
        XCTAssertFalse(malformed.confirmsTransition(from:item,target:"resumed"))
    }
    func testExtendedFollowupSnapshotKeepsAllParametersAndAdvancedDailyReceipt() async throws {
        let date=Date(timeIntervalSince1970:2_000_000_000)
        let pending=try EchoPendingFollowup(sessionID:"canonical",content:"约好的话题",date:date,origin:"http://127.0.0.1:18787",requestID:"new-daily-request",now:Date(timeIntervalSince1970:0),repeatRule:"daily",timeZone:"Asia/Shanghai",quietStart:"22:00",quietEnd:"08:00",allowContact:true,contactWindowMinutes:30,contactTopic:"只聊约定话题")
        let restored=try JSONDecoder().decode(EchoPendingFollowup.self,from:JSONEncoder().encode(pending))
        var bodies=[Data]()
        let client=try api {request in
            let body=try self.body(request);bodies.append(try JSONSerialization.data(withJSONObject:body,options:.sortedKeys))
            XCTAssertEqual(body["repeat_rule"] as? String,"daily");XCTAssertEqual(body["time_zone"] as? String,"Asia/Shanghai")
            XCTAssertEqual(body["quiet_start"] as? String,"22:00");XCTAssertEqual(body["quiet_end"] as? String,"08:00")
            XCTAssertEqual(body["allow_contact"] as? Bool,true);XCTAssertEqual(body["contact_window_minutes"] as? Int,30);XCTAssertEqual(body["contact_topic"] as? String,"只聊约定话题")
            var value=body;value["id"]="daily-existing";value["status"]="pending";value["due"]=false
            value["created_due_at"]=pending.dueAt;value["due_at"]=ISO8601DateFormatter().string(from:date.addingTimeInterval(86_400));value["last_occurrence_at"]=pending.dueAt
            return (200,String(data:try JSONSerialization.data(withJSONObject:value),encoding:.utf8)!)
        }
        let advanced=try await client.createFollowup(pending);_ = try await client.createFollowup(restored)
        XCTAssertEqual(advanced.id,"daily-existing");XCTAssertTrue(advanced.matches(pending));XCTAssertEqual(bodies.count,2);XCTAssertEqual(bodies[0],bodies[1])
    }
    func testLegacyPendingDoesNotAddTimezoneOrContactParameters() async throws {
        let old=#"{"sessionID":"canonical","content":"旧请求","dueAt":"2030-01-01T00:00:00Z","requestID":"legacy-followup","origin":"http://127.0.0.1:18787"}"#
        let pending=try JSONDecoder().decode(EchoPendingFollowup.self,from:Data(old.utf8))
        for key in ["repeat_rule","time_zone","quiet_start","quiet_end","allow_contact","contact_window_minutes","contact_topic"] {XCTAssertNil(pending.body[key])}
        let turn=try JSONDecoder().decode(EchoPendingTurn.self,from:Data(#"{"requestID":"legacy-chat","sessionID":"canonical","text":"旧原话","origin":"http://127.0.0.1:18787","cancelWanted":false}"#.utf8))
        let client=try api {request in let body=try self.body(request);XCTAssertNil(body["time_zone"]);return(200,#"{"messages":[],"memories":[]}"#)}
        _ = try await client.send(turn)
    }
    func testNewChatTimezoneIsFrozenAcrossRecreation() async throws {
        let turn=EchoPendingTurn(sessionID:"canonical",text:"今天先别问",origin:"http://127.0.0.1:18787",requestID:"zone-bound-request",timeZone:"Asia/Shanghai")
        let restored=try JSONDecoder().decode(EchoPendingTurn.self,from:JSONEncoder().encode(turn))
        let client=try api {request in let body=try self.body(request);XCTAssertEqual(body["time_zone"] as? String,"Asia/Shanghai");XCTAssertEqual(body["request_id"] as? String,"zone-bound-request");return(200,#"{"messages":[],"memories":[]}"#)}
        _ = try await client.send(restored)
    }
    func testInvalidRecurringAndContactParametersFailBeforeNetwork() throws {
        let future=Date().addingTimeInterval(3600)
        for rule in ["weekly","future-rule"] {XCTAssertThrowsError(try EchoPendingFollowup(sessionID:"s",content:"合成",date:future,origin:"http://127.0.0.1:18787",repeatRule:rule))}
        XCTAssertThrowsError(try EchoPendingFollowup(sessionID:"s",content:"合成",date:future,origin:"http://127.0.0.1:18787",timeZone:"invalid/zone"))
        XCTAssertThrowsError(try EchoPendingFollowup(sessionID:"s",content:"合成",date:future,origin:"http://127.0.0.1:18787",quietStart:"22:00",quietEnd:nil))
        XCTAssertThrowsError(try EchoPendingFollowup(sessionID:"s",content:"合成",date:future,origin:"http://127.0.0.1:18787",quietStart:"22:00",quietEnd:"22:00"))
        XCTAssertThrowsError(try EchoPendingFollowup(sessionID:"s",content:"合成",date:future,origin:"http://127.0.0.1:18787",contactWindowMinutes:181))
    }
    func testPassiveReviewRemainsVisibleWithoutContactConsent() throws {
        let decoder=JSONDecoder();decoder.keyDecodingStrategy = .convertFromSnakeCase
        let value=try decoder.decode(EchoFollowup.self,from:Data(#"{"id":"f","session_id":"s","request_id":"r","content":"仍是待办","due_at":"2030-01-01T00:00:00Z","status":"pending","due":true,"available":false,"review_available":true,"allow_contact":false,"contact_eligible":false,"contact_reason":"contact_not_allowed"}"#.utf8))
        XCTAssertTrue(value.isReviewAvailable);XCTAssertFalse(value.isAvailableNow);XCTAssertEqual(value.contactLabel,"未同意主动联系")
    }
    func testBoundaryCASCarriesExplicitConfirmationAndNeverRetriesConflict() async throws {
        var calls=0
        let client=try api {request in
            calls += 1;XCTAssertEqual(request.httpMethod,"PUT");XCTAssertEqual(request.url?.path,"/api/companion-boundary")
            let body=try self.body(request);XCTAssertEqual(body["expected_revision"] as? Int,3);XCTAssertEqual(body["confirmed"] as? Bool,true);XCTAssertEqual(body["mode"] as? String,"paused");XCTAssertTrue(body["until"] is NSNull)
            return (409,#"{"detail":"other client changed boundary","error_code":"boundary_conflict","current_revision":4}"#)
        }
        do {_ = try await client.updateBoundary(sessionID:"canonical",expectedRevision:3,mode:"paused",until:nil,timeZone:"Asia/Shanghai");XCTFail("must surface conflict")}
        catch let error as EchoAPIError {XCTAssertEqual(error.statusCode,409)}
        XCTAssertEqual(calls,1)
    }
    func testBoundaryReceiptAndNextLocalMidnightAcrossDST() async throws {
        let now=ISO8601DateFormatter().date(from:"2026-03-08T06:30:00Z")!
        let midnight=try EchoCompanionBoundary.nextMidnight(timeZone:"America/New_York",now:now)
        XCTAssertEqual(ISO8601DateFormatter().string(from:midnight),"2026-03-09T04:00:00Z")
        let client=try api {_ in (200,#"{"revision":1,"mode":"paused","until":null,"time_zone":"Asia/Shanghai","suppression_revision":1}"#)}
        let value=try await client.updateBoundary(sessionID:"canonical",expectedRevision:0,mode:"paused",until:nil,timeZone:"Asia/Shanghai")
        XCTAssertEqual(value.mode,"paused");XCTAssertEqual(value.revision,1)
    }


    func testMoodDefaultsRequireBothExplicitAxesAndValidateRealDates() throws {
        var draft=EchoMoodDraft(origin:"http://127.0.0.1:18787",sessionID:"s",day:"2026-10-30")
        XCTAssertFalse(draft.canSave);draft.dirty=true;draft.xSelected=true;XCTAssertFalse(draft.canSave)
        draft.ySelected=true;XCTAssertTrue(draft.canSave)
        draft.note=String(repeating:"e\u{301}",count:600);XCTAssertFalse(draft.canSave)
        XCTAssertFalse(EchoMood.validDay("2026-02-30"));XCTAssertTrue(EchoMood.validDay("2028-02-29"))
    }
    func testMoodCRUDRequiresConfirmationExactVersionAndTrueDeleteReceipt() async throws {
        var calls=0
        let entry=#"{"date":"2026-10-30","x":0.3,"y":-0.4,"note":"合成自述","updated_at":"2026-10-30T00:00:01.000001+00:00"}"#
        let client=try api {request in
            calls += 1
            if calls == 1 {XCTAssertEqual(request.httpMethod,"GET");XCTAssertEqual(URLComponents(url:request.url!,resolvingAgainstBaseURL:false)?.queryItems?.first?.name,"session_id");return (200,"{\"moods\":[\(entry)]}")}
            if calls == 2 {let b=try self.body(request);XCTAssertEqual(request.httpMethod,"PUT");XCTAssertEqual(b["confirmed"] as? Bool,true);XCTAssertTrue(b["expected_updated_at"] is NSNull);return (200,entry)}
            if calls == 3 {XCTAssertEqual(try self.body(request)["expected_updated_at"] as? String,"2026-10-30T00:00:01.000001+00:00");return (409,#"{"error_code":"mood_conflict","detail":"已变更"}"#)}
            XCTAssertEqual(request.httpMethod,"DELETE");XCTAssertEqual(URLComponents(url:request.url!,resolvingAgainstBaseURL:false)?.queryItems?.first(where:{$0.name == "expected_updated_at"})?.value,"2026-10-30T00:00:01.000001+00:00");XCTAssertTrue(request.url!.absoluteString.contains("%2B00:00"))
            return (200,#"{"deleted":true}"#)
        }
        _ = try await client.moods(sessionID:"s")
        var d=EchoMoodDraft(origin:client.baseURL.absoluteString,sessionID:"s",day:"2026-10-30");d.x=0.3;d.y = -0.4;d.note="合成自述"
        let saved=try await client.saveMood(sessionID:"s",mutation:.init(kind:.save,draft:d));d.expectedUpdatedAt=saved.updatedAt
        do {_ = try await client.saveMood(sessionID:"s",mutation:.init(kind:.save,draft:d));XCTFail("409 must surface without retry")} catch {XCTAssertEqual((error as? EchoAPIError)?.statusCode,409)}
        XCTAssertEqual(calls,3);try await client.deleteMood(sessionID:"s",mutation:.init(kind:.delete,draft:d));XCTAssertEqual(calls,4)
    }
    func testMoodMismatchedSaveAndUnknownDeleteNeverConfirmSuccess() async throws {
        var d=EchoMoodDraft(origin:"http://127.0.0.1:18787",sessionID:"s",day:"2026-10-30");d.expectedUpdatedAt="2026-10-30T00:00:01Z";d.note="原话"
        var calls=0
        let client=try api {request in calls += 1;return request.httpMethod == "PUT" ? (200,#"{"date":"2026-10-30","x":0,"y":0,"note":"原话","updated_at":"2026-10-30T00:00:01Z"}"#) : (200,#"{"deleted":false}"#)}
        do {_ = try await client.saveMood(sessionID:"s",mutation:.init(kind:.save,draft:d));XCTFail("same old version is not a new save receipt")} catch {}
        do {try await client.deleteMood(sessionID:"s",mutation:.init(kind:.delete,draft:d));XCTFail("false delete must stay uncertain")} catch {}
        XCTAssertEqual(calls,2)
    }
    func testMoodListRejectsDuplicateDaysOrInvalidTokens() async throws {
        for rows in [#"[{"date":"2026-10-30","x":0,"y":0,"note":"","updated_at":"not-a-token"}]"#,
                     #"[{"date":"2026-10-30","x":0,"y":0,"note":"","updated_at":"2026-10-30T00:00:01Z"},{"date":"2026-10-30","x":0,"y":0,"note":"","updated_at":"2026-10-30T00:00:02Z"}]"#] {
            let client=try api {_ in (200,"{\"moods\":\(rows)}")}
            do {_ = try await client.moods(sessionID:"s");XCTFail("invalid list must not replace local state")} catch {}
        }
    }
    func testMoodPendingSnapshotSurvivesRecreationWithoutBecomingMemoryOrChat() throws {
        var d=EchoMoodDraft(origin:"http://127.0.0.1:18787",sessionID:"s",day:"2026-10-30");d.xSelected=true;d.ySelected=true;d.dirty=true;d.note="只留日记";d.pending = .init(kind:.save,draft:d)
        let copy=try JSONDecoder().decode(EchoMoodDraft.self,from:JSONEncoder().encode(d))
        XCTAssertEqual(copy,d);XCTAssertFalse(copy.canSave);XCTAssertNil(copy.expectedUpdatedAt)
        let decoder=JSONDecoder();decoder.keyDecodingStrategy = .convertFromSnakeCase
        let item=try decoder.decode(EchoMood.self,from:Data(#"{"date":"2026-10-30","x":0,"y":0,"note":"只留日记","updated_at":"2026-10-30T00:00:01Z"}"#.utf8))
        XCTAssertTrue(item.chatDraft.contains("只留日记"));XCTAssertTrue(item.chatDraft.contains("不代表一整天"))
    }


    private func ledgerMutation(_ kind: EchoMoodMutation.Kind = .save, expectedToken: String? = nil) throws -> EchoMoodMutation {
        var draft=EchoMoodDraft(origin:"http://127.0.0.1:18787",sessionID:"canonical",day:"2026-10-28")
        draft.x=0.3;draft.y = -0.2;draft.note="保留空格 \\ 与原话🌱";draft.xSelected=true;draft.ySelected=true;draft.dirty=true
        draft.expectedUpdatedAt=expectedToken
        if kind == .delete {draft.expectedUpdatedAt="2026-10-30T00:00:01.000001+00:00"}
        return try EchoMoodMutation(kind:kind,draft:draft).preparedForLedger()
    }
    private func ledgerReceipt(_ mutation: EchoMoodMutation,state: String = "applied",token: String? = "2026-10-30T00:00:02.000001+00:00") throws -> String {
        let nf=state == "not_found"
        let data=try JSONSerialization.data(withJSONObject:["session_id":"canonical","request_id":mutation.requestID!,"operation_sha256":nf ? NSNull() : mutation.operationHash! as Any,"kind":nf ? NSNull() : mutation.kind.rawValue as Any,"state":state,"result_updated_at":token as Any? ?? NSNull()])
        return String(data:data,encoding:.utf8)!
    }
    func testMoodLedgerFrozenIdentityAndLegacyPersistence() throws {
        let value=try ledgerMutation();XCTAssertTrue(value.validLedgerIdentity)
        XCTAssertEqual(value.operationHash?.count,64);XCTAssertThrowsError(try value.preparedForLedger())
        let raw=value.operationJSON!,saved=try JSONEncoder().encode(value),restored=try JSONDecoder().decode(EchoMoodMutation.self,from:saved)
        XCTAssertEqual(restored,value);XCTAssertEqual(restored.operationJSON,raw)
        var object=try JSONSerialization.jsonObject(with:saved) as! [String:Any];object.removeValue(forKey:"requestID");object.removeValue(forKey:"operationJSON")
        let legacy=try JSONDecoder().decode(EchoMoodMutation.self,from:JSONSerialization.data(withJSONObject:object));XCTAssertFalse(legacy.hasLedgerIdentity)
        var variant=try JSONSerialization.jsonObject(with:saved) as! [String:Any];variant["operationJSON"]=raw+"\n"
        let whitespace=try JSONDecoder().decode(EchoMoodMutation.self,from:JSONSerialization.data(withJSONObject:variant))
        XCTAssertTrue(whitespace.validLedgerIdentity);XCTAssertFalse(whitespace.operationHash == value.operationHash)
        var draft=EchoMoodDraft(origin:"x",sessionID:"s",day:"2026-10-28");draft.pending=legacy
        let d=try JSONDecoder().decode(EchoMoodDraft.self,from:JSONEncoder().encode(draft));XCTAssertNil(d.cancelRequested);XCTAssertNil(d.operationState)
        let deletion=try ledgerMutation(.delete),deleteBody=try JSONSerialization.jsonObject(with:Data(deletion.operationJSON!.utf8)) as! [String:Any]
        XCTAssertEqual(Set(deleteBody.keys),["kind","date","expected_updated_at"]);XCTAssertTrue(deletion.validLedgerIdentity)
    }
    func testMoodLedgerApplyRetriesPreserveExactJSONAndNeverUseLegacyAPI() async throws {
        let mutation=try ledgerMutation();var raws=[String]();let receipt=try ledgerReceipt(mutation)
        let client=try api {req in
            XCTAssertEqual(req.url?.path,"/api/mood-operations");XCTAssertEqual(req.httpMethod,"POST")
            let body=try self.body(req);XCTAssertEqual(Set(body.keys),["session_id","request_id","operation_json","confirmed"])
            XCTAssertEqual(body["request_id"] as? String,mutation.requestID);XCTAssertEqual(body["confirmed"] as? Bool,true)
            raws.append(body["operation_json"] as! String);return (200,receipt)
        }
        _=try await client.applyMoodOperation(sessionID:"canonical",mutation:mutation);_=try await client.applyMoodOperation(sessionID:"canonical",mutation:mutation)
        XCTAssertEqual(raws,[mutation.operationJSON!,mutation.operationJSON!])
        do {_=try await client.saveMood(sessionID:"canonical",mutation:mutation);XCTFail("must not downgrade")} catch {}
        do {try await client.deleteMood(sessionID:"canonical",mutation:try ledgerMutation(.delete));XCTFail("must not downgrade")} catch {}
        XCTAssertEqual(raws.count,2)
    }
    func testMoodLedgerMissingNullableMismatchedOrUnknownReceiptsStayUnknown() async throws {
        let mutation=try ledgerMutation();let valid=try ledgerReceipt(mutation)
        var base=try JSONSerialization.jsonObject(with:Data(valid.utf8)) as! [String:Any]
        var extra=base;extra["extra_receipt_field"]="must reject"
        let extraJSON=String(data:try JSONSerialization.data(withJSONObject:extra),encoding:.utf8)!,extraClient=try api {_ in (200,extraJSON)}
        do {_=try await extraClient.moodOperation(sessionID:"canonical",mutation:mutation);XCTFail("extra field accepted")} catch {}
        for key in ["session_id","request_id","operation_sha256","kind","state","result_updated_at"] {
            var bad=base;bad.removeValue(forKey:key);let json=String(data:try JSONSerialization.data(withJSONObject:bad),encoding:.utf8)!
            let client=try api {_ in (200,json)}
            do {_=try await client.moodOperation(sessionID:"canonical",mutation:mutation);XCTFail("missing field accepted")} catch {}
        }
        for (key,value) in [("session_id","other"),("request_id","other"),("operation_sha256",String(repeating:"0",count:64)),("kind","delete"),("state","running"),("result_updated_at","not-a-token")] {
            var bad=base;bad[key]=value;let json=String(data:try JSONSerialization.data(withJSONObject:bad),encoding:.utf8)!
            let client=try api {_ in (200,json)}
            do {_=try await client.moodOperation(sessionID:"canonical",mutation:mutation);XCTFail("mismatch accepted")} catch {}
        }
        base["state"]="not_found";base["operation_sha256"]=NSNull();base["kind"]=NSNull();base["result_updated_at"]=NSNull()
        let nf=String(data:try JSONSerialization.data(withJSONObject:base),encoding:.utf8)!,client=try api {req in XCTAssertEqual(req.httpMethod,"GET");return (200,nf)}
        let result=try await client.moodOperation(sessionID:"canonical",mutation:mutation);XCTAssertEqual(result.state,"not_found")
    }
    func testMoodLedgerCancelSendsMetadataOnlyAndAppliedIsNotRollback() async throws {
        let mutation=try ledgerMutation(),receipt=try ledgerReceipt(mutation)
        let client=try api {req in
            XCTAssertEqual(req.url?.path,"/api/mood-operations/\(mutation.requestID!)/cancel");XCTAssertEqual(req.httpMethod,"POST")
            let body=try self.body(req);XCTAssertEqual(Set(body.keys),["session_id","operation_sha256","kind","confirmed"])
            XCTAssertEqual(body["operation_sha256"] as? String,mutation.operationHash);XCTAssertEqual(body["kind"] as? String,"save")
            XCTAssertNil(body["operation_json"]);XCTAssertNil(body["note"]);return (200,receipt)
        }
        let result=try await client.cancelMoodOperation(sessionID:"canonical",mutation:mutation);XCTAssertEqual(result.state,"applied")
    }
    func testMoodLedgerTerminalConflictAndDeleteTokensAreChecked() async throws {
        let deletion=try ledgerMutation(.delete)
        for state in ["conflict","cancelled"] {
            let json=try ledgerReceipt(deletion,state:state,token:nil),client=try api {_ in (200,json)}
            let result=try await client.applyMoodOperation(sessionID:"canonical",mutation:deletion);XCTAssertEqual(result.state,state)
        }
        let wrong=try ledgerReceipt(deletion),client=try api {_ in (200,wrong)}
        do {_=try await client.applyMoodOperation(sessionID:"canonical",mutation:deletion);XCTFail("delete old token required")} catch {}
        let correct=try ledgerReceipt(deletion,token:deletion.expectedUpdatedAt),good=try api {_ in (200,correct)}
        let result=try await good.applyMoodOperation(sessionID:"canonical",mutation:deletion)
        XCTAssertEqual(result.resultUpdatedAt,deletion.expectedUpdatedAt)
        let prior="2026-10-30T00:00:01.000001+00:00",save=try ledgerMutation(expectedToken:prior)
        let unchanged=try ledgerReceipt(save,token:prior),unchangedClient=try api {_ in (200,unchanged)}
        do {_=try await unchangedClient.applyMoodOperation(sessionID:"canonical",mutation:save);XCTFail("applied save must issue a different token")} catch {}
    }

    private func speechMessage(_ id: String = "speech-1",role: String = "assistant",text: String = "正文",parts: [String]? = nil,pending: Bool? = nil) throws -> EchoMessage {
        var obj:[String:Any] = ["id":id,"role":role,"text":text]
        if let parts {obj["bubbles"]=parts};if let pending {obj["delivery_pending"]=pending}
        let decoder=JSONDecoder();decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(EchoMessage.self,from:JSONSerialization.data(withJSONObject:obj))
    }
    func testSpeechOnlyExplicitCompleteVisibleAssistantRepliesAreEligible() throws {
        let complete=try speechMessage(),pending=try speechMessage(text:"未显示后段",parts:["已显示"],pending:true),user=try speechMessage(role:"user"),empty=try speechMessage(text:"   ")
        XCTAssertNotNil(EchoSpeechTarget.visibleReply(complete,origin:"local",sessionID:"one",foreground:true))
        for message in [pending,user,empty] {XCTAssertNil(EchoSpeechTarget.visibleReply(message,origin:"local",sessionID:"one",foreground:true))}
        XCTAssertNil(EchoSpeechTarget.visibleReply(complete,origin:"",sessionID:"one",foreground:true))
        XCTAssertNil(EchoSpeechTarget.visibleReply(complete,origin:"local",sessionID:nil,foreground:true))
        XCTAssertNil(EchoSpeechTarget.visibleReply(complete,origin:"local",sessionID:"one",foreground:false))
        var state=EchoSpeechState();XCTAssertFalse(state.reconcile(messages:[complete],origin:"local",sessionID:"one",foreground:true));XCTAssertNil(state.active)
    }
    func testSpeechLegacyPartsNeverFallBackToHiddenFullText() throws {
        let legacy=try speechMessage(text:"已见正文，隐藏后段不能读",parts:["已见正文"],pending:nil)
        let target=EchoSpeechTarget.visibleReply(legacy,origin:"local",sessionID:"one",foreground:true)!
        XCTAssertEqual(target.speechText,"已见正文");XCTAssertFalse(target.speechText.contains("隐藏后段"))
        let all=try speechMessage(text:"隐藏",parts:["**第一段** [表情：高兴]","[第二段](https://example.invalid/private)"])
        let body=EchoSpeechTarget.visibleReply(all,origin:"local",sessionID:"one",foreground:true)!.speechText
        XCTAssertTrue(body.contains("第一段"));XCTAssertTrue(body.contains("第二段"));XCTAssertFalse(body.contains("https://"));XCTAssertFalse(body.contains("表情"));XCTAssertFalse(body.contains("隐藏"))
    }
    func testSpeechTokenCallbacksCannotClearOrStartNewPlayback() throws {
        let target=EchoSpeechTarget.visibleReply(try speechMessage(),origin:"local",sessionID:"one",foreground:true)!
        var state=EchoSpeechState();let old=state.begin(target);XCTAssertEqual(old.phase,.preparing)
        let new=state.begin(target);XCTAssertFalse(old.token == new.token)
        for event in [EchoSpeechEvent.started(old.token),.finished(old.token),.cancelled(old.token),.failed(old.token)] {XCTAssertFalse(state.receive(event));XCTAssertEqual(state.active?.token,new.token)}
        XCTAssertTrue(state.receive(.started(new.token)));XCTAssertEqual(state.active?.phase,.speaking)
        XCTAssertTrue(state.receive(.finished(new.token)));XCTAssertNil(state.active)
        XCTAssertFalse(state.receive(.started(new.token)));XCTAssertNil(state.active)
    }
    func testSpeechReconcileStopsOnScopeVisibilityOrAnyContentChange() throws {
        let message=try speechMessage(text:"raw",parts:["可见"]),target=EchoSpeechTarget.visibleReply(message,origin:"a",sessionID:"one",foreground:true)!
        let cases:[([EchoMessage],String,String?,Bool)]=[
            ([],"a","one",true),([message],"b","one",true),([message],"a","two",true),([message],"a",nil,true),([message],"a","one",false),
            ([try speechMessage(text:"raw changed",parts:["可见"])],"a","one",true),([try speechMessage(text:"raw",parts:["内容变化"])],"a","one",true),
            ([try speechMessage(role:"user",text:"raw",parts:["可见"])],"a","one",true),([try speechMessage(text:"raw",parts:["可见"],pending:true)],"a","one",true)]
        for (messages,origin,sid,foreground) in cases {
            var state=EchoSpeechState();let request=state.begin(target)
            XCTAssertTrue(state.reconcile(messages:messages,origin:origin,sessionID:sid,foreground:foreground));XCTAssertNil(state.active)
            XCTAssertFalse(state.receive(.started(request.token)))
            XCTAssertFalse(state.reconcile(messages:[message],origin:"a",sessionID:"one",foreground:true));XCTAssertNil(state.active)
        }
    }
    func testSpeechUnchangedRefreshKeepsPlaybackAndStopNeverResumesIt() throws {
        let message=try speechMessage(),target=EchoSpeechTarget.visibleReply(message,origin:"a",sessionID:"one",foreground:true)!
        var state=EchoSpeechState();let request=state.begin(target)
        XCTAssertFalse(state.reconcile(messages:[message],origin:"a",sessionID:"one",foreground:true));XCTAssertEqual(state.active?.token,request.token)
        XCTAssertEqual(state.invalidate(),request.token);XCTAssertFalse(state.receive(.cancelled(request.token)))
        XCTAssertFalse(state.reconcile(messages:[message],origin:"a",sessionID:"one",foreground:true));XCTAssertNil(state.active)
    }

    private func pairedJSON(instance: String = "service-one",device: String = "device-one",conversation: String = "canonical") -> String {
        "{\"service_instance_id\":\"\(instance)\",\"conversation_id\":\"\(conversation)\",\"scope\":\"personal_core\",\"local_actions_allowed\":false,\"device\":{\"id\":\"\(device)\",\"label\":\"合成手机\",\"created_at\":\"2026-10-01T00:00:00+00:00\",\"expires_at\":\"2099-10-01T00:00:00+00:00\",\"revoked_at\":null}}"
    }
    private func pairedProfile() throws -> EchoDeviceProfile {
        let decoder=JSONDecoder();decoder.keyDecodingStrategy = .convertFromSnakeCase
        return EchoDeviceProfile(origin:"https://paired.example.invalid",receipt:try decoder.decode(EchoPairedDevice.self,from:Data(pairedJSON().utf8)))
    }
    private var syntheticDeviceToken: String {"echo_pair_"+String(repeating:"A",count:43)}
    func testDeviceCredentialShapeAndNamespaceNeverEncodeBearer() throws {
        XCTAssertTrue(EchoDeviceAuthorization.validToken(syntheticDeviceToken))
        for invalid in ["sk-model-key",syntheticDeviceToken+"\n",syntheticDeviceToken+"A","echo_pair_"+String(repeating:"A",count:42),"echo_pair_"+String(repeating:"é",count:43)] {XCTAssertFalse(EchoDeviceAuthorization.validToken(invalid))}
        let p=try pairedProfile(),data=try JSONEncoder().encode(p),text=String(data:data,encoding:.utf8)!
        XCTAssertFalse(text.contains(syntheticDeviceToken));XCTAssertFalse(text.contains("Bearer"))
        let restored=try JSONDecoder().decode(EchoDeviceProfile.self,from:data);XCTAssertEqual(p,restored)
        let decoder=JSONDecoder();decoder.keyDecodingStrategy = .convertFromSnakeCase
        let receipt=try decoder.decode(EchoPairedDevice.self,from:Data(pairedJSON().utf8)),other=EchoDeviceProfile(origin:p.origin,receipt:receipt)
        XCTAssertFalse(p.namespace == other.namespace);XCTAssertTrue(p.namespace.contains("service-one"));XCTAssertTrue(p.namespace.contains("device-one"))
    }
    func testPairedVerifyIsOnlyUnboundRequestAndNeverLeaksTokenToURL() async throws {
        let token=try EchoDeviceAuthorization(token:syntheticDeviceToken);var requests=[URLRequest]()
        let configuration=URLSessionConfiguration.ephemeral;configuration.protocolClasses=[MockProtocol.self]
        MockProtocol.handler={req in requests.append(req);XCTAssertEqual(req.value(forHTTPHeaderField:"Authorization"),"Bearer "+self.syntheticDeviceToken);XCTAssertNil(req.value(forHTTPHeaderField:"X-Echo-Service-Instance"));XCTAssertNil(req.url?.query);XCTAssertNil(req.httpBody);return (200,self.pairedJSON())}
        let api=try EchoAPI(baseURL:"https://paired.example.invalid",session:URLSession(configuration:configuration),authorization:token)
        let paired=try await api.pairedDevice();XCTAssertTrue(paired.isValid)
        do {_=try await api.conversation();XCTFail("must verify identity before private request")} catch {}
        XCTAssertEqual(requests.count,1);XCTAssertEqual(requests.first?.url?.path,"/api/paired-device")
        XCTAssertThrowsError(try EchoAPI(baseURL:"http://127.0.0.1:18787",authorization:token))
    }
    func testRemoteRequestsRequireBearerAndBindVerifiedInstance() async throws {
        let profile=try pairedProfile(),authorization=try EchoDeviceAuthorization(token:syntheticDeviceToken,profile:profile),config=URLSessionConfiguration.ephemeral;config.protocolClasses=[MockProtocol.self]
        var count=0
        MockProtocol.handler={request in count += 1;XCTAssertEqual(request.value(forHTTPHeaderField:"Authorization"),"Bearer "+self.syntheticDeviceToken);XCTAssertEqual(request.value(forHTTPHeaderField:"X-Echo-Service-Instance"),profile.serviceInstanceID);return (200,self.snapshot)}
        let api=try EchoAPI(baseURL:profile.origin,session:URLSession(configuration:config),authorization:authorization)
        XCTAssertEqual(api.storageNamespace,profile.namespace);_=try await api.conversation()
        do {_=try await api.actions(sessionID:"canonical");XCTFail("actions prohibited")} catch {}
        do {_=try await api.previewSource("feishu",target:"https://example.invalid");XCTFail("CLI read prohibited")} catch {}
        let anonymous=try EchoAPI(baseURL:profile.origin,session:URLSession(configuration:config))
        do {_=try await anonymous.conversation();XCTFail("must not anonymously request remote service")} catch {}
        XCTAssertEqual(count,1)
    }
    private final class AuthenticationCapture: @unchecked Sendable {
        private let lock=NSLock();private var entries=[EchoAuthenticationFailure]()
        func append(_ value: EchoAuthenticationFailure) {lock.lock();entries.append(value);lock.unlock()}
        var values: [EchoAuthenticationFailure] {lock.lock();defer {lock.unlock()};return entries}
    }
    func testDevice401InvalidatesOnlyBoundClientAndNeverRetries() async throws {
        let profile=try pairedProfile(),authorization=try EchoDeviceAuthorization(token:syntheticDeviceToken,profile:profile),config=URLSessionConfiguration.ephemeral;config.protocolClasses=[MockProtocol.self]
        var count=0;let failures=AuthenticationCapture()
        MockProtocol.handler={_ in count += 1;return (401,#"{"error_code":"paired_authentication_required","detail":"设备许可不可用"}"#)}
        let api=try EchoAPI(baseURL:profile.origin,session:URLSession(configuration:config),authorization:authorization)
        api.setAuthenticationFailureHandler {failure in failures.append(failure)}
        for _ in 0..<2 {do {_=try await api.conversation();XCTFail("invalid device cannot read")} catch {}}
        XCTAssertEqual(count,1);XCTAssertEqual(failures.values.count,1);XCTAssertEqual(failures.values.first?.profile,profile)
        let newer=try EchoDeviceAuthorization(token:syntheticDeviceToken,profile:try pairedProfile());XCTAssertNoThrow(try newer.header())
    }
    func testDevice403NetworkOrMissingInstanceDoesNotDiscardCredential() async throws {
        for (status,code) in [(403,"paired_operation_forbidden"),(503,"unavailable"),(428,"service_instance_required")] {
            let profile=try pairedProfile(),authorization=try EchoDeviceAuthorization(token:syntheticDeviceToken,profile:profile),config=URLSessionConfiguration.ephemeral;config.protocolClasses=[MockProtocol.self]
            MockProtocol.handler={_ in (status,"{\"error_code\":\"\(code)\"}")}
            let api=try EchoAPI(baseURL:profile.origin,session:URLSession(configuration:config),authorization:authorization)
            do {_=try await api.conversation();XCTFail("failure expected")} catch {XCTAssertEqual((error as? EchoAPIError)?.statusCode,status)}
            XCTAssertNoThrow(try authorization.header())
        }
    }
    func testPairedReceiptRejectsUnknownScopeExpiredRevokedAndWrongIdentity() async throws {
        let valid=pairedJSON(),profile=try pairedProfile()
        for bad in [valid.replacingOccurrences(of:"personal_core",with:"owner_admin"),valid.replacingOccurrences(of:"\"local_actions_allowed\":false",with:"\"local_actions_allowed\":true"),valid.replacingOccurrences(of:"2099-10-01",with:"2000-10-01"),valid.replacingOccurrences(of:"2026-10-01T00:00:00+00:00",with:"2100-10-01T00:00:00+00:00"),valid.replacingOccurrences(of:"2099-10-01T00:00:00+00:00",with:"2099-10-01T08:00:00+08:00"),valid.replacingOccurrences(of:"合成手机",with:""),valid.replacingOccurrences(of:"\"revoked_at\":null",with:"\"revoked_at\":\"2026-10-01T00:00:00+00:00\""),valid.replacingOccurrences(of:",\"revoked_at\":null",with:""),pairedJSON(instance:"other"),pairedJSON(device:"other"),pairedJSON(conversation:"other")] {
            let config=URLSessionConfiguration.ephemeral;config.protocolClasses=[MockProtocol.self];MockProtocol.handler={_ in (200,bad)}
            let api=try EchoAPI(baseURL:profile.origin,session:URLSession(configuration:config),authorization:EchoDeviceAuthorization(token:syntheticDeviceToken,profile:profile))
            do {_=try await api.pairedDevice();XCTFail("bad receipt must not activate device")} catch {}
        }
    }
    private func changesJSON(cursor: String = "cursor_0",reset: Bool = false,domains: [String] = [],instance: String = "service-one",conversation: String = "canonical",reason: String? = nil) -> String {
        let value:[String:Any]=["service_instance_id":instance,"conversation_id":conversation,"cursor":cursor,"reset_required":reset,"domains":domains,"reset_reason":reason as Any? ?? NSNull()]
        return String(data:try! JSONSerialization.data(withJSONObject:value),encoding:.utf8)!
    }
    func testChangesCursorIsOpaqueBoundedAndRejectedBeforeTransport() async throws {
        for text in ["",String(repeating:"A",count:2049),"cursor+body","secret=abc","中文","cursor\n"] {XCTAssertFalse(EchoConversationChanges.validCursor(text))}
        XCTAssertTrue(EchoConversationChanges.validCursor(String(repeating:"A",count:2048)))
        var count=0
        let api=try self.api {request in count += 1;XCTAssertEqual(request.url?.path,"/api/conversation/changes");XCTAssertEqual(URLComponents(url:request.url!,resolvingAgainstBaseURL:false)?.queryItems?.first?.value,"opaque_A-9");return (200,self.changesJSON(cursor:"opaque_A-9"))}
        for text in ["", "bad+cursor",String(repeating:"x",count:2049)] {do {_=try await api.conversationChanges(after:text);XCTFail("invalid cursor sent")} catch {}}
        let value=try await api.conversationChanges(after:"opaque_A-9");XCTAssertEqual(value.cursor,"opaque_A-9");XCTAssertEqual(count,1)
    }
    func testChangesDTORequiresFullResetAndPreservesUnknownDomains() throws {
        let decoder=JSONDecoder();decoder.keyDecodingStrategy = .convertFromSnakeCase
        let normal=try decoder.decode(EchoConversationChanges.self,from:Data(changesJSON().utf8));XCTAssertTrue(normal.isValid)
        let full=try decoder.decode(EchoConversationChanges.self,from:Data(changesJSON(reset:true,domains:Array(EchoConversationChanges.knownDomains),reason:"initial").utf8));XCTAssertTrue(full.isValid)
        for json in [changesJSON(reset:true,domains:["messages"],reason:"initial"),changesJSON(domains:["messages","messages"]),changesJSON(reset:true,domains:Array(EchoConversationChanges.knownDomains),reason:"unknown")] {XCTAssertFalse(try decoder.decode(EchoConversationChanges.self,from:Data(json.utf8)).isValid)}
        let future=try decoder.decode(EchoConversationChanges.self,from:Data(changesJSON(domains:["future_domain"]).utf8));XCTAssertTrue(future.isValid);XCTAssertEqual(future.domains,["future_domain"])
    }
    func testChangesReceiptCannotRebindPairedCanonicalOrInstance() async throws {
        let profile=try pairedProfile(),config=URLSessionConfiguration.ephemeral;config.protocolClasses=[MockProtocol.self]
        for wrong in [changesJSON(instance:"other"),changesJSON(conversation:"other")] {
            MockProtocol.handler={_ in (200,wrong)}
            let api=try EchoAPI(baseURL:profile.origin,session:URLSession(configuration:config),authorization:EchoDeviceAuthorization(token:syntheticDeviceToken,profile:profile))
            do {_=try await api.conversationChanges();XCTFail("wrong identity must not rebind")} catch {}
        }
    }
    func testChangePollIsSingleFlightAndCancellationDoesNotReleaseItEarly() throws {
        var state=EchoChangePollState();let first=state.begin(scope:"one")!
        XCTAssertNil(state.begin(scope:"one"));state.interrupt();XCTAssertFalse(state.accepts(first));XCTAssertNil(state.begin(scope:"one"));XCTAssertFalse(state.commit(first,cursor:"late"))
        state.finish(first);let second=state.begin(scope:"one")!;XCTAssertTrue(state.accepts(second));XCTAssertTrue(state.commit(second,cursor:"first_read"));state.finish(second)
        XCTAssertEqual(state.cursor,"first_read")
    }
    func testChangePollBlockedAndFailedReadsCannotAdvanceCursor() throws {
        var state=EchoChangePollState();let first=state.begin(scope:"same")!;state.discovered(first);XCTAssertTrue(state.pending);XCTAssertNil(state.cursor)
        state.failed(first);XCTAssertEqual(state.delaySeconds,30);state.discovered(first);state.failed(first);XCTAssertEqual(state.delaySeconds,60);state.failed(first);XCTAssertEqual(state.delaySeconds,60);state.finish(first)
        let next=state.begin(scope:"same")!;XCTAssertTrue(state.commit(next,cursor:"verified_batch"));state.finish(next);XCTAssertFalse(state.pending);XCTAssertEqual(state.delaySeconds,15)
        let invalid=state.begin(scope:"same")!;XCTAssertFalse(state.commit(invalid,cursor:"bad+cursor"));state.finish(invalid);XCTAssertEqual(state.cursor,"verified_batch")
    }
    func testChangePollIdentitySwitchKeepsLateResultOutAndDoesNotMigrateCursor() throws {
        var state=EchoChangePollState();let old=state.begin(scope:"origin_instance_device_genA")!;XCTAssertTrue(state.commit(old,cursor:"cursor_old"));state.finish(old)
        let pending=state.begin(scope:state.scope)!;state.bind("origin_instance_device_genB");XCTAssertNil(state.cursor);XCTAssertFalse(state.commit(pending,cursor:"late"));state.failed(pending);XCTAssertEqual(state.failures,0);state.finish(pending)
        let new=state.begin(scope:state.scope)!;XCTAssertNil(new.after);XCTAssertTrue(state.commit(new,cursor:"cursor_new"));state.finish(new)
    }

    func testChangesFullSnapshotDistinguishesLegitimateNullFromMissingCollections() async throws {
        for context in ["null",#"{"sources":[]}"#] {
            let json="{\"session\":{\"id\":\"canonical\"},\"messages\":[],\"memories\":[],\"context\":\(context)}"
            let api=try self.api {_ in (200,json)}
            let value=try await api.changeConversationSnapshot();XCTAssertEqual(value.session.id,"canonical");XCTAssertTrue(value.messages.isEmpty)
        }
        for context in ["",#","context":{}"#,#","context":{"sources":null}"#,#","context":[]"#] {
            let json="{\"session\":{\"id\":\"canonical\"},\"messages\":[],\"memories\":[]\(context)}"
            let api=try self.api {_ in (200,json)}
            do {_=try await api.changeConversationSnapshot();XCTFail("missing collection cannot imply deletion")} catch {}
        }
    }
    func testChangesRequiresExplicitNullableResetReason() throws {
        let decoder=JSONDecoder();decoder.keyDecodingStrategy = .convertFromSnakeCase
        let malformed=#"{"service_instance_id":"svc","conversation_id":"one","cursor":"cursor","reset_required":false,"domains":[]}"#
        XCTAssertThrowsError(try decoder.decode(EchoConversationChanges.self,from:Data(malformed.utf8)))
    }

}

extension EchoCoreTests {
    func testRefreshNoticeDistinguishesOfflineUnknownAndUnsupported() {
        XCTAssertEqual(EchoChangeNoticeKind.resolve(status:.offline,capabilitiesKnown:true,capabilityReadFailed:false,changesWaiting:true),.offline)
        XCTAssertEqual(EchoChangeNoticeKind.resolve(status:.idle,capabilitiesKnown:false,capabilityReadFailed:true,changesWaiting:false),.capabilitiesUnknown)
        XCTAssertEqual(EchoChangeNoticeKind.resolve(status:.unsupported,capabilitiesKnown:false,capabilityReadFailed:false,changesWaiting:false),.none)
        XCTAssertEqual(EchoChangeNoticeKind.resolve(status:.unsupported,capabilitiesKnown:true,capabilityReadFailed:false,changesWaiting:false),.unsupported)
    }
    private func archiveProfile() throws -> EchoDeviceProfile {
        let d=JSONDecoder();d.keyDecodingStrategy = .convertFromSnakeCase
        let receipt=try d.decode(EchoPairedDevice.self,from:Data(#"{"service_instance_id":"archive-instance","conversation_id":"archive-canonical","scope":"personal_core","local_actions_allowed":false,"device":{"id":"archive-device","label":"合成本机草稿","created_at":"2026-01-01T00:00:00Z","expires_at":"2099-01-01T00:00:00Z","revoked_at":null}}"#.utf8))
        return EchoDeviceProfile(origin:"https://archive.invalid",receipt:receipt)
    }
    func testLocalArchiveIsReadOnlyAndDoesNotExposeReplayIdentity() throws {
        let suite="echo.synthetic.archive."+UUID().uuidString,d=UserDefaults(suiteName:suite)!
        defer {d.removePersistentDomain(forName:suite)}
        let profile=try archiveProfile(),encoded=Data(profile.namespace.utf8).base64EncodedString()
        d.set("未发送的原话",forKey:"echo.native.draft.v1."+encoded)
        let pending=EchoPendingTurn(sessionID:profile.conversationID,text:"原请求文字",origin:profile.namespace)
        d.set(try JSONEncoder().encode(pending),forKey:"echo.native.pending-turn.v1."+encoded)
        d.set(Data("bad".utf8),forKey:"echo.native.followup-draft.v1."+encoded)
        d.set("不属于本身份的文字",forKey:"echo.native.draft.v1.other")
        let before=d.dictionaryRepresentation() as NSDictionary
        let archive=EchoLocalDraftArchive.read(defaults:d,profile:profile)
        XCTAssertEqual(archive.entries.map(\.text),["未发送的原话","原请求文字"])
        XCTAssertEqual(archive.unreadableCount,1)
        XCTAssertFalse(archive.entries.map { $0.text+$0.detail }.joined().contains(pending.requestID))
        XCTAssertEqual(before,d.dictionaryRepresentation() as NSDictionary)
    }
    func testLocalArchiveRejectsForeignMoodAndPreservesSelectedPositions() throws {
        let suite="echo.synthetic.archive.mood."+UUID().uuidString,d=UserDefaults(suiteName:suite)!
        defer {d.removePersistentDomain(forName:suite)}
        let profile=try archiveProfile(),prefix="echo.native.mood-draft.v1."+Data((profile.namespace+"|"+profile.conversationID).utf8).base64EncodedString()+"."
        var good=EchoMoodDraft(origin:profile.namespace,sessionID:profile.conversationID,day:"2026-10-28");good.dirty=true;good.xSelected=true;good.note="本人记下的位置"
        d.set(try JSONEncoder().encode(good),forKey:prefix+good.day)
        var foreign=EchoMoodDraft(origin:profile.namespace,sessionID:"another",day:"2026-10-29");foreign.dirty=true;foreign.note="不能读取的身份"
        d.set(try JSONEncoder().encode(foreign),forKey:prefix+foreign.day)
        d.set(try JSONEncoder().encode(good),forKey:prefix+"not-a-date")
        let archive=EchoLocalDraftArchive.read(defaults:d,profile:profile)
        XCTAssertEqual(archive.entries.count,1);XCTAssertEqual(archive.unreadableCount,2)
        XCTAssertTrue(archive.entries.first!.text.contains("精力：未选择"))
        XCTAssertFalse(archive.entries.first!.text.contains(foreign.note))
    }
}

@main struct ContractRunner {
    static func main() async {
        let suite = EchoCoreTests()
        let cases: [(String, () async throws -> Void)] = [
            ("testRefreshNoticeDistinguishesOfflineUnknownAndUnsupported", {suite.testRefreshNoticeDistinguishesOfflineUnknownAndUnsupported()}),
            ("testLocalArchiveIsReadOnlyAndDoesNotExposeReplayIdentity", {try suite.testLocalArchiveIsReadOnlyAndDoesNotExposeReplayIdentity()}),
            ("testLocalArchiveRejectsForeignMoodAndPreservesSelectedPositions", {try suite.testLocalArchiveRejectsForeignMoodAndPreservesSelectedPositions()}),
            ("testChangesFullSnapshotDistinguishesLegitimateNullFromMissingCollections", {try await suite.testChangesFullSnapshotDistinguishesLegitimateNullFromMissingCollections()}),
            ("testChangesRequiresExplicitNullableResetReason", {try suite.testChangesRequiresExplicitNullableResetReason()}),
            ("testChangesCursorIsOpaqueBoundedAndRejectedBeforeTransport", {try await suite.testChangesCursorIsOpaqueBoundedAndRejectedBeforeTransport()}),
            ("testChangesDTORequiresFullResetAndPreservesUnknownDomains", {try suite.testChangesDTORequiresFullResetAndPreservesUnknownDomains()}),
            ("testChangesReceiptCannotRebindPairedCanonicalOrInstance", {try await suite.testChangesReceiptCannotRebindPairedCanonicalOrInstance()}),
            ("testChangePollIsSingleFlightAndCancellationDoesNotReleaseItEarly", {try suite.testChangePollIsSingleFlightAndCancellationDoesNotReleaseItEarly()}),
            ("testChangePollBlockedAndFailedReadsCannotAdvanceCursor", {try suite.testChangePollBlockedAndFailedReadsCannotAdvanceCursor()}),
            ("testChangePollIdentitySwitchKeepsLateResultOutAndDoesNotMigrateCursor", {try suite.testChangePollIdentitySwitchKeepsLateResultOutAndDoesNotMigrateCursor()}),
            ("testDeviceCredentialShapeAndNamespaceNeverEncodeBearer", { try suite.testDeviceCredentialShapeAndNamespaceNeverEncodeBearer() }),
            ("testPairedVerifyIsOnlyUnboundRequestAndNeverLeaksTokenToURL", { try await suite.testPairedVerifyIsOnlyUnboundRequestAndNeverLeaksTokenToURL() }),
            ("testRemoteRequestsRequireBearerAndBindVerifiedInstance", { try await suite.testRemoteRequestsRequireBearerAndBindVerifiedInstance() }),
            ("testDevice401InvalidatesOnlyBoundClientAndNeverRetries", { try await suite.testDevice401InvalidatesOnlyBoundClientAndNeverRetries() }),
            ("testDevice403NetworkOrMissingInstanceDoesNotDiscardCredential", { try await suite.testDevice403NetworkOrMissingInstanceDoesNotDiscardCredential() }),
            ("testPairedReceiptRejectsUnknownScopeExpiredRevokedAndWrongIdentity", { try await suite.testPairedReceiptRejectsUnknownScopeExpiredRevokedAndWrongIdentity() }),

            ("testSpeechOnlyExplicitCompleteVisibleAssistantRepliesAreEligible", { try suite.testSpeechOnlyExplicitCompleteVisibleAssistantRepliesAreEligible() }),
            ("testSpeechLegacyPartsNeverFallBackToHiddenFullText", { try suite.testSpeechLegacyPartsNeverFallBackToHiddenFullText() }),
            ("testSpeechTokenCallbacksCannotClearOrStartNewPlayback", { try suite.testSpeechTokenCallbacksCannotClearOrStartNewPlayback() }),
            ("testSpeechReconcileStopsOnScopeVisibilityOrAnyContentChange", { try suite.testSpeechReconcileStopsOnScopeVisibilityOrAnyContentChange() }),
            ("testSpeechUnchangedRefreshKeepsPlaybackAndStopNeverResumesIt", { try suite.testSpeechUnchangedRefreshKeepsPlaybackAndStopNeverResumesIt() }),

            ("testMoodLedgerFrozenIdentityAndLegacyPersistence", { try suite.testMoodLedgerFrozenIdentityAndLegacyPersistence() }),
            ("testMoodLedgerApplyRetriesPreserveExactJSONAndNeverUseLegacyAPI", { try await suite.testMoodLedgerApplyRetriesPreserveExactJSONAndNeverUseLegacyAPI() }),
            ("testMoodLedgerMissingNullableMismatchedOrUnknownReceiptsStayUnknown", { try await suite.testMoodLedgerMissingNullableMismatchedOrUnknownReceiptsStayUnknown() }),
            ("testMoodLedgerCancelSendsMetadataOnlyAndAppliedIsNotRollback", { try await suite.testMoodLedgerCancelSendsMetadataOnlyAndAppliedIsNotRollback() }),
            ("testMoodLedgerTerminalConflictAndDeleteTokensAreChecked", { try await suite.testMoodLedgerTerminalConflictAndDeleteTokensAreChecked() }),

            ("testMoodDefaultsRequireBothExplicitAxesAndValidateRealDates", { try suite.testMoodDefaultsRequireBothExplicitAxesAndValidateRealDates() }),
            ("testMoodCRUDRequiresConfirmationExactVersionAndTrueDeleteReceipt", { try await suite.testMoodCRUDRequiresConfirmationExactVersionAndTrueDeleteReceipt() }),
            ("testMoodMismatchedSaveAndUnknownDeleteNeverConfirmSuccess", { try await suite.testMoodMismatchedSaveAndUnknownDeleteNeverConfirmSuccess() }),
            ("testMoodListRejectsDuplicateDaysOrInvalidTokens", { try await suite.testMoodListRejectsDuplicateDaysOrInvalidTokens() }),
            ("testMoodPendingSnapshotSurvivesRecreationWithoutBecomingMemoryOrChat", { try suite.testMoodPendingSnapshotSurvivesRecreationWithoutBecomingMemoryOrChat() }),
            ("testConfiguredAddressAcceptsOnlyExplicitHTTPSOrLoopbackHTTP", { try suite.testConfiguredAddressAcceptsOnlyExplicitHTTPSOrLoopbackHTTP() }),
            ("testBootstrapUsesOnlyCanonicalGETAndDoesNotCreateAConversation", { try await suite.testBootstrapUsesOnlyCanonicalGETAndDoesNotCreateAConversation() }),
            ("testChatUsesStableRequestIDAndExactTextWithoutModelSecrets", { try await suite.testChatUsesStableRequestIDAndExactTextWithoutModelSecrets() }),
            ("testAcceptedPendingResponseDoesNotSilentlyResend", { try await suite.testAcceptedPendingResponseDoesNotSilentlyResend() }),
            ("testRecoveryOnlyReadsTheSameTurnAndCanonicalID", { try await suite.testRecoveryOnlyReadsTheSameTurnAndCanonicalID() }),
            ("testCancelDoesNotRetransmitTextOrCreateAnotherTurn", { try await suite.testCancelDoesNotRetransmitTextOrCreateAnotherTurn() }),
            ("testCompletedCancelReceiptNeverClaimsItWasStopped", { try await suite.testCompletedCancelReceiptNeverClaimsItWasStopped() }),
            ("testUnknownReviewOnlyReadsOriginalTurnAndCanonicalSnapshot", { try await suite.testUnknownReviewOnlyReadsOriginalTurnAndCanonicalSnapshot() }),
            ("testRunningRequestCannotEndLocalWaitOrCreateAnotherSend", { try await suite.testRunningRequestCannotEndLocalWaitOrCreateAnotherSend() }),
            ("testCompletedRequestMustBeRecoveredInsteadOfAbandoned", { try await suite.testCompletedRequestMustBeRecoveredInsteadOfAbandoned() }),
            ("testUnknownReviewRejectsChangedCanonicalConversation", { try await suite.testUnknownReviewRejectsChangedCanonicalConversation() }),
            ("testFileSelectionEnforcesNamesAndUnicodeScalarLimit", { try suite.testFileSelectionEnforcesNamesAndUnicodeScalarLimit() }),
            ("testSelectedFilesAttachToCanonicalWithoutReadingPathsOrCreatingSession", { try await suite.testSelectedFilesAttachToCanonicalWithoutReadingPathsOrCreatingSession() }),
            ("testFileBatchCannotExceedThree", { try await suite.testFileBatchCannotExceedThree() }),
            ("testMemoryConfirmationHistoryAndDeletionUseRealEndpoints", { try await suite.testMemoryConfirmationHistoryAndDeletionUseRealEndpoints() }),
            ("testPreviewAndAttachAreSeparateExplicitOperations", { try await suite.testPreviewAndAttachAreSeparateExplicitOperations() }),
            ("testNotionUsesExistingCLIWithoutTokenOrNewLogin", { try await suite.testNotionUsesExistingCLIWithoutTokenOrNewLogin() }),
            ("testRevokeChecksActualAcknowledgementAndCanonicalSourceID", { try await suite.testRevokeChecksActualAcknowledgementAndCanonicalSourceID() }),
            ("testActionCommitAlwaysUsesRealFalse", { try await suite.testActionCommitAlwaysUsesRealFalse() }),
            ("testDecodedCommittedActionsDistinguishDraftLocalAndSystemResults", { try suite.testDecodedCommittedActionsDistinguishDraftLocalAndSystemResults() }),
            ("testDecodedNonCommittedActionsNeverClaimSavedOrSystemWritten", { try suite.testDecodedNonCommittedActionsNeverClaimSavedOrSystemWritten() }),
            ("testUnknownExistingActionOnlyReadsAndCannotPassConfirmationGuard", { try await suite.testUnknownExistingActionOnlyReadsAndCannotPassConfirmationGuard() }),
            ("testPreviewedActionGuardKeepsItsOriginalIDAndRejectsAnotherConversation", { try await suite.testPreviewedActionGuardKeepsItsOriginalIDAndRejectsAnotherConversation() }),
            ("testHTTPBudgetErrorIsActionableAndNotMisrepresentedAsSuccess", { try await suite.testHTTPBudgetErrorIsActionableAndNotMisrepresentedAsSuccess() }),
            ("testPendingMemoryPreferenceSurvivesPersistenceAndUsesSamePayload", { try await suite.testPendingMemoryPreferenceSurvivesPersistenceAndUsesSamePayload() }),
            ("testLegacyPendingRequestKeepsMemoryPreferenceOff", { try await suite.testLegacyPendingRequestKeepsMemoryPreferenceOff() }),
            ("testManualMemoryIsExplicitCandidateAndValidatesTextBeforePosting", { try await suite.testManualMemoryIsExplicitCandidateAndValidatesTextBeforePosting() }),
            ("testQuoteMemoryOnlyConfirmsTheExplicitOriginalMessage", { try await suite.testQuoteMemoryOnlyConfirmsTheExplicitOriginalMessage() }),
            ("testMemoryCASUsesExactVersionAndConflictDoesNotRetry", { try await suite.testMemoryCASUsesExactVersionAndConflictDoesNotRetry() }),
            ("testUnifiedLocalSearchIncludesMemoryAndMessagesButNotDeletedMemory", { try suite.testUnifiedLocalSearchIncludesMemoryAndMessagesButNotDeletedMemory() }),
            ("testTopicViewsRemainLocalLabelsWithDailyDefault", { suite.testTopicViewsRemainLocalLabelsWithDailyDefault() }),
            ("testFollowupContractKeepsConfirmationAndStableRequestID", { try await suite.testFollowupContractKeepsConfirmationAndStableRequestID() }),
            ("testCapabilitiesMetadataNeverProbesOrClaimsAuthorization", { try await suite.testCapabilitiesMetadataNeverProbesOrClaimsAuthorization() }),
            ("testSourcePreviewRequiresActualTextOrItemBeforeConfirmation", { try suite.testSourcePreviewRequiresActualTextOrItemBeforeConfirmation() }),
            ("testFollowupRejectsInvalidDraftBeforeAnyNetworkRequest", { try await suite.testFollowupRejectsInvalidDraftBeforeAnyNetworkRequest() }),
            ("testFollowupDoesNotAcceptMismatchedOrUnknownReceipt", { try await suite.testFollowupDoesNotAcceptMismatchedOrUnknownReceipt() }),
            ("testKnownRepeatingFollowupsAndQuietState", { try suite.testKnownRepeatingFollowupsAndQuietState() }),
            ("testDeliveryPartsAreOrderedAndLegacyMessagesStillDecode", { try suite.testDeliveryPartsAreOrderedAndLegacyMessagesStillDecode() }),
            ("testTargetedDeliveryStopSendsMessageIDAndRejectsUnconfirmedSuccess", { try await suite.testTargetedDeliveryStopSendsMessageIDAndRejectsUnconfirmedSuccess() }),
            ("testFeishuRequiresCompleteSnapshotAndReportsTruncation", { try suite.testFeishuRequiresCompleteSnapshotAndReportsTruncation() }),
            ("testDailyFollowupSendsOccurrenceAndChecksReceipt", { try await suite.testDailyFollowupSendsOccurrenceAndChecksReceipt() }),
            ("testExtendedFollowupSnapshotKeepsAllParametersAndAdvancedDailyReceipt", { try await suite.testExtendedFollowupSnapshotKeepsAllParametersAndAdvancedDailyReceipt() }),
            ("testLegacyPendingDoesNotAddTimezoneOrContactParameters", { try await suite.testLegacyPendingDoesNotAddTimezoneOrContactParameters() }),
            ("testNewChatTimezoneIsFrozenAcrossRecreation", { try await suite.testNewChatTimezoneIsFrozenAcrossRecreation() }),
            ("testInvalidRecurringAndContactParametersFailBeforeNetwork", { try suite.testInvalidRecurringAndContactParametersFailBeforeNetwork() }),
            ("testPassiveReviewRemainsVisibleWithoutContactConsent", { try suite.testPassiveReviewRemainsVisibleWithoutContactConsent() }),
            ("testBoundaryCASCarriesExplicitConfirmationAndNeverRetriesConflict", { try await suite.testBoundaryCASCarriesExplicitConfirmationAndNeverRetriesConflict() }),
            ("testBoundaryReceiptAndNextLocalMidnightAcrossDST", { try await suite.testBoundaryReceiptAndNextLocalMidnightAcrossDST() }),
            ("testUnexpectedHTMLDoesNotExposeRawServerResponse", { try await suite.testUnexpectedHTMLDoesNotExposeRawServerResponse() })
        ]
        for (name, run) in cases {
            let previous = failureCount
            do { try await run() } catch { fail("\(name) threw: \(error.localizedDescription)") }
            if failureCount == previous { print("PASS: \(name)") }
        }
        print("Foundation checks: \(cases.count - failureCount)/\(cases.count) passed")
        if failureCount > 0 { exit(1) }
    }
}
