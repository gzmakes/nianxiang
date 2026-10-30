import Foundation
import SwiftUI

/// Entire transport and vault are synthetic. This executable never calls SecItem*.
@MainActor private final class FakeDeviceVault: EchoDeviceCredentialStore {
    var values=[String:String](),saved=[EchoDeviceProfile](),readAccounts=[String](),removed=[String]()
    var locked=false,failSave=false,wrongReadback=false
    func save(_ token: String,for profile: EchoDeviceProfile) throws {
        if locked {throw EchoCredentialStoreError.locked};if failSave {throw EchoCredentialStoreError.unavailable}
        saved.append(profile);values[profile.vaultAccount]=token
    }
    func read(for profile: EchoDeviceProfile) throws -> String {
        readAccounts.append(profile.vaultAccount);if locked {throw EchoCredentialStoreError.locked}
        guard let value=values[profile.vaultAccount] else {throw EchoCredentialStoreError.missing}
        return wrongReadback ? "echo_pair_"+String(repeating:"Z",count:43) : value
    }
    func remove(for profile: EchoDeviceProfile) throws {
        if locked {throw EchoCredentialStoreError.locked};removed.append(profile.vaultAccount);values.removeValue(forKey:profile.vaultAccount)
    }
}
private final class DeviceProtocol: URLProtocol {
    static var calls=[URLRequest](),failPath="",failure=0,holdPath="",held=[DeviceProtocol]()
    static var instance="instance-A",conversation="canonical",wrongConversation=false
    static func reset() {calls=[];failPath="";failure=0;holdPath="";held=[];instance="instance-A";conversation="canonical";wrongConversation=false}
    override class func canInit(with request: URLRequest) -> Bool {true}
    override class func canonicalRequest(for request: URLRequest) -> URLRequest {request}
    override func stopLoading() {}
    var deviceID: String {request.value(forHTTPHeaderField:"Authorization")?.hasSuffix(String(repeating:"B",count:43)) == true ? "device-B" : "device-A"}
    override func startLoading() {
        Self.calls.append(request);let path=request.url!.path
        precondition(!path.contains("actions") && !path.contains("lark") && !path.contains("hardware"),"Remote local actions must never be probed")
        if path == Self.holdPath {Self.held.append(self);return}
        if path == Self.failPath {
            if Self.failure == -1 {client?.urlProtocol(self,didFailWithError:URLError(.timedOut));return}
            finish(["detail":"synthetic rejection","error_code":Self.failure == 401 ? "paired_authentication_required" : Self.failure == 409 ? "service_instance_mismatch" : "paired_operation_forbidden"],status:Self.failure);return
        }
        if path == "/api/paired-device" {
            finish(["service_instance_id":Self.instance,"conversation_id":Self.conversation,"scope":"personal_core","local_actions_allowed":false,"device":["id":deviceID,"label":"合成测试设备","created_at":"2026-01-01T00:00:00Z","expires_at":"2099-01-01T00:00:00Z","revoked_at":NSNull()]]);return
        }
        if path == "/api/conversation" {snapshot();return}
        if path == "/api/capabilities" {finish(["contract_version":"1.6.0","deployment_mode":"remote_app","service_platform":"darwin","features":[:],"platform_status":[:],"connection_status":"not_probed"]);return}
        if path == "/api/chat" {client?.urlProtocol(self,didFailWithError:URLError(.timedOut));return}
        if path.hasPrefix("/api/chat/turn/") {finish(["request_id":request.url!.lastPathComponent,"session_id":Self.conversation,"status":"unknown"]);return}
        if path == "/api/followups" {finish(["followups":[]]);return}
        fatalError("Unexpected synthetic device request")
    }
    func fail() {client?.urlProtocol(self,didFailWithError:URLError(.timedOut))}
    func snapshot() {finish(["session":["id":Self.wrongConversation ? "different-canonical" : Self.conversation],"messages":[["id":"one","role":"assistant","text":"合成设备快照"]],"memories":[],"context":NSNull()])}
    func finish(_ value: [String:Any],status: Int = 200) {
        client?.urlProtocol(self,didReceive:HTTPURLResponse(url:request.url!,statusCode:status,httpVersion:nil,headerFields:["Content-Type":"application/json"])!,cacheStoragePolicy:.notAllowed)
        client?.urlProtocol(self,didLoad:try! JSONSerialization.data(withJSONObject:value));client?.urlProtocolDidFinishLoading(self)
    }
}
@main struct DeviceConnectionLifecycleChecks {
    static let origin="https://synthetic.echo.invalid"
    static let tokenA="echo_pair_"+String(repeating:"A",count:43),tokenB="echo_pair_"+String(repeating:"B",count:43)
    @MainActor private static func store(_ defaults: UserDefaults,_ vault: FakeDeviceVault) -> EchoStore {
        EchoStore(defaults:defaults,credentialStore:vault,apiFactory:{address,auth in
            let c=URLSessionConfiguration.ephemeral;c.protocolClasses=[DeviceProtocol.self]
            return try EchoAPI(baseURL:address,session:URLSession(configuration:c),authorization:auth)
        })
    }
    @MainActor static func waitForHeld() async {for _ in 0..<5000 {if !DeviceProtocol.held.isEmpty {return};await Task.yield()};preconditionFailure("synthetic transport did not suspend")}
    @MainActor static func settleCallbacks() async {for _ in 0..<100 {await Task.yield()}}
    @MainActor static func main() async {
        let suite="echo.synthetic.device."+UUID().uuidString,defaults=UserDefaults(suiteName:suite)!,vault=FakeDeviceVault()
        defer {defaults.removePersistentDomain(forName:suite)}
        let s=store(defaults,vault);var groups=0
        func pass(_ message: String) {groups += 1;print("PASS: "+message)}
        func check(_ value: Bool,file: StaticString = #fileID,line: UInt = #line) {precondition(value,"Device invariant",file:file,line:line)}
        DeviceProtocol.reset()
        // No synthetic local boot request is needed: explicit remote attempts below.
        check(vault.readAccounts.isEmpty && vault.saved.isEmpty && vault.removed.isEmpty)
        pass("init never queries credential store; cold foreground check follows below")
        s.draft="本机旧草稿";let endpoint=s.endpoint
        check(!(await s.connectDevice(address:origin,token:"model-key")))
        check(!(await s.connectDevice(address:"http://127.0.0.1:19999",token:tokenA)))
        check(DeviceProtocol.calls.isEmpty && vault.saved.isEmpty && s.endpoint == endpoint && s.draft == "本机旧草稿")
        pass("malformed bearer and HTTP token connection fail before network or vault access")
        DeviceProtocol.failPath="/api/paired-device";DeviceProtocol.failure=401
        check(!(await s.connectDevice(address:origin,token:tokenA)))
        check(s.endpoint == endpoint && s.draft == "本机旧草稿" && vault.saved.isEmpty)
        DeviceProtocol.failure = -1;check(!(await s.connectDevice(address:origin,token:tokenA)))
        check(s.endpoint == endpoint && s.draft == "本机旧草稿" && vault.removed.isEmpty)
        pass("first verification auth rejection or timeout preserves existing connection and draft")
        DeviceProtocol.reset();DeviceProtocol.wrongConversation=true
        check(!(await s.connectDevice(address:origin,token:tokenA)));check(vault.saved.isEmpty && s.endpoint == endpoint)
        DeviceProtocol.reset();vault.failSave=true
        check(!(await s.connectDevice(address:origin,token:tokenA)));check(s.endpoint == endpoint)
        vault.failSave=false;vault.wrongReadback=true
        check(!(await s.connectDevice(address:origin,token:tokenA)));check(s.endpoint == endpoint && vault.values.isEmpty)
        vault.wrongReadback=false
        pass("canonical mismatch, vault save failure and readback mismatch cannot activate candidate")
        DeviceProtocol.reset();DeviceProtocol.failPath="/api/capabilities";DeviceProtocol.failure=401
        let beforeSaves=vault.saved.count
        check(!(await s.connectDevice(address:origin,token:tokenA)));await settleCallbacks()
        check(vault.saved.count == beforeSaves && s.deviceProfile == nil)
        pass("candidate 401 during optional metadata cannot be swallowed into activation")
        DeviceProtocol.reset();check(await s.connectDevice(address:origin,token:tokenA))
        let a=s.deviceProfile!,aClient=s.api,aScope=s.scopeIdentity
        check(s.deviceConnected && s.sessionID == "canonical" && s.actions.isEmpty && vault.values[a.vaultAccount] == tokenA)
        check(DeviceProtocol.calls.first!.value(forHTTPHeaderField:"X-Echo-Service-Instance") == nil)
        check(DeviceProtocol.calls.dropFirst().allSatisfy {$0.value(forHTTPHeaderField:"X-Echo-Service-Instance") == "instance-A"})
        check(DeviceProtocol.calls.allSatisfy {$0.httpMethod == "GET" && $0.url!.query == nil && $0.value(forHTTPHeaderField:"Authorization") == "Bearer "+tokenA})
        pass("verification precedes exact scoped vault save; bound reads carry instance and never probe actions")
        s.draft="设备A的草稿";s.disconnectDevice(forgetCredential:false)
        check(s.conversation == nil && s.draft.isEmpty && vault.values[a.vaultAccount] == tokenA)
        let readsBefore=vault.readAccounts.count,cold=store(defaults,vault);await cold.refreshFromForeground()
        check(vault.readAccounts.count == readsBefore && !cold.deviceConnected)
        DeviceProtocol.calls=[];check(await cold.restoreDeviceConnection())
        check(cold.scopeIdentity == aScope && cold.draft == "设备A的草稿" && DeviceProtocol.calls.allSatisfy {$0.httpMethod == "GET"})
        pass("cold recreation reads no vault; explicit restore validates exact profile and reloads isolated draft without POST")
        cold.disconnectDevice(forgetCredential:false);vault.locked=true;let callsBefore=DeviceProtocol.calls.count
        check(!(await cold.restoreDeviceConnection()))
        check(DeviceProtocol.calls.count == callsBefore && vault.values[a.vaultAccount] == tokenA && !cold.forgottenDeviceGenerations.contains(a.credentialGeneration))
        vault.locked=false;check(await cold.restoreDeviceConnection())
        pass("locked vault preserves exact credential and does not attempt network or deletion")
        DeviceProtocol.failPath="/api/conversation";DeviceProtocol.failure=403;_ = try? await cold.api.conversation();await settleCallbacks()
        check(cold.deviceConnected && cold.conversation != nil && vault.values[a.vaultAccount] == tokenA)
        DeviceProtocol.failure=503;_ = try? await cold.api.conversation();await settleCallbacks()
        check(cold.deviceConnected && vault.values[a.vaultAccount] == tokenA)
        pass("forbidden and transient service errors do not revoke or clear active identity")
        DeviceProtocol.failure=409;_ = try? await cold.api.conversation();await settleCallbacks()
        check(!cold.deviceConnected && cold.conversation == nil && cold.draft.isEmpty && vault.values[a.vaultAccount] == tokenA && !cold.forgottenDeviceGenerations.contains(a.credentialGeneration))
        DeviceProtocol.reset();check(await cold.restoreDeviceConnection())
        check(cold.draft == "设备A的草稿")
        pass("instance mismatch retires RAM authorization but preserves original credential and draft for verified restoration")
        // Hold an old-generation success while a new generation activates on the same canonical conversation.
        DeviceProtocol.holdPath="/api/conversation";let oldClient=cold.api
        let oldRead=Task {try? await oldClient.conversation()};await waitForHeld();let held=DeviceProtocol.held.removeFirst();DeviceProtocol.holdPath=""
        check(await cold.connectDevice(address:origin,token:tokenB));let b=cold.deviceProfile!
        cold.draft="设备B草稿";held.snapshot();let stale=await oldRead.value
        check(stale == nil && cold.deviceProfile == b && cold.draft == "设备B草稿" && b.namespace != a.namespace)
        pass("retired client's late success cannot escape into same-canonical new device generation")
        // A known retired profile's late 409 must not delete its original vault item.
        DeviceProtocol.holdPath="/api/conversation";let bClient=cold.api
        let bRead=Task {try? await bClient.conversation()};await waitForHeld();let bHeld=DeviceProtocol.held.removeFirst();DeviceProtocol.holdPath=""
        check(await cold.restoreDeviceConnection(a));cold.draft="恢复A仍在"
        bHeld.finish(["detail":"synthetic old instance mismatch","error_code":"service_instance_mismatch"],status:409);_ = await bRead.value;await settleCallbacks()
        check(cold.deviceProfile == a && cold.draft == "恢复A仍在" && vault.values[b.vaultAccount] == tokenB)
        pass("late old-profile 409 preserves old recoverable credential and current identity")
        DeviceProtocol.holdPath="/api/conversation";let restoredAClient=cold.api
        let late401=Task {try? await restoredAClient.conversation()};await waitForHeld();let aHeld=DeviceProtocol.held.removeFirst();DeviceProtocol.holdPath=""
        check(await cold.restoreDeviceConnection(b));cold.draft="B不被旧401清掉"
        aHeld.finish(["detail":"synthetic old auth failure","error_code":"paired_authentication_required"],status:401);_ = await late401.value;await settleCallbacks()
        check(cold.deviceProfile == b && cold.deviceConnected && cold.draft == "B不被旧401清掉" && vault.values[b.vaultAccount] == tokenB && vault.values[a.vaultAccount] == nil)
        check(cold.forgottenDeviceGenerations.contains(a.credentialGeneration))
        pass("late known old 401 removes only its exact app-owned key and cannot clear newer token or RAM")
        // Persist a real unknown turn using the synthetic chat timeout.
        cold.draft="B原请求";await cold.send();let pending=cold.pending!
        check(pending.origin == b.namespace && DeviceProtocol.calls.filter {$0.httpMethod == "POST"}.count == 1)
        cold.disconnectDevice(forgetCredential:false);DeviceProtocol.calls=[]
        check(await cold.restoreDeviceConnection(b));check(cold.pending?.requestID == pending.requestID)
        await cold.recoverPending();check(cold.pending?.requestID == pending.requestID && DeviceProtocol.calls.allSatisfy {$0.httpMethod == "GET"})
        pass("paired unknown request preserves exact ID/payload namespace across explicit restore and only GET reconciliation")
        DeviceProtocol.failPath="/api/conversation";DeviceProtocol.failure=401
        _ = try? await cold.api.conversation();await settleCallbacks()
        check(!cold.deviceConnected && cold.conversation == nil && cold.pending == nil && vault.values[b.vaultAccount] == nil && cold.forgottenDeviceGenerations.contains(b.credentialGeneration))
        let pendingKey="echo.native.pending-turn.v1."+Data(b.namespace.utf8).base64EncodedString()
        check((try? JSONDecoder().decode(EchoPendingTurn.self,from:defaults.data(forKey:pendingKey)!))?.requestID == pending.requestID)
        pass("current 401 clears private RAM and exact vault key while retaining isolated unknown payload on disk")
        DeviceProtocol.reset();check(await cold.connectDevice(address:origin,token:tokenA));let fresh=cold.deviceProfile!
        DeviceProtocol.holdPath="/api/paired-device";let cancelled=Task {await cold.connectDevice(address:origin,token:tokenB)};await waitForHeld();let verifyHeld=DeviceProtocol.held.removeFirst();cold.cancelDeviceVerification();DeviceProtocol.holdPath=""
        verifyHeld.finish(["service_instance_id":"instance-A","conversation_id":"canonical","scope":"personal_core","local_actions_allowed":false,"device":["id":"device-B","label":"合成","created_at":"2026-01-01T00:00:00Z","expires_at":"2099-01-01T00:00:00Z","revoked_at":NSNull()]])
        check(!(await cancelled.value) && cold.deviceProfile == fresh && !cold.verifyingDevice)
        pass("leaving/background cancellation prevents a late verifier from activating or saving credentials")
        check(await cold.connectDevice(address:origin,token:tokenB));let newest=cold.deviceProfile!
        cold.forgetSavedDeviceCredential(fresh)
        check(cold.deviceProfile == newest && cold.deviceConnected && vault.values[newest.vaultAccount] == tokenB && vault.values[fresh.vaultAccount] == nil && cold.forgottenDeviceGenerations.contains(fresh.credentialGeneration))
        let removedBefore=vault.removed.count
        check(!(await cold.restoreDeviceConnection(fresh)) && vault.removed.count == removedBefore)
        _ = aClient // an old externally held API remains permanently retired.
        pass("explicit old-profile removal affects only selected local key and disables its automatic restoration")
        // Two same-canonical writes are allowed only after an explicit local
        // disconnect. Their persistent IDs remain in separate generations.
        DeviceProtocol.holdPath="/api/chat";cold.draft="旧许可的原发送"
        let oldSend=Task {await cold.send()};await waitForHeld();let oldWrite=DeviceProtocol.held.removeFirst(),retiredProfile=cold.deviceProfile!,retiredPending=cold.pending!
        cold.disconnectDevice(forgetCredential:false);DeviceProtocol.holdPath=""
        check(await cold.connectDevice(address:origin,token:tokenA));let active=cold.deviceProfile!
        DeviceProtocol.holdPath="/api/chat";cold.draft="新许可的原发送"
        let newSend=Task {await cold.send()};await waitForHeld();let newWrite=DeviceProtocol.held.removeFirst(),newID=cold.pending!.requestID
        oldWrite.finish(["detail":"old quota response","error_code":"budget_exceeded"],status:429);await oldSend.value
        check(cold.deviceProfile == active && cold.busy && cold.pending?.requestID == newID && cold.draft.isEmpty && cold.error == nil)
        newWrite.fail();await newSend.value;check(!cold.busy && cold.pending?.requestID == newID)
        DeviceProtocol.holdPath="";cold.disconnectDevice(forgetCredential:false);DeviceProtocol.calls=[]
        check(await cold.restoreDeviceConnection(retiredProfile))
        check(cold.pending?.requestID == retiredPending.requestID && cold.pending?.text == "旧许可的原发送" && DeviceProtocol.calls.allSatisfy {$0.httpMethod == "GET"})
        pass("old429/finally cannot edit new-generation draft/pending/busy; original unknown restores by exact profile without resubmission")
        print("Host device connection groups: \(groups)/\(groups) passed; fake vault + synthetic URLProtocol only, no Keychain/TLS/iOS runtime.")
    }
}
