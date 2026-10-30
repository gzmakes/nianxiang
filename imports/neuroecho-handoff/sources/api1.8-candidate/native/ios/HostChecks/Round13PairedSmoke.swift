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
@main struct Round13PairedSmoke {
    @MainActor static func main() async {
        func check(_ value: Bool,file: StaticString = #fileID,line: UInt = #line) {precondition(value,"Paired smoke invariant",file:file,line:line)}
        do {
            let data=FileHandle.standardInput.readDataToEndOfFile(),input=try JSONSerialization.jsonObject(with:data) as! [String:String]
            let address=input["remote"]!,owner=input["owner"]!,token=input["token"]!,device=input["device"]!,ca=Data(base64Encoded:input["ca_der"]!)!
            check(URL(string:address)?.host == "localhost" && URL(string:owner)?.host == "127.0.0.1")
            print("HOST_R13_PAIRED: real URLSession HTTPS to fresh loopback runner; test-only CA/hostname validation, fake vault, NOT iOS/Keychain/device.")
            let untrusted=try EchoAPI(baseURL:address,authorization:EchoDeviceAuthorization(token:token))
            do {_=try await untrusted.pairedDevice();fatalError("Product default trust must reject disposable untrusted certificate")} catch {check(!(error is EchoAPIError));print("PASS: unchanged product trust rejects the uninstalled self-signed certificate.")}
            let trust=DisposableCATrust(ca),session=URLSession(configuration:.ephemeral,delegate:trust,delegateQueue:nil)
            let redirected=try EchoAPI(baseURL:input["redirect"]!,session:session,authorization:EchoDeviceAuthorization(token:token))
            for status in [302,307,308] {
                do {_=try await redirected.pairedDevice();fatalError("Redirect must not be followed")} catch {check((error as? EchoAPIError)?.statusCode == status)}
            }
            print("PASS: actual HTTPS302/307/308 are rejected by the product task delegate; target listener audit follows.")
            let verifier=try EchoAPI(baseURL:address,session:session,authorization:EchoDeviceAuthorization(token:token))
            let receipt=try await verifier.pairedDevice();check(receipt.isValid && receipt.device.id == device)
            print("PASS: actual typed device receipt decoded over TLS with scoped CA + hostname evaluation.")
            let suite="echo.synthetic.r13.https."+UUID().uuidString,defaults=UserDefaults(suiteName:suite)!,vault=SmokeVault()
            defer {defaults.removePersistentDomain(forName:suite);session.invalidateAndCancel()}
            let store=EchoStore(defaults:defaults,credentialStore:vault,automaticChangePolling:false,apiFactory:{url,auth in try EchoAPI(baseURL:url,session:session,authorization:auth)})
            check(await store.connectDevice(address:address,token:token));store.setChangeMonitoringActive(true);let profile=store.deviceProfile!,api=store.api,sid=receipt.conversationId
            check(store.sessionID == sid && profile.serviceInstanceID == receipt.serviceInstanceId && vault.values.count == 1 && store.actions.isEmpty)
            let capabilities=try await api.capabilities(),catalog=try await api.sources()
            check(capabilities.features["source_cli_read"] == false && capabilities.features["service_apple_calendar_reminders"] == false && catalog.map(\.id) == ["local_files"])
            do {_=try await api.actions(sessionID:sid);fatalError("Remote actions must fail before send")} catch {check((error as? EchoAPIError)?.statusCode == nil)}
            print("PASS: actual EchoStore activates only verified instance/canonical; safe source catalogue exposes upload only, actions remain blocked.")
            let memory=try await api.addMemory(sessionID:sid,text:"R13-iOS-HTTPS 合成候选"),updated=try await api.updateMemory(id:memory.id,text:"R13-iOS-HTTPS 合成纠正",expectedVersion:memory.version)
            check(updated.version > memory.version)
            do {_=try await api.updateMemory(id:memory.id,text:"不应覆盖",expectedVersion:memory.version);fatalError("Old CAS must conflict")} catch {check((error as? EchoAPIError)?.statusCode == 409)}
            try await api.deleteMemory(id:updated.id,expectedVersion:updated.version)
            print("PASS: real paired memory candidate/update/CAS409/delete stays in the same canonical conversation.")
            var draft=EchoMoodDraft(origin:api.storageNamespace,sessionID:sid,day:"2026-10-28")
            draft.x=0.2;draft.y = -0.3;draft.xSelected=true;draft.ySelected=true;draft.note="R13 合成手动日记";draft.dirty=true
            let mutation=try EchoMoodMutation(kind:.save,draft:draft).preparedForLedger(),saved=try await api.applyMoodOperation(sessionID:sid,mutation:mutation)
            check(saved.state == "applied")
            let duplicate=try await api.applyMoodOperation(sessionID:sid,mutation:mutation);check(duplicate == saved)
            let rows=try await api.moods(sessionID:sid);check(rows.count == 1 && rows[0].note == draft.note)
            let deletion=try EchoMoodMutation(kind:.delete,draft:EchoMoodDraft(origin:api.storageNamespace,sessionID:sid,day:draft.day,record:rows[0])).preparedForLedger()
            let deleted=try await api.applyMoodOperation(sessionID:sid,mutation:deletion);check(deleted.state == "applied")
            print("PASS: real paired exact-ID mood ledger apply/retry/read/delete accepts typed receipts without model calls.")
            let file=try EchoSelectedFile(name:"R13-iOS-HTTPS.txt",text:"这是本人在合成联调中选择并预览的测试资料。")
            let snapshot=try await api.attachFiles([file],sessionID:sid)
            check(snapshot.session.id == sid);let source=snapshot.context!.sources!.first!
            try await api.revokeSource(id:source.id,sessionID:sid)
            let after=try await api.conversation();check(!(after.context?.sources ?? []).contains {$0.id == source.id})
            _ = try await api.boundary(sessionID:sid);_ = try await api.followups(sessionID:sid)
            print("PASS: selected-text confirmation, per-source withdrawal and passive boundary/followup reads work through the paired gateway.")
            // A forbidden endpoint is checked with the same explicitly trusted test session.
            var forbidden=URLRequest(url:URL(string:address+"/api/settings/model")!);forbidden.setValue("Bearer "+token,forHTTPHeaderField:"Authorization");forbidden.setValue(receipt.serviceInstanceId,forHTTPHeaderField:"X-Echo-Service-Instance")
            let (_,denied)=try await session.data(for:forbidden);check((denied as! HTTPURLResponse).statusCode == 403)
            check(store.deviceConnected && vault.values[profile.vaultAccount] == token)
            print("PASS: real gateway403 rejects model settings without dropping device identity.")
            var revoke=URLRequest(url:URL(string:owner+"/api/paired-devices/"+device+"/revoke")!);revoke.httpMethod="POST";revoke.setValue("application/json",forHTTPHeaderField:"Content-Type");revoke.httpBody=Data(#"{"confirmed":true}"#.utf8)
            let (_,revoked)=try await URLSession(configuration:.ephemeral).data(for:revoke);check((revoked as! HTTPURLResponse).statusCode == 200)
            store.draft="撤销后保留在原身份的合成草稿";await store.refreshFromForeground();for _ in 0..<100 {await Task.yield()}
            check(!store.deviceConnected && store.conversation == nil && store.draft.isEmpty && vault.values.isEmpty && vault.removals == 1)
            check(store.connectionFailureCode == "paired_authentication_required")
            print("PASS: owner revocation causes actual typed401; exact fake-vault item/private RAM cleared, no anonymous retry or server rollback claim.")
            print("HOST_R13_PAIRED_PASS: 10 workflow groups. Synthetic data only; no system CA installation, user Keychain, model, CLI, hardware or notification.")
        } catch {print("HOST_R13_PAIRED_FAIL:",error.localizedDescription);exit(1)}
    }
}
