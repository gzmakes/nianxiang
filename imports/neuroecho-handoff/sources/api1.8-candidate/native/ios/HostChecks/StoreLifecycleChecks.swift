import Foundation
import SwiftUI

/// All responses are synthetic URLProtocol data. No real host, file, account or model.
private final class SyntheticProtocol: URLProtocol {
    static var state = "unknown"
    static var cancelled = false
    static var calls = [String]()
    static var chatBodies = [[String:Any]]()
    static var chatBusy = false
    static var busyMutation = ""
    static var holdChat = false
    static var heldChat = [SyntheticProtocol]()
    static var turnOverride: String?
    static var followupList = #"{"followups":[]}"#
    static var followupFailureStatus: Int?
    static var followupRequestIDs = [String]()
    static var deliveryStop = #"{"ok":true,"stopped":false,"message_id":"msg-1","reason":"not_pending"}"#
    static var deliveryStopBodies = [[String:Any]]()
    static var holdConversation = false
    static var heldConversations = [SyntheticProtocol]()
    static var extendedCapabilities=false
    static var boundaryJSON = #"{"revision":0,"mode":"active","until":null,"time_zone":"UTC","suppression_revision":0}"#
    static var holdBoundary=false
    static var heldBoundaries=[SyntheticProtocol]()
    static var snapshot = #"{"session":{"id":"canonical"},"messages":[{"id":"msg-1","role":"user","text":"合成第一句"},{"id":"msg-2","role":"assistant","text":"合成回复"}],"memories":[],"context":null}"#
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    private func body() -> [String:Any] {
        var data = request.httpBody ?? Data()
        if data.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer {stream.close()}; var buffer = [UInt8](repeating:0,count:1024)
            while stream.hasBytesAvailable { let count = stream.read(&buffer,maxLength:buffer.count); if count <= 0 {break}; data.append(buffer,count:count) }
        }
        return (try? JSONSerialization.jsonObject(with:data)) as? [String:Any] ?? [:]
    }
    override func startLoading() {
        let path = request.url!.path, method = request.httpMethod ?? "GET"
        Self.calls.append(method + " " + path)
        if path == "/api/conversation", Self.holdConversation {Self.heldConversations.append(self); return}
        if path == "/api/companion-boundary", Self.holdBoundary {Self.heldBoundaries.append(self);return}
        let json: String
        if path == "/api/conversation" { json = Self.snapshot }
        else if path == "/api/capabilities" {
            json = Self.extendedCapabilities
                ? #"{"contract_version":"1.3.0","deployment_mode":"local_single_user","service_platform":"darwin","features":{"memory_expected_version_patch":true,"memory_expected_version_delete":true,"realtime_multi_device_sync":false,"chat_delivery_targeted_stop":true,"in_app_recurring_followups":true,"companion_boundaries":true,"bounded_followup_contact":true,"unified_contact_claim":true},"platform_status":{},"connection_status":"not_probed"}"#
                : #"{"contract_version":"1.2.0","deployment_mode":"local_single_user","service_platform":"darwin","features":{"memory_expected_version_patch":true,"memory_expected_version_delete":true,"realtime_multi_device_sync":false,"chat_delivery_targeted_stop":true},"platform_status":{"apple_calendar":"conditions_required"},"connection_status":"not_probed"}"#
        }
        else if path == "/api/companion-boundary" {json=Self.boundaryJSON}
        else if path == "/api/actions" { json = #"{"actions":[]}"# }
        else if path == "/api/next-step" { json = #"{"step":"synthetic"}"# }
        else if path == "/api/followups", method == "GET" { json = Self.followupList }
        else if path == "/api/followups", method == "POST" {
            Self.followupRequestIDs.append(body()["request_id"] as? String ?? "")
            if let status = Self.followupFailureStatus {
                client?.urlProtocol(self,didReceive:HTTPURLResponse(url:request.url!,statusCode:status,httpVersion:nil,headerFields:["Content-Type":"application/json"])!,cacheStoragePolicy:.notAllowed)
                client?.urlProtocol(self,didLoad:Data(#"{"detail":"合成验证拒绝"}"#.utf8)); client?.urlProtocolDidFinishLoading(self); return
            }
            client?.urlProtocol(self,didFailWithError:URLError(.timedOut)); return
        }
        else if path == "/api/chat" {
            let value = body(); Self.chatBodies.append(value)
            if Self.holdChat {Self.heldChat.append(self);return}
            if Self.chatBusy {finishBusy(value);return}
            json = "{\"request_id\":\"\(value["request_id"] as! String)\",\"session_id\":\"canonical\",\"status\":\"running\"}"
        }
        else if path.hasSuffix("/delivery/stop") {Self.deliveryStopBodies.append(body()); json=Self.deliveryStop}
        else if path.hasSuffix("/cancel") { json = "{\"request_id\":\"synthetic-turn\",\"session_id\":\"canonical\",\"status\":\"completed\",\"result\":{\"messages\":[],\"cancelled\":\(Self.cancelled)}}" }
        else if path.hasPrefix("/api/chat/turn/") { json = Self.turnOverride ?? "{\"request_id\":\"\(request.url!.lastPathComponent)\",\"session_id\":\"canonical\",\"status\":\"\(Self.state)\"}" }
        else { fatalError("Unexpected request: lifecycle checks must stay synthetic") }
        finish(json)
    }
    func finishBusy(_ payload: [String:Any]? = nil) {
        let payload = payload ?? body()
        var data: [String:Any] = ["request_id":payload["request_id"] ?? "", "session_id":payload["session_id"] ?? "", "status":"unknown", "error_code":"conversation_busy_not_accepted"]
        if !Self.busyMutation.isEmpty {data[Self.busyMutation] = "other"}
        client?.urlProtocol(self,didReceive:HTTPURLResponse(url:request.url!,statusCode:409,httpVersion:nil,headerFields:["Content-Type":"application/json"])!,cacheStoragePolicy:.notAllowed)
        client?.urlProtocol(self,didLoad:try! JSONSerialization.data(withJSONObject:data));client?.urlProtocolDidFinishLoading(self)
    }
    func finish(_ json: String) {
        client?.urlProtocol(self,didReceive:HTTPURLResponse(url:request.url!,statusCode:200,httpVersion:nil,headerFields:["Content-Type":"application/json"])!,cacheStoragePolicy:.notAllowed)
        client?.urlProtocol(self,didLoad:Data(json.utf8)); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
@MainActor private func makeSyntheticStore(defaults: UserDefaults) -> EchoStore {
    EchoStore(defaults:defaults,apiFactory:{address,authorization in
        let configuration=URLSessionConfiguration.ephemeral;configuration.protocolClasses=[SyntheticProtocol.self]
        return try EchoAPI(baseURL:address,session:URLSession(configuration:configuration),authorization:authorization)
    })
}
@main struct StoreLifecycleChecks {
    @MainActor static func makeStore(seedPending: Bool = true) throws -> (EchoStore,UserDefaults,String) {
        let name = "echo.synthetic.lifecycle." + UUID().uuidString
        let defaults = UserDefaults(suiteName:name)!
        defaults.set("http://127.0.0.1:19099",forKey:"echo.native.endpoint")
        if seedPending {
            let turn = EchoPendingTurn(sessionID:"canonical",text:"synthetic retained text",origin:"http://127.0.0.1:19099",requestID:"synthetic-turn")
            defaults.set(try JSONEncoder().encode(turn),forKey:"echo.native.pending-turn.v1")
        }
        return (makeSyntheticStore(defaults:defaults),defaults,name)
    }
    @MainActor static func main() async {
        var checkGroups = 0
        func passed(_ label: String) { checkGroups += 1; print("PASS: \(label)") }
        URLProtocol.registerClass(SyntheticProtocol.self)
        do {
            let (store,defaults,name) = try makeStore(); defer {defaults.removePersistentDomain(forName:name)}
            await store.connect(); await store.recoverPending()
            precondition(store.canEndLocalWait && store.pending != nil)
            store.draft = "existing draft"; SyntheticProtocol.calls = []
            await store.endLocalWaitAfterReview()
            precondition(store.pending == nil && !store.canEndLocalWait)
            precondition(store.draft == "synthetic retained text\nexisting draft")
            precondition(defaults.data(forKey:"echo.native.pending-turn.v1") == nil)
            precondition(SyntheticProtocol.calls == ["GET /api/chat/turn/synthetic-turn","GET /api/conversation"])
            passed("unknown review preserves draft and performs no POST")

            let (running,rd,rn) = try makeStore(); defer {rd.removePersistentDomain(forName:rn)}
            SyntheticProtocol.state = "unknown"; await running.connect(); await running.recoverPending()
            SyntheticProtocol.state = "running"; await running.endLocalWaitAfterReview()
            precondition(running.pending != nil && running.draft.isEmpty)
            passed("changed running status cannot release pending")

            let (done,dd,dn) = try makeStore(); defer {dd.removePersistentDomain(forName:dn)}
            await done.connect(); SyntheticProtocol.cancelled = false; await done.cancelPending()
            precondition(done.pending == nil && done.error?.contains("未能撤回") == true && done.error?.contains("已停止") == false)
            passed("cancelled false never reports stopped")
            let (stopped,sd,sn) = try makeStore(); defer {sd.removePersistentDomain(forName:sn)}
            await stopped.connect(); SyntheticProtocol.cancelled = true; await stopped.cancelPending()
            precondition(stopped.pending == nil && stopped.error?.contains("已停止") == true)
            passed("confirmed cancellation reports stopped")

            let (draft,df,dfn) = try makeStore(seedPending:false); defer {df.removePersistentDomain(forName:dfn)}
            draft.draft = "合成未发送草稿"
            precondition(makeSyntheticStore(defaults:df).draft == "合成未发送草稿")
            passed("ordinary draft survives store recreation")
            await draft.connect(to:"http://127.0.0.1:19100")
            precondition(draft.draft.isEmpty)
            draft.draft = "另一个服务的合成草稿"
            await draft.connect(to:"http://127.0.0.1:19099")
            precondition(draft.draft == "合成未发送草稿")
            passed("endpoint changes isolate drafts and restore original draft")

            draft.setTopic("周五方案",for:"msg-1")
            precondition(draft.visibleMessages.map(\.id) == ["msg-1"])
            let restored = makeSyntheticStore(defaults:df); await restored.connect()
            precondition(restored.topics["msg-1"] == "周五方案")
            precondition(restored.conversation?.session.id == draft.conversation?.session.id)
            passed("topic persists locally without a new conversation")
            let oldToken = draft.jumpRequestID; draft.focusMessage("msg-1")
            precondition(draft.selectedTopic == "全部" && draft.jumpRequestID != oldToken)
            let once = draft.jumpRequestID; draft.focusMessage("msg-1")
            precondition(draft.jumpRequestID != once)
            passed("repeated search jump resets topic and creates a new scroll event")

            SyntheticProtocol.state = "unknown"; SyntheticProtocol.calls = []
            let (foreground,fd,fn) = try makeStore(); defer {fd.removePersistentDomain(forName:fn)}
            await foreground.refreshFromForeground()
            precondition(foreground.pending != nil && foreground.canEndLocalWait)
            precondition(SyntheticProtocol.calls.allSatisfy { $0.hasPrefix("GET ") })
            precondition(SyntheticProtocol.calls.contains("GET /api/chat/turn/synthetic-turn"))
            passed("foreground refresh reconciles pending using GET only")
            foreground.busy = true; SyntheticProtocol.calls = []; await foreground.refreshFromForeground()
            precondition(SyntheticProtocol.calls.isEmpty); foreground.busy = false
            passed("foreground refresh does not overlap in-flight user work")

            let (delivery,xd,xn) = try makeStore(seedPending:false); defer {xd.removePersistentDomain(forName:xn)}
            let originalSnapshot = SyntheticProtocol.snapshot
            SyntheticProtocol.snapshot = #"{"session":{"id":"canonical"},"messages":[{"id":"msg-1","role":"assistant","text":"第一段","bubbles":["第一段"],"delivery_pending":true,"delivery_next_ms":100}],"memories":[],"context":null}"#
            await delivery.connect()
            precondition(delivery.conversation?.messages[0].displayParts == ["第一段"])
            SyntheticProtocol.snapshot = #"{"session":{"id":"canonical"},"messages":[{"id":"msg-1","role":"assistant","text":"第一段\n\n第二段","bubbles":["第一段","第二段"],"delivery_pending":false}],"memories":[],"context":null}"#
            SyntheticProtocol.calls = []; await delivery.refreshDelivery()
            precondition(delivery.conversation?.messages[0].displayParts == ["第一段","第二段"])
            precondition(delivery.conversation?.messages[0].deliveryPending == false)
            precondition(SyntheticProtocol.calls == ["GET /api/conversation"])
            SyntheticProtocol.calls = []; await delivery.refreshDelivery(); precondition(SyntheticProtocol.calls.isEmpty)
            passed("delivery resumes with ordered parts through GET only and stops when complete")
            SyntheticProtocol.snapshot = #"{"session":{"id":"canonical"},"messages":[{"id":"msg-1","role":"assistant","text":"第一段","delivery_pending":true}],"memories":[],"context":null}"#
            await delivery.connect()
            SyntheticProtocol.snapshot = #"{"session":{"id":"other"},"messages":[{"id":"intruder","role":"assistant","text":"错误对话"}],"memories":[],"context":null}"#
            await delivery.refreshDelivery()
            precondition(delivery.conversation?.session.id == "canonical" && delivery.conversation?.messages[0].id == "msg-1")
            SyntheticProtocol.snapshot = originalSnapshot
            passed("delivery refresh rejects a different canonical conversation")

            let pendingDelivery = #"{"session":{"id":"canonical"},"messages":[{"id":"msg-1","role":"assistant","text":"已经显示的一句","delivery_pending":true}],"memories":[],"context":null}"#
            let stoppedDelivery = #"{"session":{"id":"canonical"},"messages":[{"id":"msg-1","role":"assistant","text":"已经显示的一句","delivery_pending":false}],"memories":[],"context":null}"#
            SyntheticProtocol.snapshot=pendingDelivery; await delivery.connect()
            SyntheticProtocol.snapshot=stoppedDelivery; SyntheticProtocol.calls=[]; SyntheticProtocol.deliveryStopBodies=[]
            SyntheticProtocol.deliveryStop = #"{"ok":true,"stopped":false,"message_id":"msg-1","reason":"not_pending"}"#
            await delivery.stopDelivery(messageID:"msg-1")
            precondition(delivery.error?.contains("尚未确认停止") == true)
            precondition(SyntheticProtocol.calls == ["POST /api/session/canonical/delivery/stop","GET /api/conversation"])
            precondition(SyntheticProtocol.deliveryStopBodies[0]["message_id"] as? String == "msg-1")
            passed("delivery stopped false never becomes success and only GET reconciles")
            SyntheticProtocol.snapshot=pendingDelivery; await delivery.connect(); SyntheticProtocol.snapshot=stoppedDelivery
            SyntheticProtocol.deliveryStop = #"{"ok":true,"stopped":true,"message_id":"msg-1","reason":"stopped"}"#
            await delivery.stopDelivery(messageID:"msg-1")
            precondition(delivery.error?.hasPrefix("已停止展开这条回复") == true)
            SyntheticProtocol.calls=[]; await delivery.stopDelivery(messageID:"old-id"); precondition(SyntheticProtocol.calls.isEmpty)
            passed("delivery stop requires matching acknowledgement plus refreshed stopped message")
            SyntheticProtocol.snapshot=pendingDelivery; await delivery.connect()
            SyntheticProtocol.holdConversation=true
            let staleRead=Task {await delivery.refreshDelivery()}
            for _ in 0..<100 where SyntheticProtocol.heldConversations.isEmpty {await Task.yield()}
            precondition(SyntheticProtocol.heldConversations.count == 1)
            let decoder=JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
            let newer=pendingDelivery.replacingOccurrences(of:"已经显示的一句",with:"刚刚接受的新内容")
            delivery.conversation=try decoder.decode(EchoConversation.self,from:Data(newer.utf8))
            SyntheticProtocol.heldConversations.removeFirst().finish(pendingDelivery)
            await staleRead.value; SyntheticProtocol.holdConversation=false
            precondition(delivery.conversation?.messages[0].text == "刚刚接受的新内容")
            passed("late delivery GET cannot replace a newer accepted conversation revision")
            SyntheticProtocol.snapshot=originalSnapshot

            let (preference,pd,pn) = try makeStore(seedPending:false); defer {pd.removePersistentDomain(forName:pn)}
            await preference.connect(); preference.memoryProposals = true; preference.draft = "合成可提议原话"
            SyntheticProtocol.chatBodies = []; await preference.send()
            precondition(preference.pending?.memoryProposals == true)
            preference.memoryProposals = false
            let resumed = makeSyntheticStore(defaults:pd)
            precondition(resumed.pending?.memoryProposals == true && resumed.memoryProposals == false)
            precondition(SyntheticProtocol.chatBodies.count == 1 && SyntheticProtocol.chatBodies[0]["memory_proposals"] as? Bool == true)
            passed("pending request snapshots preference independently of later toggle")
            let (follow,ud,un) = try makeStore(seedPending:false); defer {ud.removePersistentDomain(forName:un)}
            await follow.connect()
            await follow.saveFollowup(content:"合成要跟进的事",date:Date().addingTimeInterval(3600))
            guard let pending = follow.pendingFollowup else { fatalError("timeout must preserve pending") }
            precondition(ud.data(forKey:"echo.native.pending-followup.v1") != nil)
            let recreated = makeSyntheticStore(defaults:ud); await recreated.connect()
            precondition(recreated.pendingFollowup?.requestID == pending.requestID && recreated.pendingFollowup?.content == pending.content)
            passed("uncertain followup survives store recreation")
            SyntheticProtocol.followupFailureStatus = 400
            await recreated.retryFollowup()
            precondition(recreated.pendingFollowup?.requestID == pending.requestID)
            precondition(SyntheticProtocol.followupRequestIDs.suffix(2).allSatisfy {$0 == pending.requestID})
            SyntheticProtocol.followupFailureStatus = nil
            passed("retry rejection after prior uncertainty preserves the same pending ID")
            func list(content: String, due: String) throws -> String {
                var item=pending.body
                item["id"]="synthetic-fup";item["content"]=content;item["due_at"]=due;item["status"]="pending";item["due"]=false
                return String(data:try JSONSerialization.data(withJSONObject:["followups":[item]]),encoding:.utf8)!
            }
            SyntheticProtocol.followupList = try list(content:"不匹配的内容",due:pending.dueAt)
            await recreated.refreshFollowups()
            precondition(recreated.pendingFollowup?.requestID == pending.requestID)
            SyntheticProtocol.followupList = try list(content:pending.content,due:"2035-01-01T00:00:00Z")
            await recreated.refreshFollowups()
            precondition(recreated.pendingFollowup?.requestID == pending.requestID)
            SyntheticProtocol.followupList = try list(content:pending.content,due:pending.dueAt)
            await recreated.refreshFollowups()
            precondition(recreated.pendingFollowup == nil && ud.data(forKey:"echo.native.pending-followup.v1") == nil)
            passed("followup reconciliation checks content and time before unlocking")
            let (invalid,vd,vn) = try makeStore(seedPending:false); defer {vd.removePersistentDomain(forName:vn)}
            await invalid.connect(); SyntheticProtocol.followupFailureStatus = 400
            await invalid.saveFollowup(content:"合成应保留的跟进草稿",date:Date().addingTimeInterval(3600))
            precondition(invalid.pendingFollowup == nil && invalid.followupDraft?.content == "合成应保留的跟进草稿")
            precondition(makeSyntheticStore(defaults:vd).followupDraft?.content == "合成应保留的跟进草稿")
            SyntheticProtocol.followupFailureStatus = nil
            passed("first definitive validation failure restores editable persisted draft")
            for code in [400,422] {
                let (rejected,rd2,rn2) = try makeStore(seedPending:false); defer {rd2.removePersistentDomain(forName:rn2)}
                await rejected.connect(); SyntheticProtocol.followupFailureStatus = code
                await rejected.saveFollowup(content:"合成待修改内容",date:Date().addingTimeInterval(3600))
                precondition(rejected.pendingFollowup == nil && rejected.followupDraft?.content == "合成待修改内容")
                let restoredDraft = makeSyntheticStore(defaults:rd2)
                precondition(restoredDraft.followupDraft?.content == "合成待修改内容")
            }
            passed("initial 400/422 preserves editable draft")
            let (migration,md,mn)=try makeStore(seedPending:false); defer {md.removePersistentDomain(forName:mn)}
            let legacyDraft=try EchoPendingFollowup(sessionID:"canonical",content:"并行版本遗留草稿",date:Date().addingTimeInterval(3600),origin:migration.endpoint)
            md.set(try JSONEncoder().encode(legacyDraft),forKey:"echo.native.followup-rejected-draft.v1")
            let restoredLegacy=makeSyntheticStore(defaults:md)
            precondition(restoredLegacy.followupDraft?.requestID == legacyDraft.requestID)
            await restoredLegacy.connect(to:"http://127.0.0.1:19101")
            precondition(restoredLegacy.endpoint == migration.endpoint)
            passed("both local followup draft keys remain readable and protect endpoint changes")
            for code in [408,409,429,500] {
                let (uncertain,ud2,un2) = try makeStore(seedPending:false); defer {ud2.removePersistentDomain(forName:un2)}
                await uncertain.connect(); SyntheticProtocol.followupFailureStatus = code
                await uncertain.saveFollowup(content:"合成待核对内容",date:Date().addingTimeInterval(3600))
                precondition(uncertain.pendingFollowup != nil && uncertain.followupDraft == nil)
            }
            SyntheticProtocol.followupFailureStatus = nil
            let (late,ld,ln) = try makeStore(seedPending:false); defer {ld.removePersistentDomain(forName:ln)}
            await late.connect(); await late.saveFollowup(content:"合成超时的内容",date:Date().addingTimeInterval(3600))
            let oldID = late.pendingFollowup?.requestID
            SyntheticProtocol.followupFailureStatus = 400; await late.retryFollowup()
            precondition(late.pendingFollowup?.requestID == oldID && late.followupDraft == nil)
            passed("uncertain attempts and later 400 remain locked")

            SyntheticProtocol.followupFailureStatus=nil;SyntheticProtocol.extendedCapabilities=true
            let (r9,r9d,r9n)=try makeStore(seedPending:false);defer {r9d.removePersistentDomain(forName:r9n)}
            await r9.connect()
            var form=EchoFollowupFormDraft(sessionID:"canonical",origin:r9.endpoint)
            form.content="R9 合成周期草稿";form.repeatRule="daily";form.timeZone="Asia/Shanghai";form.usesQuietHours=true;form.quietStart="22:00";form.quietEnd="08:00";form.allowContact=true;form.contactTopic="只聊这一件";form.contactWindowMinutes=45
            r9.saveFollowupForm(form)
            let formRestored=makeSyntheticStore(defaults:r9d);await formRestored.connect()
            precondition(formRestored.followupForm == form)
            await formRestored.connect(to:"http://127.0.0.1:19102");precondition(formRestored.followupForm == nil)
            await formRestored.connect(to:r9.endpoint);precondition(formRestored.followupForm == form)
            passed("ordinary followup form preserves periodic/timezone/quiet/contact parameters and isolates endpoints")

            SyntheticProtocol.chatBodies=[];r9.draft="今天先别问";await r9.send()
            precondition(r9.pending?.timeZone == TimeZone.current.identifier)
            precondition(SyntheticProtocol.chatBodies.last?["time_zone"] as? String == r9.pending?.timeZone)
            let chatRestored=makeSyntheticStore(defaults:r9d)
            precondition(chatRestored.pending?.timeZone == r9.pending?.timeZone)
            passed("new chat snapshots local timezone and restores it without changing old request payloads")

            let (daily,dailyDefaults,dailySuite)=try makeStore(seedPending:false);defer {dailyDefaults.removePersistentDomain(forName:dailySuite)}
            await daily.connect();daily.saveFollowupForm(form)
            SyntheticProtocol.calls=[]
            let saved=await daily.saveFollowup(content:form.content,date:form.due,repeatRule:form.repeatRule,timeZone:form.timeZone,quietStart:form.quietStart,quietEnd:form.quietEnd,allowContact:true,contactWindowMinutes:45,contactTopic:form.contactTopic)
            precondition(!saved)
            guard let request=daily.pendingFollowup else {fatalError("timeout must preserve full daily request")}
            precondition(request.repeatRule == "daily" && request.timeZone == "Asia/Shanghai" && request.allowContact == true && request.contactWindowMinutes == 45)
            let dailyRestored=makeSyntheticStore(defaults:dailyDefaults);await dailyRestored.connect()
            let restoredPayload=try JSONSerialization.data(withJSONObject:dailyRestored.pendingFollowup!.body,options:.sortedKeys)
            let originalPayload=try JSONSerialization.data(withJSONObject:request.body,options:.sortedKeys)
            precondition(restoredPayload == originalPayload)
            precondition(SyntheticProtocol.calls.filter {$0 == "POST /api/followups"}.count == 1)
            passed("daily timeout keeps one exact persisted payload including explicit contact permission")
            func dailyList(status: String, topic: String) throws -> String {
                var item=request.body;item["id"]="r9-daily";item["status"]=status;item["due"]=false;item["created_due_at"]=request.dueAt
                item["due_at"]=ISO8601DateFormatter().string(from:form.due.addingTimeInterval(86_400));item["contact_topic"]=topic
                return String(data:try JSONSerialization.data(withJSONObject:["followups":[item]]),encoding:.utf8)!
            }
            SyntheticProtocol.followupList=try dailyList(status:"pending",topic:"不匹配的话题");await dailyRestored.refreshFollowups();precondition(dailyRestored.pendingFollowup != nil)
            SyntheticProtocol.followupList=try dailyList(status:"future-status",topic:form.contactTopic);await dailyRestored.refreshFollowups();precondition(dailyRestored.pendingFollowup != nil)
            SyntheticProtocol.followupList=try dailyList(status:"cancelled",topic:form.contactTopic);await dailyRestored.refreshFollowups();precondition(dailyRestored.pendingFollowup == nil)
            passed("advanced daily GET reconciles created_due_at plus full scope; mismatched and unknown receipts stay locked")

            let (invalidR9,id9,in9)=try makeStore(seedPending:false);defer {id9.removePersistentDomain(forName:in9)}
            await invalidR9.connect();invalidR9.saveFollowupForm(EchoFollowupFormDraft(sessionID:"canonical",origin:invalidR9.endpoint));SyntheticProtocol.calls=[]
            let invalidSaved=await invalidR9.saveFollowup(content:"保留参数错误草稿",date:Date().addingTimeInterval(3600),repeatRule:"daily",timeZone:"Asia/Shanghai",allowContact:true,contactWindowMinutes:181)
            precondition(!invalidSaved && invalidR9.pendingFollowup == nil && invalidR9.followupForm != nil && SyntheticProtocol.calls.isEmpty)
            passed("invalid full form remains editable without a network write or a false saved result")

            SyntheticProtocol.followupFailureStatus=400
            _ = await invalidR9.saveFollowup(content:"明确拒绝的旧草稿",date:Date().addingTimeInterval(3600))
            guard let rejectedForm=invalidR9.followupDraft else {fatalError("must keep first rejection")}
            var revisedForm=EchoFollowupFormDraft(rejectedForm);revisedForm.content="编辑后关闭也应保留"
            invalidR9.saveFollowupForm(revisedForm)
            let revisedStore=makeSyntheticStore(defaults:id9)
            precondition(revisedStore.followupDraft == nil && revisedStore.followupForm?.content == revisedForm.content)
            SyntheticProtocol.followupFailureStatus=nil
            passed("editing a definitively rejected draft preserves the newer full form when reopened")

            SyntheticProtocol.boundaryJSON = #"{"revision":2,"mode":"paused","until":null,"time_zone":"Asia/Shanghai","suppression_revision":2}"#
            SyntheticProtocol.calls=[];await invalidR9.refreshBoundary()
            precondition(invalidR9.boundary?.mode == "paused" && SyntheticProtocol.calls == ["GET /api/companion-boundary"])
            SyntheticProtocol.holdBoundary=true
            let oldBoundary=Task {await invalidR9.refreshBoundary()}
            for _ in 0..<1000 where SyntheticProtocol.heldBoundaries.count < 1 {await Task.yield()}
            let newBoundary=Task {await invalidR9.refreshBoundary()}
            for _ in 0..<1000 where SyntheticProtocol.heldBoundaries.count < 2 {await Task.yield()}
            precondition(SyntheticProtocol.heldBoundaries.count == 2)
            SyntheticProtocol.heldBoundaries.remove(at:1).finish(#"{"revision":4,"mode":"paused","until":null,"time_zone":"Asia/Shanghai","suppression_revision":4}"#)
            await newBoundary.value
            SyntheticProtocol.heldBoundaries.removeFirst().finish(#"{"revision":3,"mode":"active","until":null,"time_zone":"UTC","suppression_revision":3}"#)
            await oldBoundary.value;SyntheticProtocol.holdBoundary=false
            precondition(invalidR9.boundary?.revision == 4 && invalidR9.boundary?.mode == "paused")
            precondition(SyntheticProtocol.calls.allSatisfy {$0.hasPrefix("GET ")})
            passed("boundary refresh is GET only and late older policy cannot overwrite a newer result; no contact claim")

            let (busyStore,busyDefaults,busyName)=try makeStore(seedPending:false);defer {busyDefaults.removePersistentDomain(forName:busyName)}
            await busyStore.connect(); SyntheticProtocol.calls=[];SyntheticProtocol.chatBodies=[];SyntheticProtocol.holdChat=true
            busyStore.draft="未接受的原话";let sending=Task {await busyStore.send()}
            for _ in 0..<100 where SyntheticProtocol.heldChat.isEmpty {await Task.yield()}
            precondition(SyntheticProtocol.heldChat.count == 1)
            busyStore.draft="新草稿";SyntheticProtocol.heldChat.removeFirst().finishBusy();await sending.value;SyntheticProtocol.holdChat=false
            precondition(busyStore.pending == nil && busyStore.draft == "未接受的原话\n新草稿")
            precondition(SyntheticProtocol.calls.filter {$0 == "POST /api/chat"}.count == 1)
            let firstID=SyntheticProtocol.chatBodies.first!["request_id"] as! String
            await busyStore.send();precondition(SyntheticProtocol.chatBodies.count == 2 && SyntheticProtocol.chatBodies[1]["request_id"] as! String != firstID)
            passed("exact busy POST restores old and new drafts; next manual send uses new ID")
            for key in ["request_id","session_id","status","error_code"] {
                let (forged,fd3,fn3)=try makeStore(seedPending:false);defer {fd3.removePersistentDomain(forName:fn3)}
                await forged.connect();forged.draft="保留的原话";SyntheticProtocol.chatBusy=true;SyntheticProtocol.busyMutation=key
                await forged.send();precondition(forged.pending != nil && forged.draft.isEmpty)
            }
            SyntheticProtocol.chatBusy=false;SyntheticProtocol.busyMutation=""
            passed("mismatched busy POST keeps the pending ledger")
            let (getBusy,gd,gn)=try makeStore();defer {gd.removePersistentDomain(forName:gn)}
            await getBusy.connect();getBusy.draft="新草稿";SyntheticProtocol.calls=[]
            SyntheticProtocol.turnOverride=#"{"request_id":"synthetic-turn","session_id":"canonical","status":"unknown","error_code":"conversation_busy_not_accepted"}"#
            await getBusy.recoverPending();precondition(getBusy.pending == nil && getBusy.draft == "synthetic retained text\n新草稿")
            precondition(SyntheticProtocol.calls == ["GET /api/chat/turn/synthetic-turn"])
            passed("exact busy GET recovers text without a POST")
            for (key,value) in [("request_id","other"),("session_id","other"),("status","running"),("error_code","other")] {
                let (forged,fd4,fn4)=try makeStore();defer {fd4.removePersistentDomain(forName:fn4)}
                SyntheticProtocol.turnOverride=nil;await forged.connect();forged.draft="新草稿"
                var data: [String:String] = ["request_id":"synthetic-turn","session_id":"canonical","status":"unknown","error_code":"conversation_busy_not_accepted"]
                data[key]=value;SyntheticProtocol.turnOverride=String(data:try JSONSerialization.data(withJSONObject:data),encoding:.utf8)!
                await forged.recoverPending();precondition(forged.pending != nil && forged.draft == "新草稿")
            }
            SyntheticProtocol.turnOverride=nil
            passed("mismatched busy GET preserves pending and current draft")
            print("Host Store check groups: \(checkGroups)/\(checkGroups) passed; no iOS runtime or device validation.")
        } catch { print("FAIL: lifecycle check \(error.localizedDescription)"); exit(1) }
    }
}
