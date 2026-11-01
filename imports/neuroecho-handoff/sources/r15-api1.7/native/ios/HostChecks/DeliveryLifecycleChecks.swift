import Foundation
import SwiftUI

@MainActor private final class DeliveryVault: EchoDeviceCredentialStore {
    private var values=[String:String]()
    func save(_ token:String,for profile:EchoDeviceProfile) throws {values[profile.vaultAccount]=token}
    func read(for profile:EchoDeviceProfile) throws -> String {guard let value=values[profile.vaultAccount] else {throw EchoCredentialStoreError.missing};return value}
    func remove(for profile:EchoDeviceProfile) throws {values.removeValue(forKey:profile.vaultAccount)}
}
private final class DeliveryProtocol: URLProtocol {
    private static let lock=NSRecursiveLock()
    private static var requests=[String](),waiting=[DeliveryProtocol]()
    private static var stage="initial",hold=false,completeAfterPendingRead=false,changes=true
    static func configure(stage:String="initial",hold:Bool=false,completeAfterPendingRead:Bool=false,changes:Bool=true) {
        lock.lock();defer {lock.unlock()}
        self.stage=stage;self.hold=hold;self.completeAfterPendingRead=completeAfterPendingRead;self.changes=changes
    }
    static func resetCalls() {lock.lock();defer {lock.unlock()};requests=[]}
    static var calls:[String] {lock.lock();defer {lock.unlock()};return requests}
    static var heldCount:Int {lock.lock();defer {lock.unlock()};return waiting.count}
    static func release(_ value:[String:Any]) {lock.lock();let request=waiting.removeFirst();lock.unlock();request.finish(value)}
    static func snapshot(_ stage:String) -> [String:Any] {
        var messages=[[String:Any]]()
        if stage != "deleted" {
            let pending=stage == "pending"
            let parts=pending ? ["合成洞察第一段"] : stage == "initial" ? ["原有回复"] : ["合成洞察第一段","合成洞察第二段"]
            messages=[["id":"intro-message","role":"assistant","text":parts.joined(separator:"\n\n"),"bubbles":parts,"delivery_pending":pending,"delivery_next_ms":100,
                "citations":[["kind":"feishu_document","title":"合成文档","url":"https://synthetic.feishu.cn/docx/synthetic_document","text":"合成文档"]]]]
        }
        return ["session":["id":"canonical"],"messages":messages,"memories":[],"context":NSNull()]
    }
    override class func canInit(with request:URLRequest)->Bool {true}
    override class func canonicalRequest(for request:URLRequest)->URLRequest {request}
    override func stopLoading() {}
    override func startLoading() {
        Self.lock.lock();defer {Self.lock.unlock()}
        let path=request.url!.path
        precondition(request.httpMethod == "GET","Delivery continuation cannot submit chat, intro, auth, source or model operations")
        Self.requests.append("GET "+path)
        if path == "/api/paired-device" {
            let id=request.value(forHTTPHeaderField:"Authorization")!.hasSuffix(String(repeating:"B",count:43)) ? "B" : "A"
            finish(["service_instance_id":"delivery-instance","conversation_id":"canonical","scope":"personal_core","local_actions_allowed":false,"device":["id":id,"label":"合成设备","created_at":"2026-01-01T00:00:00Z","expires_at":"2099-01-01T00:00:00Z","revoked_at":NSNull()]]);return
        }
        if path == "/api/capabilities" {finish(["contract_version":"1.7.0","deployment_mode":"paired_single_owner","service_platform":"darwin","features":["conversation_change_cursor":Self.changes],"platform_status":[:],"connection_status":"not_probed"]);return}
        if path == "/api/conversation/changes" {
            let after=URLComponents(url:request.url!,resolvingAgainstBaseURL:false)?.queryItems?.first {$0.name == "after"}?.value
            finish(["service_instance_id":"delivery-instance","conversation_id":"canonical","cursor":"intro_cursor","reset_required":after == nil,"reset_reason":after == nil ? "initial" as Any : NSNull(),"domains":after == nil ? Array(EchoConversationChanges.knownDomains) : []]);return
        }
        if path == "/api/conversation" {
            if Self.hold {Self.waiting.append(self);return}
            let value=Self.snapshot(Self.stage)
            if Self.stage == "pending",Self.completeAfterPendingRead {Self.stage="complete";Self.completeAfterPendingRead=false}
            finish(value);return
        }
        fatalError("Unexpected endpoint: delivery checks must remain synthetic GET-only")
    }
    private func finish(_ value:[String:Any]) {
        client?.urlProtocol(self,didReceive:HTTPURLResponse(url:request.url!,statusCode:200,httpVersion:nil,headerFields:["Content-Type":"application/json"])!,cacheStoragePolicy:.notAllowed)
        client?.urlProtocol(self,didLoad:try! JSONSerialization.data(withJSONObject:value));client?.urlProtocolDidFinishLoading(self)
    }
}
@main struct DeliveryLifecycleChecks {
    @MainActor static func main() async throws {
        var groups=0,suites=[String](),stores=[EchoStore]()
        defer {for store in stores {store.setChangeMonitoringActive(false)};for suite in suites {UserDefaults(suiteName:suite)?.removePersistentDomain(forName:suite)}}
        func check(_ value:Bool) {precondition(value)}
        func pass(_ label:String) {groups+=1;print("PASS: "+label)}
        func waitFor(_ ready:()->Bool) async {
            let deadline=ContinuousClock.now.advanced(by:.seconds(4))
            while !ready(),ContinuousClock.now < deadline {try? await Task.sleep(for:.milliseconds(10))}
            precondition(ready(),"Synthetic delivery event did not arrive within four seconds")
        }
        func decode(_ value:[String:Any]) throws -> EchoConversation {let d=JSONDecoder();d.keyDecodingStrategy = .convertFromSnakeCase;return try d.decode(EchoConversation.self,from:JSONSerialization.data(withJSONObject:value))}
        func makeStore(automatic:Bool=false) -> EchoStore {
            let suite="echo.synthetic.delivery."+UUID().uuidString;suites.append(suite)
            let value=EchoStore(defaults:UserDefaults(suiteName:suite)!,credentialStore:DeliveryVault(),automaticChangePolling:automatic,apiFactory:{origin,auth in
                let c=URLSessionConfiguration.ephemeral;c.protocolClasses=[DeliveryProtocol.self]
                return try EchoAPI(baseURL:origin,session:URLSession(configuration:c),authorization:auth)
            });stores.append(value);return value
        }
        let address="https://synthetic.delivery.invalid",a="echo_pair_"+String(repeating:"A",count:43),b="echo_pair_"+String(repeating:"B",count:43)
        DeliveryProtocol.configure();let today=makeStore(automatic:true)
        check(await today.connectDevice(address:address,token:a))
        // No ChatStreamView is created. Root foreground monitoring must finish
        // a partial intro first discovered by conversation/changes on Today.
        DeliveryProtocol.configure(stage:"pending",completeAfterPendingRead:true);DeliveryProtocol.resetCalls();today.setChangeMonitoringActive(true)
        await waitFor {today.conversation?.messages.first?.displayParts.count == 2}
        precondition(today.conversation?.messages.first?.documentCitations.count == 1)
        let calls=DeliveryProtocol.calls
        precondition(calls.prefix(4) == ["GET /api/conversation/changes","GET /api/conversation","GET /api/conversation/changes","GET /api/conversation"])
        today.setChangeMonitoringActive(false)
        pass("Today/Connections without a chat view: changes publishes partial intro, store resumes it and complete citation becomes visible")

        DeliveryProtocol.configure(stage:"pending");let s=makeStore();check(await s.connectDevice(address:address,token:a));s.setChangeMonitoringActive(true)
        DeliveryProtocol.configure(stage:"complete",hold:true);DeliveryProtocol.resetCalls()
        let first=Task {await s.refreshDelivery()};await waitFor {DeliveryProtocol.heldCount == 1}
        await s.refreshDelivery();precondition(DeliveryProtocol.calls == ["GET /api/conversation"])
        DeliveryProtocol.configure(stage:"complete");DeliveryProtocol.release(DeliveryProtocol.snapshot("complete"));await first.value
        precondition(s.conversation?.messages.first?.displayParts.count == 2)
        pass("concurrent continuation calls share one GET; complete receipt stops further reads")
        DeliveryProtocol.resetCalls();await s.refreshDelivery();precondition(DeliveryProtocol.calls.isEmpty)

        s.conversation=try decode(DeliveryProtocol.snapshot("pending"));DeliveryProtocol.configure(hold:true)
        let background=Task {await s.refreshDelivery()};await waitFor {DeliveryProtocol.heldCount == 1}
        s.setChangeMonitoringActive(false);s.setChangeMonitoringActive(true)
        DeliveryProtocol.configure(stage:"complete");DeliveryProtocol.release(DeliveryProtocol.snapshot("complete"));await background.value
        precondition(s.conversation?.messages.first?.deliveryPending == true)
        s.setChangeMonitoringActive(false);DeliveryProtocol.resetCalls();await s.refreshDelivery();precondition(DeliveryProtocol.calls.isEmpty)
        s.setChangeMonitoringActive(true);await s.refreshDelivery();precondition(s.conversation?.messages.first?.deliveryPending == false)
        pass("leaving and returning foreground invalidates old lifecycle receipt; background never starts a GET")

        s.conversation=try decode(DeliveryProtocol.snapshot("pending"));DeliveryProtocol.configure(hold:true)
        let changed=Task {await s.refreshDelivery()};await waitFor {DeliveryProtocol.heldCount == 1}
        var updated=DeliveryProtocol.snapshot("pending");updated["messages"]=[["id":"intro-message","role":"assistant","text":"较新的本机快照","delivery_pending":true]]
        s.conversation=try decode(updated);DeliveryProtocol.configure(stage:"complete");DeliveryProtocol.release(DeliveryProtocol.snapshot("complete"));await changed.value
        precondition(s.conversation?.messages.first?.text == "较新的本机快照")
        pass("same message ID with a newer accepted conversation revision rejects late delivery content")

        s.conversation=try decode(DeliveryProtocol.snapshot("pending"));let lease=UUID();s.protectChangeReads(lease,active:true);DeliveryProtocol.resetCalls()
        await s.refreshDelivery();precondition(DeliveryProtocol.calls.isEmpty)
        s.protectChangeReads(lease,active:false);let pending=EchoPendingTurn(sessionID:"canonical",text:"合成未决原话",origin:s.scopeIdentity);s.pending=pending
        await s.refreshDelivery();precondition(DeliveryProtocol.calls.isEmpty && s.pending?.requestID == pending.requestID)
        s.pending=nil;s.draft="保留正在写的普通草稿";await s.refreshDelivery()
        precondition(s.draft == "保留正在写的普通草稿" && s.conversation?.messages.first?.deliveryPending == false)
        pass("editor/source-confirm lease and unknown turn block reads; ordinary draft survives successful continuation without sending")

        s.conversation=try decode(DeliveryProtocol.snapshot("pending"));DeliveryProtocol.configure(hold:true)
        let old=Task {await s.refreshDelivery()};await waitFor {DeliveryProtocol.heldCount == 1}
        let oldScope=s.scopeIdentity;DeliveryProtocol.configure(stage:"initial")
        check(await s.connectDevice(address:address,token:b));precondition(s.scopeIdentity != oldScope && s.sessionID == "canonical")
        DeliveryProtocol.release(DeliveryProtocol.snapshot("complete"));await old.value
        precondition(s.deviceConnected && s.conversation?.messages.first?.text == "原有回复" && s.error == nil)
        pass("same canonical conversation with a different device/generation cannot accept old delivery success or failure")
        s.conversation=try decode(DeliveryProtocol.snapshot("pending"));DeliveryProtocol.configure(stage:"deleted");DeliveryProtocol.resetCalls();await s.refreshDelivery()
        precondition(s.conversation?.messages.isEmpty == true && DeliveryProtocol.calls == ["GET /api/conversation"])
        await s.refreshDelivery();precondition(DeliveryProtocol.calls.count == 1);s.setChangeMonitoringActive(false)
        pass("server deletion removes the pending reply; no append, empty reply synthesis or repeated GET")

        DeliveryProtocol.configure(stage:"pending",changes:false);let legacy=makeStore(automatic:true)
        check(await legacy.connectDevice(address:address,token:a));DeliveryProtocol.configure(stage:"complete",changes:false);DeliveryProtocol.resetCalls();legacy.setChangeMonitoringActive(true)
        await waitFor {legacy.conversation?.messages.first?.deliveryPending == false};legacy.setChangeMonitoringActive(false)
        precondition(!legacy.canDiscoverChanges && DeliveryProtocol.calls == ["GET /api/conversation"])
        pass("existing pending reply continues on an older service without changes capability or intro-specific calls")
        print("Host delivery continuation: \(groups)/\(groups) groups passed; actual EchoStore + synthetic URLProtocol/fake vault; no ChatStreamView, SDK, network, model or account.")
    }
}
