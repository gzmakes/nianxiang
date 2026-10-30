import Foundation
import SwiftUI

private final class LedgerProtocol: URLProtocol {
    static var rows=[[String:Any]](), receipts=[String:[String:Any]](),calls=[String](),applyBodies=[[String:Any]](),cancelBodies=[[String:Any]]()
    static var mode="ack",hold=false,held=[LedgerProtocol](),tick=1
    static func reset() {rows=[];receipts=[:];calls=[];applyBodies=[];cancelBodies=[];mode="ack";hold=false;held=[];tick=1}
    override class func canInit(with request: URLRequest) -> Bool {true}
    override class func canonicalRequest(for request: URLRequest) -> URLRequest {request}
    override func stopLoading() {}
    func body() -> [String:Any] {
        if let data=request.httpBody {return (try? JSONSerialization.jsonObject(with:data)) as? [String:Any] ?? [:]}
        guard let stream=request.httpBodyStream else {return [:]};stream.open();defer {stream.close()}
        var data=Data(),buffer=[UInt8](repeating:0,count:1024)
        while stream.hasBytesAvailable {let count=stream.read(&buffer,maxLength:buffer.count);if count <= 0 {break};data.append(buffer,count:count)}
        return (try? JSONSerialization.jsonObject(with:data)) as? [String:Any] ?? [:]
    }
    func finish(_ value: [String:Any],_ code: Int = 200) {
        client?.urlProtocol(self,didReceive:HTTPURLResponse(url:request.url!,statusCode:code,httpVersion:nil,headerFields:["Content-Type":"application/json"])!,cacheStoragePolicy:.notAllowed)
        client?.urlProtocol(self,didLoad:try! JSONSerialization.data(withJSONObject:value));client?.urlProtocolDidFinishLoading(self)
    }
    func fail() {client?.urlProtocol(self,didFailWithError:URLError(.timedOut))}
    override func startLoading() {
        let path=request.url!.path,method=request.httpMethod ?? "GET";Self.calls.append(method+" "+path)
        precondition(path == "/api/moods" || path == "/api/mood-operations" || path.hasPrefix("/api/mood-operations/"),"No model/chat/account/source/contact/device requests")
        if method == "GET",path == "/api/moods" {
            if Self.mode == "read-fail" {fail();return};finish(["moods":Self.rows]);return
        }
        if Self.hold {Self.held.append(self);return}
        respond()
    }
    func respond() {
        let path=request.url!.path,method=request.httpMethod ?? "GET",b=body()
        let id=(b["request_id"] as? String) ?? (path.hasSuffix("/cancel") ? request.url!.deletingLastPathComponent().lastPathComponent : request.url!.lastPathComponent)
        let sid=(b["session_id"] as? String) ?? URLComponents(url:request.url!,resolvingAgainstBaseURL:false)!.queryItems!.first {$0.name == "session_id"}!.value!
        if method == "GET" {
            var result=Self.receipts[id] ?? ["session_id":sid,"request_id":id,"operation_sha256":NSNull(),"kind":NSNull(),"state":"not_found","result_updated_at":NSNull()]
            if Self.mode == "bad-receipt" {result["request_id"]="another-id"};finish(result);return
        }
        if path.hasSuffix("/cancel") {
            Self.cancelBodies.append(b)
            precondition(Set(b.keys) == ["session_id","operation_sha256","kind","confirmed"])
            if Self.mode == "cancel-timeout" {fail();return}
            let result=Self.receipts[id] ?? ["session_id":sid,"request_id":id,"operation_sha256":b["operation_sha256"]!,"kind":b["kind"]!,"state":"cancelled","result_updated_at":NSNull()]
            Self.receipts[id]=result;finish(result);return
        }
        Self.applyBodies.append(b)
        if Self.mode == "timeout-before" {fail();return}
        if Self.mode == "invalid" {finish(["detail":"synthetic invalid"],422);return}
        if let receipt=Self.receipts[id] {finish(receipt);return}
        let raw=b["operation_json"] as! String,inner=try! JSONSerialization.jsonObject(with:Data(raw.utf8)) as! [String:Any]
        let kind=inner["kind"] as! String,day=inner["date"] as! String,expected=inner["expected_updated_at"] as? String
        let old=Self.rows.first {$0["date"] as? String == day},oldToken=old?["updated_at"] as? String
        var result:[String:Any] = ["session_id":sid,"request_id":id,"operation_sha256":hash(raw),"kind":kind,"state":"applied","result_updated_at":NSNull()]
        if expected != oldToken {result["state"]="conflict";result["result_updated_at"]=oldToken as Any? ?? NSNull()}
        else if kind == "save" {
            Self.tick += 1;let token=String(format:"2026-10-30T00:00:%02d.000001+00:00",Self.tick)
            Self.rows.removeAll {$0["date"] as? String == day};Self.rows.append(["date":day,"x":inner["x"]!,"y":inner["y"]!,"note":inner["note"]!,"updated_at":token]);result["result_updated_at"]=token
        } else {Self.rows.removeAll {$0["date"] as? String == day};result["result_updated_at"]=expected!}
        Self.receipts[id]=result
        if Self.mode == "timeout-after" {fail();return}
        if Self.mode == "bad-receipt" {result["kind"]="unrecognized"}
        finish(result)
    }
    func hash(_ raw: String) -> String {
        // Reuse the immutable JSON hash from a decoded local snapshot, not any API request.
        var draft=EchoMoodDraft(origin:"hash",sessionID:"hash",day:"2026-10-28");draft.xSelected=true;draft.ySelected=true
        var obj=try! JSONSerialization.jsonObject(with:JSONEncoder().encode(EchoMoodMutation(kind:.save,draft:draft))) as! [String:Any]
        obj["operationJSON"]=raw
        return try! JSONDecoder().decode(EchoMoodMutation.self,from:JSONSerialization.data(withJSONObject:obj)).operationHash!
    }
}

