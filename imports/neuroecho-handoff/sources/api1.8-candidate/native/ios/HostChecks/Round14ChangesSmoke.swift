import Foundation
import Security
import SwiftUI

/// Test-only trust: the explicitly supplied disposable CA is the ONLY anchor.
/// Hostname and certificate validation remain required. Product trust is unchanged.
private final class DisposableCATrust: NSObject,URLSessionDelegate,@unchecked Sendable {
    let certificate: SecCertificate
    init(_ data: Data) {certificate=SecCertificateCreateWithData(nil,data as CFData)!}
    func urlSession(_ session: URLSession,didReceive challenge: URLAuthenticationChallenge,completionHandler: @escaping @Sendable (URLSession.AuthChallengeDisposition,URLCredential?)->Void) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,challenge.protectionSpace.host == "localhost",let trust=challenge.protectionSpace.serverTrust else {completionHandler(.cancelAuthenticationChallenge,nil);return}
        guard SecTrustSetAnchorCertificates(trust,[certificate] as CFArray) == errSecSuccess,
              SecTrustSetAnchorCertificatesOnly(trust,true) == errSecSuccess,
              SecTrustSetPolicies(trust,SecPolicyCreateSSL(true,"localhost" as CFString)) == errSecSuccess,
              SecTrustEvaluateWithError(trust,nil) else {var failure:CFError?;_ = SecTrustEvaluateWithError(trust,&failure);print("TEST_CA_VALIDATION_REJECTED:",failure.map {CFErrorCopyDescription($0) as String} ?? "unknown");completionHandler(.cancelAuthenticationChallenge,nil);return}
        completionHandler(.useCredential,URLCredential(trust:trust))
    }
}
@MainActor private final class SmokeVault: EchoDeviceCredentialStore {
    var values=[String:String](),removals=0
    func save(_ token: String,for profile: EchoDeviceProfile) throws {values[profile.vaultAccount]=token}
    func read(for profile: EchoDeviceProfile) throws -> String {guard let value=values[profile.vaultAccount] else {throw EchoCredentialStoreError.missing};return value}
    func remove(for profile: EchoDeviceProfile) throws {values.removeValue(forKey:profile.vaultAccount);removals+=1}
}
@main struct Round14ChangesSmoke {
    @MainActor static func main() async {
        var groups=0
        func check(_ value: Bool,file:StaticString=#fileID,line:UInt=#line) {precondition(value,"R14 actual HTTPS invariant",file:file,line:line)}
        func pass(_ value:String) {groups+=1;print("PASS: "+value)}
        do {
            let input=try JSONSerialization.jsonObject(with:FileHandle.standardInput.readDataToEndOfFile()) as! [String:String]
            let address=input["remote"]!,owner=input["owner"]!,tokenA=input["token_a"]!,tokenB=input["token_b"]!
            check(URL(string:address)?.host == "localhost" && URL(string:owner)?.host == "127.0.0.1")
            let trust=DisposableCATrust(Data(base64Encoded:input["ca_der"]!)!),session=URLSession(configuration:.ephemeral,delegate:trust,delegateQueue:nil)
            defer {session.invalidateAndCancel()}
            let suiteA="echo.synthetic.r14.A."+UUID().uuidString,suiteB="echo.synthetic.r14.B."+UUID().uuidString
            let defaultsA=UserDefaults(suiteName:suiteA)!,defaultsB=UserDefaults(suiteName:suiteB)!,vaultA=SmokeVault(),vaultB=SmokeVault()
            defer {defaultsA.removePersistentDomain(forName:suiteA);defaultsB.removePersistentDomain(forName:suiteB)}
            func store(_ defaults:UserDefaults,_ vault:SmokeVault) -> EchoStore {EchoStore(defaults:defaults,credentialStore:vault,automaticChangePolling:false,apiFactory:{url,auth in try EchoAPI(baseURL:url,session:session,authorization:auth)})}
            let a=store(defaultsA,vaultA),b=store(defaultsB,vaultB)
            check(await a.connectDevice(address:address,token:tokenA));check(await b.connectDevice(address:address,token:tokenB))
            check(a.sessionID == b.sessionID && a.deviceProfile?.deviceID != b.deviceProfile?.deviceID && a.scopeIdentity != b.scopeIdentity)
            a.setChangeMonitoringActive(true);await a.checkForChanges()
            check(a.heldChangeCursor != nil && a.remoteReadRevision == 1 && a.changeSyncStatus == .updated)
            let sid=a.sessionID!,peer=b.api
            print("HOST_R14_CHANGES: actual macOS EchoStore/URLSession to fresh paired TLS runner; two devices, fake vault, scoped CA+hostname verification. NOT iOS SDK/device/cloud sync.")
            pass("two real paired clients verify same canonical but separate device/generation, then changes-first baseline commits")
            let memory=try await peer.addMemory(sessionID:sid,text:"R14 peer 合成记忆")
            await a.checkForChanges();check(a.conversation?.memories.contains {$0.id == memory.id} == true)
            let beforeEdit=a.heldChangeCursor,lease=UUID();a.protectChangeReads(lease,active:true);a.draft="A本机尚未发送的原话"
            let edited=try await peer.updateMemory(id:memory.id,text:"R14 peer 已修改",expectedVersion:memory.version)
            await a.checkForChanges();check(a.heldChangeCursor == beforeEdit && a.changesWaiting && a.draft == "A本机尚未发送的原话" && a.conversation?.memories.first {$0.id == memory.id}?.text == memory.text)
            a.protectChangeReads(lease,active:false);a.draft="";await a.checkForChanges()
            check(a.conversation?.memories.first {$0.id == memory.id}?.version == edited.version && a.heldChangeCursor != beforeEdit)
            pass("peer memory create/edit is discovered; active edit/local draft preserves old view/cursor until safe explicit check")
            try await peer.deleteMemory(id:edited.id,expectedVersion:edited.version);await a.checkForChanges()
            check(a.conversation?.memories.contains {$0.id == edited.id} == false)
            pass("peer memory deletion replaces local snapshot rather than keeping or appending deleted row")
            let attached=try await peer.attachFiles([EchoSelectedFile(name:"R14-peer.txt",text:"本人选择并预览确认的合成资料")],sessionID:sid)
            let source=attached.context!.sources!.first!;await a.checkForChanges();check(a.sources.contains {$0.id == source.id})
            try await peer.revokeSource(id:source.id,sessionID:sid);await a.checkForChanges();check(!a.sources.contains {$0.id == source.id})
            pass("peer selected-file confirmation and withdrawal are reflected as full source replacements")
            var mood=EchoMoodDraft(origin:peer.storageNamespace,sessionID:sid,day:"2026-10-28")
            mood.x=0.4;mood.y = -0.2;mood.xSelected=true;mood.ySelected=true;mood.note="R14 peer 合成日记";mood.dirty=true
            let mutation=try EchoMoodMutation(kind:.save,draft:mood).preparedForLedger();_ = try await peer.applyMoodOperation(sessionID:sid,mutation:mutation)
            await a.checkForChanges();check(a.remoteMoods.count == 1 && a.remoteMoods.first?.note == mood.note)
            let deleting=try EchoMoodMutation(kind:.delete,draft:EchoMoodDraft(origin:peer.storageNamespace,sessionID:sid,day:mood.day,record:a.remoteMoods[0])).preparedForLedger();_ = try await peer.applyMoodOperation(sessionID:sid,mutation:deleting)
            await a.checkForChanges();check(a.remoteMoods.isEmpty)
            pass("peer mood ledger save/delete invalidates and refreshes diary cache without creating chat or memory")
            let followup=try await peer.createFollowup(EchoPendingFollowup(sessionID:sid,content:"R14 peer 合成被动待办",date:Date().addingTimeInterval(3600),origin:peer.storageNamespace,repeatRule:"once",timeZone:"UTC",allowContact:false))
            await a.checkForChanges();check(a.followups.contains {$0.id == followup.id})
            _ = try await peer.changeFollowup(followup,status:"cancelled");await a.checkForChanges();check(a.followups.first {$0.id == followup.id}?.status == "cancelled")
            let boundary=try await peer.boundary(sessionID:sid)
            let paused=try await peer.updateBoundary(sessionID:sid,expectedRevision:boundary.revision,mode:"paused",until:nil,timeZone:"UTC")
            await a.checkForChanges();check(a.boundary?.mode == "paused")
            _ = try await peer.updateBoundary(sessionID:sid,expectedRevision:paused.revision,mode:"active",until:nil,timeZone:"UTC");await a.checkForChanges();check(a.boundary?.mode == "active")
            pass("passive followup creation/cancellation and boundary pause/resume refresh without contact claim or notification")
            let pending=EchoPendingTurn(sessionID:sid,text:"R14 未实际发出的unknown合成原文",origin:a.scopeIdentity);a.pending=pending
            let unknownCursor=a.heldChangeCursor,extra=try await peer.addMemory(sessionID:sid,text:"R14 unknown期间对端新增")
            await a.checkForChanges();check(a.pending?.requestID == pending.requestID && a.heldChangeCursor == unknownCursor && a.changesWaiting)
            a.pending=nil;await a.checkForChanges();check(a.conversation?.memories.contains {$0.id == extra.id} == true)
            pass("synthetic local unknown is retained while peer changes wait; clearing own never-sent fixture permits GET-only adoption")
            a.setChangeMonitoringActive(false);let backgroundCursor=a.heldChangeCursor
            let bg=try await peer.addMemory(sessionID:sid,text:"R14 background期间对端新增");await a.checkForChanges()
            check(a.heldChangeCursor == backgroundCursor && a.conversation?.memories.contains {$0.id == bg.id} == false)
            a.setChangeMonitoringActive(true);await a.checkForChanges();check(a.conversation?.memories.contains {$0.id == bg.id} == true)
            pass("inactive client performs no poll/apply; foreground resumes from original cursor and reads peer updates")
            // Prove backend's metadata detects a write between staged read and check.
            let candidate=try await a.api.conversationChanges(after:a.heldChangeCursor),staged=try await a.api.conversation()
            let during=try await peer.addMemory(sessionID:sid,text:"R14 between-read-and-check")
            let stable=try await a.api.conversationChanges(after:candidate.cursor)
            check(staged.memories.contains {$0.id == during.id} == false && !stable.domains.isEmpty)
            await a.checkForChanges();check(a.conversation?.memories.contains {$0.id == during.id} == true)
            pass("actual interleaved peer write after snapshot is exposed by stability GET; later Store check re-reads it")
            var revoke=URLRequest(url:URL(string:owner+"/api/paired-devices/"+a.deviceProfile!.deviceID+"/revoke")!);revoke.httpMethod="POST";revoke.setValue("application/json",forHTTPHeaderField:"Content-Type");revoke.httpBody=Data(#"{"confirmed":true}"#.utf8)
            let (_,response)=try await URLSession(configuration:.ephemeral).data(for:revoke);check((response as! HTTPURLResponse).statusCode == 200)
            await a.checkForChanges();for _ in 0..<100 {await Task.yield()}
            check(!a.deviceConnected && a.conversation == nil && a.heldChangeCursor == nil && vaultA.values.isEmpty)
            check(b.deviceConnected && vaultB.values.count == 1)
            pass("revoked A receives real401 and clears only its exact fake credential/private cursor; B remains independent")
            print("HOST_R14_CHANGES_PASS: \(groups) workflow groups; no model/chat POST/CLI/hardware/global CA or real Keychain. Temporary synthetic data only.")
        } catch {print("HOST_R14_CHANGES_FAIL:",error.localizedDescription);exit(1)}
    }
}
