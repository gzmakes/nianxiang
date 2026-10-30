import Foundation
import SwiftUI

@MainActor private final class ChangesVault: EchoDeviceCredentialStore {
    var values=[String:String](),removed=0,reads=0
    func save(_ value: String,for profile: EchoDeviceProfile) throws {values[profile.vaultAccount]=value}
    func read(for profile: EchoDeviceProfile) throws -> String {reads+=1;guard let value=values[profile.vaultAccount] else {throw EchoCredentialStoreError.missing};return value}
    func remove(for profile: EchoDeviceProfile) throws {values.removeValue(forKey:profile.vaultAccount);removed+=1}
}
private final class ChangesProtocol: URLProtocol {
    static var calls=[String](),afterValues=[String?](),cursor="c0",domains=Array(EchoConversationChanges.knownDomains)
    static var instance="synthetic-instance",supported=true,deleted=false,failPath="",failStatus=503
    static var holdSnapshot=false,held=[ChangesProtocol](),changeAfterSnapshot=false,unstableCursorOnly=false
    static var message="initial",malformedSnapshot=false,holdCapabilitiesForA=false
    static func reset() {calls=[];afterValues=[];cursor="c0";domains=Array(EchoConversationChanges.knownDomains);instance="synthetic-instance";supported=true;deleted=false;failPath="";failStatus=503;holdSnapshot=false;held=[];changeAfterSnapshot=false;unstableCursorOnly=false;message="initial";malformedSnapshot=false;holdCapabilitiesForA=false}
    override class func canInit(with request: URLRequest)->Bool {true}
    override class func canonicalRequest(for request: URLRequest)->URLRequest {request}
    override func stopLoading() {}
    static func snapshot() -> [String:Any] {
        ["session":["id":"canonical"],"messages":deleted ? [] : [["id":"msg","role":"assistant","text":message]],"memories":deleted ? [] : [["id":"memory","kind":"fact","text":message,"status":"candidate","version":1,"source":"本人合成"]],"context":["sources":deleted ? [] : [["id":"source","label":"合成所选文件","items":[]]]]]
    }
    override func startLoading() {
        let path=request.url!.path;Self.calls.append((request.httpMethod ?? "GET")+" "+path)
        precondition(request.httpMethod == "GET","Refresh checks cannot issue a mutation/model/CLI request")
        if path == Self.failPath {
            finish(["detail":"synthetic rejected","error_code":Self.failStatus == 401 ? "paired_authentication_required" : "synthetic_unavailable"],status:Self.failStatus);return
        }
        if path == "/api/paired-device" {
            let id=request.value(forHTTPHeaderField:"Authorization")!.hasSuffix(String(repeating:"B",count:43)) ? "B" : "A"
            finish(["service_instance_id":Self.instance,"conversation_id":"canonical","scope":"personal_core","local_actions_allowed":false,"device":["id":id,"label":"合成设备","created_at":"2026-01-01T00:00:00Z","expires_at":"2099-01-01T00:00:00Z","revoked_at":NSNull()]]);return
        }
        if path == "/api/capabilities", Self.holdCapabilitiesForA, request.value(forHTTPHeaderField:"Authorization")?.hasSuffix(String(repeating:"A",count:43)) == true {Self.held.append(self);return}
        if path == "/api/capabilities" {finish(["contract_version":"1.7.0","deployment_mode":"paired_single_owner","service_platform":"darwin","features":["conversation_change_cursor":Self.supported,"daily_mood_entries":true,"in_app_one_time_followups":true,"companion_boundaries":true],"platform_status":[:],"connection_status":"not_probed"]);return}
        if path == "/api/conversation/changes" {
            let after=URLComponents(url:request.url!,resolvingAgainstBaseURL:false)?.queryItems?.first {$0.name == "after"}?.value
            Self.afterValues.append(after)
            let empty=after == Self.cursor
            let returned=Self.unstableCursorOnly && empty ? "different_empty_cursor" : Self.cursor
            finish(["service_instance_id":Self.instance,"conversation_id":"canonical","cursor":returned,"reset_required":after == nil,"reset_reason":after == nil ? "initial" as Any : NSNull(),"domains":after == nil ? Array(EchoConversationChanges.knownDomains) : empty ? [] : Self.domains]);return
        }
        if path == "/api/conversation" {
            if Self.holdSnapshot {Self.held.append(self);return}
            if Self.malformedSnapshot {finish(["session":["id":"canonical"],"messages":[],"memories":[]]);return}
            let value=Self.snapshot();if Self.changeAfterSnapshot {Self.cursor="changed_during_read";Self.message="later";Self.changeAfterSnapshot=false};finish(value);return
        }
        if path == "/api/moods" {finish(["moods":Self.deleted ? [] : [["date":"2026-10-28","x":0.2,"y":0.4,"note":Self.message,"updated_at":"2026-10-30T00:00:00Z"]]]);return}
        if path == "/api/followups" {finish(["followups":[]]);return}
        if path == "/api/companion-boundary" {finish(["revision":1,"mode":"active","until":NSNull(),"time_zone":"UTC","suppression_revision":0]);return}
        fatalError("Unexpected endpoint in read-only refresh checks")
    }
    func finish(_ value:[String:Any],status:Int=200) {
        client?.urlProtocol(self,didReceive:HTTPURLResponse(url:request.url!,statusCode:status,httpVersion:nil,headerFields:["Content-Type":"application/json"])!,cacheStoragePolicy:.notAllowed)
        client?.urlProtocol(self,didLoad:try! JSONSerialization.data(withJSONObject:value));client?.urlProtocolDidFinishLoading(self)
    }
}
@main struct ChangeRefreshLifecycleChecks {
    static let address="https://synthetic.changes.invalid",tokenA="echo_pair_"+String(repeating:"A",count:43),tokenB="echo_pair_"+String(repeating:"B",count:43)
    static func receiptForArchive() throws -> EchoPairedDevice {
        let d=JSONDecoder();d.keyDecodingStrategy = .convertFromSnakeCase
        return try d.decode(EchoPairedDevice.self,from:Data(#"{"service_instance_id":"synthetic-instance","conversation_id":"canonical","scope":"personal_core","local_actions_allowed":false,"device":{"id":"A","label":"synthetic","created_at":"2026-01-01T00:00:00Z","expires_at":"2099-01-01T00:00:00Z","revoked_at":null}}"#.utf8))
    }
    @MainActor static func main() async {
        var groups=0
        func check(_ value:Bool,file:StaticString=#fileID,line:UInt=#line) {precondition(value,"Changes safety invariant",file:file,line:line)}
        func pass(_ text:String) {groups+=1;print("PASS: "+text)}
        let suite="echo.synthetic.changes."+UUID().uuidString,defaults=UserDefaults(suiteName:suite)!,vault=ChangesVault()
        defer {defaults.removePersistentDomain(forName:suite)}
        func store() -> EchoStore {EchoStore(defaults:defaults,credentialStore:vault,automaticChangePolling:false,apiFactory:{origin,auth in let c=URLSessionConfiguration.ephemeral;c.protocolClasses=[ChangesProtocol.self];return try EchoAPI(baseURL:origin,session:URLSession(configuration:c),authorization:auth)})}
        ChangesProtocol.reset();let s=store();check(await s.connectDevice(address:address,token:tokenA));s.setChangeMonitoringActive(true);ChangesProtocol.calls=[]
        await s.checkForChanges()
        check(s.heldChangeCursor == "c0" && s.changeSyncStatus == .updated && s.remoteMoods.count == 1)
        check(ChangesProtocol.calls == ["GET /api/conversation/changes","GET /api/conversation","GET /api/followups","GET /api/companion-boundary","GET /api/moods","GET /api/conversation/changes"])
        pass("baseline stages changes first, complete GETs next, stability last and atomically acknowledges first cursor")
        ChangesProtocol.calls=[];let revision=s.remoteReadRevision;await s.checkForChanges()
        check(ChangesProtocol.calls == ["GET /api/conversation/changes"] && s.remoteReadRevision == revision && s.heldChangeCursor == "c0")
        pass("unchanged cursor performs one metadata GET without unnecessary snapshot reads")
        ChangesProtocol.cursor="c1";ChangesProtocol.domains=["messages","memories","sources","moods"];ChangesProtocol.deleted=true;await s.checkForChanges()
        check(s.conversation?.messages.isEmpty == true && s.conversation?.memories.isEmpty == true && s.sources.isEmpty && s.remoteMoods.isEmpty && s.heldChangeCursor == "c1")
        pass("remote deletions and source withdrawal replace arrays, never append stale messages/memories/sources/moods")
        ChangesProtocol.cursor="c2";ChangesProtocol.deleted=false;ChangesProtocol.message="all-or-nothing";ChangesProtocol.failPath="/api/moods";await s.checkForChanges()
        check(s.heldChangeCursor == "c1" && s.conversation?.messages.isEmpty == true && s.changeSyncStatus == .offline)
        ChangesProtocol.failPath="";await s.checkForChanges();check(s.heldChangeCursor == "c2" && s.conversation?.messages.first?.text == "all-or-nothing")
        pass("failed dependent domain leaves all current snapshots/cursor unchanged; later full read can recover")
        ChangesProtocol.cursor="c3";let lease=UUID();s.protectChangeReads(lease,active:true);ChangesProtocol.calls=[];await s.checkForChanges()
        check(s.heldChangeCursor == "c2" && s.changesWaiting && ChangesProtocol.calls == ["GET /api/conversation/changes"])
        s.protectChangeReads(lease,active:false);await s.checkForChanges();check(s.heldChangeCursor == "c3")
        pass("active edit/upload lease discovers but defers content; closing permits safe full re-read")
        ChangesProtocol.cursor="c4";s.draft="正在写的原话";ChangesProtocol.calls=[];await s.checkForChanges()
        check(s.draft == "正在写的原话" && s.heldChangeCursor == "c3" && ChangesProtocol.calls.count == 1)
        s.draft="";await s.checkForChanges();check(s.heldChangeCursor == "c4")
        pass("ordinary chat composition is retained and never overwritten by passive refresh")
        ChangesProtocol.cursor="c5";let pending=EchoPendingTurn(sessionID:"canonical",text:"unknown原请求",origin:s.scopeIdentity);s.pending=pending;ChangesProtocol.calls=[];await s.checkForChanges()
        check(s.pending?.requestID == pending.requestID && s.heldChangeCursor == "c4" && ChangesProtocol.calls == ["GET /api/conversation/changes"])
        s.pending=nil;await s.checkForChanges();check(s.heldChangeCursor == "c5")
        pass("unknown turn blocks adoption and cursor advancement; no ledger replay/cancel/POST occurs")
        ChangesProtocol.cursor="c6";ChangesProtocol.holdSnapshot=true
        let racing=Task {await s.checkForChanges()};for _ in 0..<5000 {if !ChangesProtocol.held.isEmpty {break};await Task.yield()};check(ChangesProtocol.held.count == 1)
        let held=ChangesProtocol.held.removeFirst(),calls=ChangesProtocol.calls.count
        await s.checkForChanges();check(ChangesProtocol.calls.count == calls)
        s.draft="读取期间开始编辑";ChangesProtocol.holdSnapshot=false;held.finish(ChangesProtocol.snapshot());await racing.value
        check(s.heldChangeCursor == "c5" && s.draft == "读取期间开始编辑")
        s.draft="";await s.checkForChanges();check(s.heldChangeCursor == "c6")
        pass("single-flight poll plus mid-read edit barrier discards all staged data and keeps exact draft")
        ChangesProtocol.cursor="c7";ChangesProtocol.changeAfterSnapshot=true;await s.checkForChanges()
        check(s.heldChangeCursor == "c6" && s.changesWaiting)
        await s.checkForChanges();check(s.heldChangeCursor == "changed_during_read" && s.conversation?.messages.first?.text == "later")
        pass("second changes detects concurrent write; no mixed snapshot or second-cursor skipping; next bounded poll re-reads")
        ChangesProtocol.cursor="c8";ChangesProtocol.unstableCursorOnly=true;await s.checkForChanges()
        check(s.heldChangeCursor == "changed_during_read");ChangesProtocol.unstableCursorOnly=false;await s.checkForChanges();check(s.heldChangeCursor == "c8")
        pass("unexpected distinct empty second cursor cannot advance past an unverified batch")
        ChangesProtocol.unstableCursorOnly=true;await s.checkForChanges();check(s.heldChangeCursor == "c8");ChangesProtocol.unstableCursorOnly=false
        pass("unexpected distinct empty first cursor cannot skip all domain reads")
        ChangesProtocol.cursor="c8malformed";ChangesProtocol.malformedSnapshot=true;await s.checkForChanges();check(s.heldChangeCursor == "c8" && s.conversation?.messages.first?.text == "later")
        ChangesProtocol.malformedSnapshot=false;await s.checkForChanges();check(s.heldChangeCursor == "c8malformed")
        pass("missing context collection is not mistaken for a legitimate null/withdrawal or acknowledged")
        ChangesProtocol.cursor="c9";ChangesProtocol.domains=["future_domain"];ChangesProtocol.calls=[];await s.checkForChanges()
        check(s.heldChangeCursor == "c8malformed" && ChangesProtocol.calls == ["GET /api/conversation/changes"] && s.changeSyncStatus == .offline)
        ChangesProtocol.domains=["messages"];await s.checkForChanges();check(s.heldChangeCursor == "c9")
        pass("future unknown metadata is preserved but not silently acknowledged or applied")
        ChangesProtocol.cursor="c10";ChangesProtocol.holdSnapshot=true;let background=Task {await s.checkForChanges()}
        for _ in 0..<5000 {if !ChangesProtocol.held.isEmpty {break};await Task.yield()};check(ChangesProtocol.held.count == 1)
        let bg=ChangesProtocol.held.removeFirst();s.setChangeMonitoringActive(false);let countBefore=ChangesProtocol.calls.count
        ChangesProtocol.holdSnapshot=false;bg.finish(ChangesProtocol.snapshot());await background.value;await s.checkForChanges()
        check(s.heldChangeCursor == "c9" && ChangesProtocol.calls.count == countBefore)
        s.setChangeMonitoringActive(true);await s.checkForChanges();check(s.heldChangeCursor == "c10")
        pass("background invalidates in-flight receipt and starts no further GETs; foreground resumes from held cursor")
        ChangesProtocol.cursor="c11";ChangesProtocol.holdSnapshot=true;let old=Task {await s.checkForChanges()}
        for _ in 0..<5000 {if !ChangesProtocol.held.isEmpty {break};await Task.yield()};check(ChangesProtocol.held.count == 1)
        let oldHeld=ChangesProtocol.held.removeFirst();ChangesProtocol.holdSnapshot=false;let oldScope=s.scopeIdentity
        check(await s.connectDevice(address:address,token:tokenB));let newScope=s.scopeIdentity
        oldHeld.finish(ChangesProtocol.snapshot());await old.value
        check(newScope != oldScope && s.heldChangeCursor == nil && s.deviceConnected && s.changeSyncStatus != .offline)
        await s.checkForChanges();check(s.heldChangeCursor == "c11")
        pass("same-canonical device/generation switch cannot inherit old cursor or old response/error state")
        ChangesProtocol.instance="other-instance";ChangesProtocol.cursor="c12";ChangesProtocol.calls=[];await s.checkForChanges()
        check(s.heldChangeCursor == "c11" && s.deviceConnected && ChangesProtocol.calls.count == 1)
        ChangesProtocol.instance="synthetic-instance"
        pass("wrong metadata instance is rejected before snapshot and never silently rebinds current credential")
        ChangesProtocol.failPath="/api/conversation/changes";ChangesProtocol.failStatus=401;await s.checkForChanges();for _ in 0..<100 {await Task.yield()}
        check(!s.deviceConnected && s.conversation == nil && s.heldChangeCursor == nil && vault.removed == 1)
        pass("actual Store auth callback preserves R13 precise401 cleanup and invalidates private cursor/RAM")
        ChangesProtocol.reset();ChangesProtocol.supported=false;let legacy=store();check(await legacy.connectDevice(address:address,token:tokenA));legacy.setChangeMonitoringActive(true);ChangesProtocol.calls=[]
        await legacy.refreshFromForeground();check(!legacy.canDiscoverChanges && !ChangesProtocol.calls.contains { $0.contains("/changes") } && legacy.conversation != nil)
        pass("service without advertised capability retains explicit legacy refresh and makes no changes request")
        ChangesProtocol.reset();ChangesProtocol.failPath="/api/capabilities";let recovery=store()
        check(await recovery.connectDevice(address:address,token:tokenA));recovery.setChangeMonitoringActive(true)
        check(recovery.deviceConnected && recovery.conversation != nil && recovery.capabilities == nil && recovery.capabilityReadFailed && recovery.changeNoticeKind == .capabilitiesUnknown)
        pass("failed initial capability GET keeps connection truthful and shows unknown, never unsupported")
        ChangesProtocol.failPath="";let protected=UUID();recovery.protectChangeReads(protected,active:true);ChangesProtocol.calls=[]
        await recovery.checkUpdatesExplicitly()
        check(recovery.canDiscoverChanges && !recovery.capabilityReadFailed && recovery.changeNoticeKind == .pending && recovery.heldChangeCursor == nil)
        check(ChangesProtocol.calls == ["GET /api/capabilities","GET /api/conversation/changes"])
        await recovery.checkUpdatesExplicitly();check(recovery.heldChangeCursor == nil)
        recovery.protectChangeReads(protected,active:false);await recovery.checkForChanges();check(recovery.heldChangeCursor == "c0")
        pass("explicit capability recovery uses GET and preserves edit lease until the editor actually closes")
        ChangesProtocol.failPath="/api/conversation/changes";await recovery.checkForChanges()
        check(!recovery.changesWaiting && recovery.changeNoticeKind == .offline)
        ChangesProtocol.failPath="";ChangesProtocol.cursor="pending-then-offline";recovery.protectChangeReads(protected,active:true);await recovery.checkForChanges()
        ChangesProtocol.failPath="/api/conversation/changes";await recovery.checkForChanges()
        check(recovery.changesWaiting && recovery.changeNoticeKind == .offline)
        recovery.protectChangeReads(protected,active:false);ChangesProtocol.failPath="";await recovery.checkForChanges()
        pass("first failure and pending-then-failure both display offline accurately without losing cursor protection")
        ChangesProtocol.failPath="/api/capabilities";ChangesProtocol.calls=[];await recovery.checkUpdatesExplicitly()
        check(recovery.capabilities != nil && recovery.canDiscoverChanges && recovery.capabilityReadFailed && ChangesProtocol.calls == ["GET /api/capabilities"])
        pass("failed explicit capability reread keeps last verified features and performs no fallback mutation")
        ChangesProtocol.reset();ChangesProtocol.supported=false;let oldService=store();check(await oldService.connectDevice(address:address,token:tokenA));oldService.setChangeMonitoringActive(true)
        oldService.protectChangeReads(protected,active:true);ChangesProtocol.calls=[];await oldService.checkUpdatesExplicitly()
        check(oldService.changeNoticeKind == .unsupported && ChangesProtocol.calls == ["GET /api/capabilities"])
        oldService.protectChangeReads(protected,active:false);ChangesProtocol.calls=[];await oldService.checkUpdatesExplicitly()
        check(ChangesProtocol.calls.contains("GET /api/conversation") && !ChangesProtocol.calls.contains {$0.contains("/changes")})
        pass("known old service keeps explicit snapshot fallback but never bypasses active editor protection")
        ChangesProtocol.holdCapabilitiesForA=true;ChangesProtocol.calls=[]
        let backgroundCheck=Task {await oldService.checkUpdatesExplicitly()}
        for _ in 0..<5000 {if !ChangesProtocol.held.isEmpty {break};await Task.yield()};check(ChangesProtocol.held.count == 1)
        let backgroundReceipt=ChangesProtocol.held.removeFirst();oldService.setChangeMonitoringActive(false);ChangesProtocol.holdCapabilitiesForA=false
        backgroundReceipt.finish(["contract_version":"1.6.0","deployment_mode":"remote_app","service_platform":"darwin","features":[:],"platform_status":[:],"connection_status":"not_probed"])
        await backgroundCheck.value
        check(ChangesProtocol.calls == ["GET /api/capabilities"] && !oldService.readingCapabilities)
        pass("leaving foreground during explicit capability check prevents subsequent legacy snapshot GETs")
        ChangesProtocol.reset();let race=store();check(await race.connectDevice(address:address,token:tokenA));race.setChangeMonitoringActive(true)
        ChangesProtocol.holdCapabilitiesForA=true;let late=Task {await race.rereadCapabilities()}
        for _ in 0..<5000 {if !ChangesProtocol.held.isEmpty {break};await Task.yield()};check(ChangesProtocol.held.count == 1)
        let lateResponse=ChangesProtocol.held.removeFirst();ChangesProtocol.holdCapabilitiesForA=false
        check(await race.connectDevice(address:address,token:tokenB));let newProfile=race.deviceProfile!
        lateResponse.finish(["detail":"synthetic late failure"],status:503);check(!(await late.value))
        check(race.deviceProfile == newProfile && race.canDiscoverChanges && !race.capabilityReadFailed && !race.readingCapabilities)
        pass("late capability failure from same-canonical old device cannot downgrade or lock new identity")
        race.draft="原身份的未发送文字";let oldProfile=race.deviceProfile!
        let archivedPending=EchoPendingTurn(sessionID:"canonical",text:"旧身份的未决原话",origin:oldProfile.namespace)
        let pendingKey="echo.native.pending-turn.v1."+Data(oldProfile.namespace.utf8).base64EncodedString()
        defaults.set(try! JSONEncoder().encode(archivedPending),forKey:pendingKey)
        race.disconnectDevice(forgetCredential:true);check(race.forgottenDeviceGenerations.contains(oldProfile.credentialGeneration))
        check(await race.connectDevice(address:address,token:tokenA));race.draft="新身份的草稿"
        let callsBefore=ChangesProtocol.calls.count,vaultReads=vault.reads,before=defaults.dictionaryRepresentation() as NSDictionary
        let archive=race.localDraftArchive(for:oldProfile)!
        check(archive.entries.map(\.text).contains("原身份的未发送文字") && archive.entries.map(\.text).contains("旧身份的未决原话"))
        check(ChangesProtocol.calls.count == callsBefore && vault.reads == vaultReads && (defaults.dictionaryRepresentation() as NSDictionary) == before)
        check(race.draft == "新身份的草稿" && race.pending == nil && race.deviceConnected)
        pass("forgotten old identity has a real read-only archive with zero GET, vault access, writes, migration or replay")
        let foreign=EchoDeviceProfile(origin:oldProfile.origin,receipt:try! receiptForArchive())
        check(race.localDraftArchive(for:foreign) == nil)
        pass("unknown profile cannot supply arbitrary local draft namespace")
        print("Host R15 change refresh / usability: \(groups)/\(groups) groups passed; actual Store + fake vault/URLProtocol, GET-only, no iOS SDK or real network.")
    }
}