@main struct MoodLedgerLifecycleChecks {
    @MainActor static func api(_ origin: String = "http://127.0.0.1:18787") throws -> EchoAPI {let c=URLSessionConfiguration.ephemeral;c.protocolClasses=[LedgerProtocol.self];return try EchoAPI(baseURL:origin,session:URLSession(configuration:c))}
    static func row(note: String,token: String = "2026-10-30T00:00:10.000001+00:00") -> [String:Any] {["date":EchoMood.day(),"x":0.8,"y":0.2,"note":note,"updated_at":token]}
    @MainActor static func main() async {
        let suite="echo.synthetic.ledger."+UUID().uuidString,defaults=UserDefaults(suiteName:suite)!
        defer {defaults.removePersistentDomain(forName:suite)}
        var count=0
        func pass(_ s: String) {count += 1;print("PASS:",s)}
        do {
            let client=try api()
            func model(_ sid: String,writer: ((String,Data)->Bool)? = nil) async -> MoodStore {
                let s=MoodStore(defaults:defaults,writer:writer);await s.bind(api:client,sessionID:sid,supported:true,ledgerSupported:true);return s
            }
            func fill(_ s: MoodStore,_ text: String) {s.edit(x:0.3,y:0.1,note:text)}
            LedgerProtocol.reset();let saved=await model("saved");fill(saved,"原始 JSON 保留 🫶");await saved.save()
            precondition(saved.draft?.pending == nil && saved.current?.note == "原始 JSON 保留 🫶" && LedgerProtocol.applyBodies.count == 1)
            precondition(LedgerProtocol.calls.last == "GET /api/moods")
            pass("ledger save persists identity then validates metadata and independently reads current diary")
            LedgerProtocol.reset();let unknown=await model("unknown");fill(unknown,"不要丢我的原话");LedgerProtocol.mode="timeout-before";await unknown.save()
            let original=unknown.draft!.pending!;precondition(original.validLedgerIdentity)
            await unknown.refresh();precondition(unknown.draft?.pending == original && unknown.draft?.operationState == "not_found" && !unknown.canSave && LedgerProtocol.applyBodies.count == 1)
            let restored=await model("unknown");precondition(restored.draft?.pending == original && LedgerProtocol.applyBodies.count == 1)
            pass("timeout then not_found and recreation do not auto resend or unlock; raw JSON and UUID retained")
            LedgerProtocol.mode="ack";await restored.retryOperation()
            precondition(restored.draft?.pending == nil && LedgerProtocol.applyBodies.count == 2 && LedgerProtocol.applyBodies[0]["operation_json"] as? String == LedgerProtocol.applyBodies[1]["operation_json"] as? String && LedgerProtocol.applyBodies[0]["request_id"] as? String == LedgerProtocol.applyBodies[1]["request_id"] as? String)
            pass("explicit retry reuses exact frozen raw and original ID, then reconciles current row")
            LedgerProtocol.reset();let lost=await model("lost-ack");fill(lost,"写入后丢回执");LedgerProtocol.mode="timeout-after";await lost.save()
            precondition(lost.draft?.pending != nil && LedgerProtocol.rows.count == 1);LedgerProtocol.mode="ack";await lost.refresh()
            precondition(lost.draft?.pending == nil && lost.current?.note == "写入后丢回执" && LedgerProtocol.applyBodies.count == 1)
            pass("applied but lost response recovers by GET without second apply")
            LedgerProtocol.reset();let cancelled=await model("cancelled");fill(cancelled,"取消但留下草稿");LedgerProtocol.mode="timeout-before";await cancelled.save()
            let cancelPending=cancelled.draft!.pending!;LedgerProtocol.mode="ack";await cancelled.cancelOperation()
            precondition(cancelled.draft?.pending == nil && cancelled.draft?.note == "取消但留下草稿" && cancelled.canSave && LedgerProtocol.rows.isEmpty && LedgerProtocol.cancelBodies.count == 1)
            let late=try await client.applyMoodOperation(sessionID:"cancelled",mutation:cancelPending)
            precondition(late.state == "cancelled" && LedgerProtocol.rows.isEmpty)
            pass("cancel tombstone unlocks retained draft; late same apply remains cancelled without writing")
            LedgerProtocol.reset();let cancelUnknown=await model("cancel-unknown");fill(cancelUnknown,"取消意图持久");LedgerProtocol.mode="timeout-before";await cancelUnknown.save()
            LedgerProtocol.mode="cancel-timeout";await cancelUnknown.cancelOperation();precondition(cancelUnknown.draft?.cancelRequested == true && !cancelUnknown.canRetryLedger)
            let cancelRestored=await model("cancel-unknown");await cancelRestored.retryOperation()
            precondition(cancelRestored.draft?.cancelRequested == true && cancelRestored.draft?.pending != nil && LedgerProtocol.applyBodies.count == 1)
            LedgerProtocol.mode="ack";await cancelRestored.cancelOperation();precondition(cancelRestored.draft?.pending == nil && LedgerProtocol.cancelBodies.count == 2)
            pass("cancel intent persists before POST; timeout/restart/not_found can only check or repeat same cancel, never apply")
            LedgerProtocol.reset();let tooLate=await model("late-cancel");fill(tooLate,"已处理不回滚");LedgerProtocol.mode="timeout-after";await tooLate.save();LedgerProtocol.mode="ack";await tooLate.cancelOperation()
            precondition(tooLate.draft?.pending == nil && tooLate.current?.note == "已处理不回滚" && tooLate.notice.contains("不会回滚"))
            pass("cancel of already-applied write reports processed/current row and never pretends rollback")
            LedgerProtocol.reset();let newer=await model("newer");fill(newer,"历史提交");LedgerProtocol.mode="timeout-after";await newer.save();LedgerProtocol.rows=[row(note:"另一次更新")];LedgerProtocol.mode="ack";await newer.refresh()
            precondition(newer.draft?.pending == nil && newer.draft?.needsReview == true && newer.draft?.note == "历史提交" && newer.current?.note == "另一次更新" && !newer.canSave)
            let applyCount=LedgerProtocol.applyBodies.count;newer.adoptLatestVersion();precondition(newer.canSave && LedgerProtocol.applyBodies.count == applyCount)
            pass("historical applied receipt cannot overwrite newer row; original draft requires explicit current-version adoption")
            LedgerProtocol.reset();let conflict=await model("conflict");fill(conflict,"CAS 草稿");LedgerProtocol.rows=[row(note:"并行新增")];await conflict.save()
            precondition(conflict.draft?.pending == nil && conflict.draft?.needsReview == true && conflict.draft?.note == "CAS 草稿" && conflict.current?.note == "并行新增" && LedgerProtocol.applyBodies.count == 1)
            pass("CAS conflict is terminal HTTP200 but not saved; current row and retained draft need explicit review")
            LedgerProtocol.reset();let invalid=await model("invalid");fill(invalid,"明确422也不换ID");LedgerProtocol.mode="invalid";await invalid.save();let invalidPending=invalid.draft!.pending!;await invalid.save()
            precondition(invalid.draft?.pending == invalidPending && LedgerProtocol.applyBodies.count == 1);LedgerProtocol.mode="ack";await invalid.cancelOperation();precondition(invalid.draft?.pending == nil)
            pass("ledger 422 never silently releases identity; metadata cancel can explicitly retire it")
            LedgerProtocol.reset();let malformed=await model("malformed");fill(malformed,"不匹配回执");LedgerProtocol.mode="bad-receipt";await malformed.save();await malformed.refresh()
            precondition(malformed.draft?.pending != nil && !malformed.canSave);LedgerProtocol.mode="ack";await malformed.refresh();precondition(malformed.draft?.pending == nil)
            pass("mismatched apply/status receipts retain protection until an exact GET receipt is obtained")
            LedgerProtocol.reset();let readFail=await model("read-fail");fill(readFail,"终态后GET失败");LedgerProtocol.mode="read-fail";await readFail.save()
            precondition(readFail.draft?.operationState == "applied" && readFail.draft?.pending != nil && !readFail.canSave);LedgerProtocol.mode="ack";await readFail.refresh();precondition(readFail.draft?.pending == nil && LedgerProtocol.applyBodies.count == 1)
            pass("known terminal ledger response with diary GET failure stays pending; next check is read-only")
            LedgerProtocol.reset();let noStorage=await model("storage",writer:{_,_ in false});fill(noStorage,"落盘失败");await noStorage.save()
            precondition(LedgerProtocol.applyBodies.isEmpty && noStorage.draft?.note == "落盘失败")
            pass("local persistence failure retains input and prevents any new apply")
            LedgerProtocol.reset();let lateOrigin=await model("origin");fill(lateOrigin,"旧地址回执");LedgerProtocol.hold=true
            let task=Task {await lateOrigin.save()};for _ in 0..<100 {if !LedgerProtocol.held.isEmpty {break};await Task.yield()};precondition(!LedgerProtocol.held.isEmpty)
            await lateOrigin.bind(api:try api("http://127.0.0.1:19101"),sessionID:"new",supported:false,ledgerSupported:false)
            LedgerProtocol.hold=false;let held=LedgerProtocol.held;LedgerProtocol.held=[];for h in held {h.respond()};await task.value
            precondition(lateOrigin.draft?.sessionID == "new" && lateOrigin.draft?.note == "" && !lateOrigin.ready)
            let old=await model("origin");precondition(old.draft?.pending == nil && old.current?.note == "旧地址回执")
            pass("late apply receipt cannot cross origin/sid generation; original scope recovers by GET")
            LedgerProtocol.reset();let downgrade=await model("downgrade");fill(downgrade,"不能降级");LedgerProtocol.mode="timeout-before";await downgrade.save();let before=LedgerProtocol.calls.count
            await downgrade.bind(api:client,sessionID:"downgrade",supported:true,ledgerSupported:false)
            precondition(downgrade.draft?.pending?.hasLedgerIdentity == true && LedgerProtocol.calls.count == before && !downgrade.canRetryLedger)
            pass("ledger pending on service capability downgrade is locked without legacy API fallback")
            LedgerProtocol.reset();let legacySID="legacy-r10",origin=client.baseURL.absoluteString,day=EchoMood.day()
            var legacyDraft=EchoMoodDraft(origin:origin,sessionID:legacySID,day:day);legacyDraft.x=0.2;legacyDraft.y=0.1;legacyDraft.xSelected=true;legacyDraft.ySelected=true;legacyDraft.note="R10 未决草稿";legacyDraft.dirty=true
            legacyDraft.pending=EchoMoodMutation(kind:.save,draft:legacyDraft)
            let key="echo.native.mood-draft.v1."+Data((origin+"|"+legacySID).utf8).base64EncodedString()+"."+day
            defaults.set(try JSONEncoder().encode(legacyDraft),forKey:key)
            let legacy=await model(legacySID);await legacy.retryOperation();await legacy.cancelOperation()
            precondition(legacy.draft?.pending?.hasLedgerIdentity == false && legacy.draft?.note == "R10 未决草稿" && LedgerProtocol.applyBodies.isEmpty && LedgerProtocol.cancelBodies.isEmpty && LedgerProtocol.calls == ["GET /api/moods"])
            pass("restored R10 pending stays legacy GET-only even on ledger-capable service; no new ID or cancel")
            LedgerProtocol.reset();var failWrites=false
            let failCancel=await model("cancel-storage",writer:{_,_ in !failWrites})
            fill(failCancel,"取消也必须先落盘");LedgerProtocol.mode="timeout-before";await failCancel.save()
            precondition(failCancel.draft?.pending != nil);failWrites=true;await failCancel.cancelOperation();await failCancel.retryOperation()
            precondition(failCancel.draft?.cancelRequested == true && LedgerProtocol.cancelBodies.isEmpty && LedgerProtocol.applyBodies.count == 1 && !failCancel.canRetryLedger)
            pass("failure to persist cancellation intent blocks cancel network and subsequent apply")
            print("Mood ledger lifecycle checks:",count,"/",count,"passed; actual MoodStore on macOS, synthetic URLProtocol; no iOS SDK/device validation.")
        } catch {print("FAIL:",error.localizedDescription);exit(1)}
    }
}
