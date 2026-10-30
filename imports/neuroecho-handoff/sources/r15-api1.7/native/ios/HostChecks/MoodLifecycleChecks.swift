import Foundation
import SwiftUI

private final class MoodProtocol: URLProtocol {
    static var rows=[[String:Any]]()
    static var calls=[String]()
    static var mode="ack"
    static var holdGET=false
    static var holdPUT=false
    static var held=[MoodProtocol]()
    static var tick=1
    static func reset() {rows=[];calls=[];mode="ack";holdGET=false;holdPUT=false;held=[];tick=1}
    override class func canInit(with request: URLRequest) -> Bool {true}
    override class func canonicalRequest(for request: URLRequest) -> URLRequest {request}
    func body() -> [String:Any] {
        if let data=request.httpBody {return (try? JSONSerialization.jsonObject(with:data)) as? [String:Any] ?? [:]}
        guard let stream=request.httpBodyStream else {return [:]};stream.open();defer {stream.close()}
        var data=Data(),buffer=[UInt8](repeating:0,count:1024)
        while stream.hasBytesAvailable {let count=stream.read(&buffer,maxLength:buffer.count);if count <= 0 {break};data.append(buffer,count:count)}
        return (try? JSONSerialization.jsonObject(with:data)) as? [String:Any] ?? [:]
    }
    override func startLoading() {
        let method=request.httpMethod ?? "GET",path=request.url!.path
        precondition(path == "/api/moods" || path.hasPrefix("/api/moods/"),"No chat, memory, contact, account or hardware request allowed")
        Self.calls.append(method+" "+path)
        if (method == "GET" && Self.holdGET) || (method == "PUT" && Self.holdPUT) {Self.held.append(self);return}
        if method == "GET" {finish(["moods":Self.rows]);return}
        if Self.mode == "timeout" {fail();return}
        if Self.mode == "conflict" {finish(["detail":"合成版本冲突","error_code":"mood_conflict"],status:409);return}
        if Self.mode == "invalid" {finish(["detail":"合成输入拒绝","error_code":"validation_error"],status:422);return}
        if method == "PUT" {
            var row=body();row.removeValue(forKey:"session_id");row.removeValue(forKey:"confirmed");row.removeValue(forKey:"expected_updated_at")
            row["date"]=request.url!.lastPathComponent;Self.tick += 1;row["updated_at"]=String(format:"2026-10-30T00:00:%02d.000001+00:00",Self.tick)
            Self.rows.removeAll {$0["date"] as? String == row["date"] as? String};Self.rows.append(row);finish(row)
        } else if method == "DELETE" {
            if Self.mode == "false-delete" {finish(["deleted":false]);return}
            Self.rows.removeAll {$0["date"] as? String == request.url!.lastPathComponent};finish(["deleted":true])
        } else {fatalError("Unexpected mutation")}
    }
    func finish(_ value: [String:Any],status: Int = 200) {client?.urlProtocol(self,didReceive:HTTPURLResponse(url:request.url!,statusCode:status,httpVersion:nil,headerFields:["Content-Type":"application/json"])!,cacheStoragePolicy:.notAllowed);client?.urlProtocol(self,didLoad:try! JSONSerialization.data(withJSONObject:value));client?.urlProtocolDidFinishLoading(self)}
    func fail() {client?.urlProtocol(self,didFailWithError:URLError(.timedOut))}
    override func stopLoading() {}
}
@main struct MoodLifecycleChecks {
    @MainActor static func client(_ origin: String = "http://127.0.0.1:18787") throws -> EchoAPI {let config=URLSessionConfiguration.ephemeral;config.protocolClasses=[MoodProtocol.self];return try EchoAPI(baseURL:origin,session:URLSession(configuration:config))}
    static func row(day: String = EchoMood.day(),note: String = "已存自述",token: String = "2026-10-30T00:00:01.000001+00:00",x: Double = 0.2,y: Double = -0.3) -> [String:Any] {["date":day,"x":x,"y":y,"note":note,"updated_at":token]}
    @MainActor static func main() async {
        let suite="echo.synthetic.mood."+UUID().uuidString,defaults=UserDefaults(suiteName:suite)!
        defer {defaults.removePersistentDomain(forName:suite)}
        var count=0
        func pass(_ text: String) {count += 1;print("PASS:",text)}
        do {
            let api=try client();MoodProtocol.reset();let store=MoodStore(defaults:defaults)
            await store.bind(api:api,sessionID:"one",supported:false)
            precondition(MoodProtocol.calls.isEmpty && store.draft?.xSelected == false && store.draft?.ySelected == false && !store.canSave)
            pass("missing capability does not read or upload and zero axes are unselected")
            await store.bind(api:api,sessionID:"one",supported:true);store.edit(x:0);precondition(!store.canSave)
            store.edit(y:0,note:"保存我的草稿");precondition(store.canSave)
            let restored=MoodStore(defaults:defaults);await restored.bind(api:api,sessionID:"one",supported:true)
            precondition(restored.draft?.note == "保存我的草稿" && restored.draft?.xSelected == true && restored.canSave)
            await restored.select(day:"2026-10-28");restored.edit(note:"另一天")
            await restored.select(day:EchoMood.day());precondition(restored.draft?.note == "保存我的草稿")
            await restored.bind(api:try client("http://127.0.0.1:19101"),sessionID:"one",supported:true);precondition(restored.draft?.note == "")
            await restored.bind(api:api,sessionID:"two",supported:true);precondition(restored.draft?.note == "")
            pass("ordinary draft and explicit zero choices survive recreation, date changes, origin and conversation isolation")
            await store.save();precondition(store.draft?.dirty == false && store.draft?.pending == nil && store.current?.note == "保存我的草稿" && store.canDelete)
            let chat=EchoStore(defaults:defaults);chat.draft="既有聊天草稿";let before=MoodProtocol.calls.count
            precondition(store.reviewedChatDraft(origin:"http://127.0.0.1:19101",sessionID:"one") == nil)
            precondition(store.reviewedChatDraft(origin:api.baseURL.absoluteString,sessionID:"other") == nil)
            chat.carryToChat(store.reviewedChatDraft(origin:api.baseURL.absoluteString,sessionID:"one")!)
            precondition(chat.draft.hasPrefix("既有聊天草稿\n") && chat.draft.contains("保存我的草稿") && chat.pending == nil && MoodProtocol.calls.count == before)
            pass("confirmed save validates receipt; carry appends existing chat draft without chat or memory request")
            MoodProtocol.reset();let unknown=MoodStore(defaults:defaults);await unknown.bind(api:api,sessionID:"unknown",supported:true)
            unknown.edit(x:0.4,y:0.1,note:"不丢我的原话");MoodProtocol.mode="timeout";await unknown.save()
            let pending=unknown.draft!.pending!;await unknown.refresh();await unknown.save()
            precondition(unknown.draft?.pending?.localID == pending.localID && MoodProtocol.calls.filter {$0.hasPrefix("PUT")}.count == 1)
            let resumed=MoodStore(defaults:defaults);await resumed.bind(api:api,sessionID:"unknown",supported:true)
            precondition(resumed.draft?.pending == pending && !resumed.canSave)
            MoodProtocol.rows=[row(note:pending.note,x:pending.x,y:pending.y)];await resumed.refresh()
            precondition(resumed.draft?.pending == nil && resumed.current?.note == pending.note && MoodProtocol.calls.filter {$0.hasPrefix("PUT")}.count == 1)
            pass("unknown create survives recreation; GET absence stays locked and matching read reconciles without another PUT")
            MoodProtocol.reset();MoodProtocol.rows=[row()];let conflict=MoodStore(defaults:defaults);await conflict.bind(api:api,sessionID:"conflict",supported:true)
            conflict.edit(note:"我的纠正草稿");MoodProtocol.mode="conflict";await conflict.save()
            MoodProtocol.rows=[row(note:"别处的新内容",token:"2026-10-30T00:00:10.000001+00:00")];await conflict.refresh()
            precondition(conflict.draft?.note == "我的纠正草稿" && conflict.draft?.needsReview == true && !conflict.canSave)
            let writes=MoodProtocol.calls.filter {$0.hasPrefix("PUT")}.count;conflict.adoptLatestVersion()
            precondition(conflict.draft?.expectedUpdatedAt == MoodProtocol.rows[0]["updated_at"] as? String && conflict.draft?.note == "我的纠正草稿" && MoodProtocol.calls.filter {$0.hasPrefix("PUT")}.count == writes)
            MoodProtocol.tick=20;MoodProtocol.mode="ack";await conflict.save();precondition(conflict.current?.note == "我的纠正草稿" && conflict.draft?.needsReview == false)
            pass("CAS409 preserves text; explicit latest-version adoption is local only and a separate save is required")
            MoodProtocol.reset();MoodProtocol.rows=[row()];let removed=MoodStore(defaults:defaults);await removed.bind(api:api,sessionID:"removed-version",supported:true)
            removed.edit(note:"原版本删除后仍保留草稿");MoodProtocol.mode="timeout";await removed.save();MoodProtocol.rows=[];await removed.refresh()
            precondition(removed.draft?.pending == nil && removed.draft?.needsReview == true && removed.draft?.note == "原版本删除后仍保留草稿")
            let beforeAdopt=MoodProtocol.calls.count;removed.adoptLatestVersion();precondition(removed.draft?.expectedUpdatedAt == nil && removed.canSave && MoodProtocol.calls.count == beforeAdopt)
            pass("unknown update whose old CAS version is deleted becomes explicit-review conflict, never an automatic new create")
            MoodProtocol.rows=[row(note:conflict.current!.note,token:conflict.current!.updatedAt)]
            MoodProtocol.mode="false-delete";await conflict.delete();precondition(conflict.draft?.pending?.kind == .delete)
            await conflict.refresh();precondition(conflict.draft?.pending != nil)
            MoodProtocol.rows=[];await conflict.refresh();precondition(conflict.draft?.pending == nil && conflict.notice.contains("当前没有记录") && !conflict.notice.contains("明确删除回执"))
            pass("deleted false remains unknown; GET absence confirms current absence without fabricating deletion receipt")
            MoodProtocol.reset();MoodProtocol.rows=[row()];let deleting=MoodStore(defaults:defaults);await deleting.bind(api:api,sessionID:"delete",supported:true)
            await deleting.delete();precondition(deleting.current == nil && deleting.notice.contains("明确删除回执"))
            pass("confirmed delete requires actual true acknowledgement")
            MoodProtocol.reset();let race=MoodStore(defaults:defaults);MoodProtocol.holdGET=true
            let oldRead=Task {await race.bind(api:api,sessionID:"old",supported:true)}
            for _ in 0..<2000 where MoodProtocol.held.isEmpty {await Task.yield()}
            precondition(MoodProtocol.held.count == 1);let heldRead=MoodProtocol.held.removeFirst();MoodProtocol.holdGET=false
            await race.bind(api:try client("http://127.0.0.1:19102"),sessionID:"new",supported:true);race.edit(note:"新服务草稿")
            heldRead.fail();await oldRead.value
            precondition(race.ready && race.draft?.sessionID == "new" && race.draft?.note == "新服务草稿")
            pass("late failure from old origin/conversation cannot replace newer loaded state or draft")
            MoodProtocol.reset();let same=MoodStore(defaults:defaults);MoodProtocol.holdGET=true
            let sameOld=Task {await same.bind(api:api,sessionID:"same-generation",supported:true)}
            for _ in 0..<2000 where MoodProtocol.held.isEmpty {await Task.yield()}
            precondition(MoodProtocol.held.count == 1);let sameHeld=MoodProtocol.held.removeFirst();MoodProtocol.holdGET=false;same.suspend()
            await same.bind(api:api,sessionID:"same-generation",supported:true);same.edit(note:"同服务的新一轮")
            sameHeld.fail();await sameOld.value
            precondition(same.ready && same.draft?.note == "同服务的新一轮" && !same.busy)
            pass("same-origin/same-conversation rebinding rejects an older generation failure")
            MoodProtocol.reset();let late=MoodStore(defaults:defaults);await late.bind(api:api,sessionID:"late-old",supported:true);late.edit(x:0.3,y:0.4,note:"原服务未决")
            MoodProtocol.holdPUT=true;let oldSave=Task {await late.save()}
            for _ in 0..<2000 where MoodProtocol.held.isEmpty {await Task.yield()}
            precondition(MoodProtocol.held.count == 1);let heldSave=MoodProtocol.held.removeFirst();MoodProtocol.holdPUT=false;late.suspend()
            await late.bind(api:api,sessionID:"late-new",supported:true);late.edit(note:"新对话草稿")
            heldSave.finish(row(note:"原服务未决",x:0.3,y:0.4));await oldSave.value
            precondition(late.draft?.sessionID == "late-new" && late.draft?.note == "新对话草稿" && late.draft?.pending == nil)
            await late.bind(api:api,sessionID:"late-old",supported:true);precondition(late.draft?.pending?.kind == .save)
            pass("late successful save cannot mutate another generation; original pending remains persisted for read-only reconciliation")
            MoodProtocol.reset();let failure=MoodStore(defaults:defaults,writer:{key,data in
                if (try? JSONDecoder().decode(EchoMoodDraft.self,from:data))?.pending != nil {return false}
                defaults.set(data,forKey:key);return true
            });await failure.bind(api:api,sessionID:"storage",supported:true);failure.edit(x:0,y:0,note:"存储失败不上传")
            await failure.save();precondition(!MoodProtocol.calls.contains(where:{$0.hasPrefix("PUT")}) && failure.draft?.note == "存储失败不上传" && failure.draft?.pending == nil)
            pass("failure to persist mutation prevents network write and preserves editable text")
            MoodProtocol.reset();let invalid=MoodStore(defaults:defaults);await invalid.bind(api:api,sessionID:"invalid",supported:true);invalid.edit(x:0,y:0,note:"明确拒绝保留")
            MoodProtocol.mode="invalid";await invalid.save();precondition(invalid.draft?.pending == nil && invalid.draft?.dirty == true && invalid.canSave)
            pass("first definitive 422 keeps a recoverable editable draft")
            print("Mood Store checks: \(count)/\(count) groups passed; synthetic URLProtocol, NOT iOS runtime or device.")
        } catch {print("MOOD_STORE_FAIL:",error.localizedDescription);exit(1)}
    }
}
