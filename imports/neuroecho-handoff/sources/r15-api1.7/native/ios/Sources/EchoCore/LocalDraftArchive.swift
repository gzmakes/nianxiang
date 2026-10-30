import Foundation

/// A display-only copy: deliberately contains no request ID, operation JSON,
/// bearer, API client or method that can reactivate/replay a saved operation.
public struct EchoLocalDraftText: Identifiable,Equatable,Sendable {
    public let id: String
    public let title: String
    public let text: String
    public let detail: String
}
public struct EchoLocalDraftArchive: Equatable,Sendable {
    public let entries: [EchoLocalDraftText]
    public let unreadableCount: Int
    public static func read(defaults: UserDefaults,profile: EchoDeviceProfile) -> Self {
        let namespace=profile.namespace,sid=profile.conversationID
        let encoded=Data(namespace.utf8).base64EncodedString(),suffix="."+encoded
        var entries=[EchoLocalDraftText](),unreadable=0
        func add(_ id: String,_ title: String,_ text: String,_ detail: String) {
            guard !text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else {return}
            entries.append(.init(id:id,title:title,text:text,detail:detail))
        }
        if let text=defaults.string(forKey:"echo.native.draft.v1."+encoded) {add("chat","未发送的聊天草稿",text,"仅保存在这份原连接的本机草稿；没有发送。")}
        func decode<T: Decodable>(_ type: T.Type,_ key: String) -> T? {
            guard defaults.object(forKey:key) != nil else {return nil}
            guard let data=defaults.data(forKey:key),let value=try? JSONDecoder().decode(type,from:data) else {unreadable+=1;return nil}
            return value
        }
        if let value=decode(EchoPendingTurn.self,"echo.native.pending-turn.v1"+suffix) {
            if value.origin == namespace && value.sessionID == sid {add("chat-pending","原发送的文字副本",value.text,"原请求结果仍需在原服务核对，可能已处理；这里不恢复标识、不重发，也不代表已取消。")}
            else {unreadable+=1}
        }
        for (key,id,title) in [("echo.native.pending-followup.v1","followup-pending","原跟进提交的文字副本"),("echo.native.followup-draft.v1","followup-draft","待修改的跟进草稿"),("echo.native.followup-rejected-draft.v1","followup-legacy","旧跟进草稿")] {
            if let value=decode(EchoPendingFollowup.self,key+suffix) {
                if value.origin == namespace && value.sessionID == sid {add(id,title,value.content,"原约定时间："+value.dueAt+"。这只是本机文字副本，不证明服务端当前状态，也不恢复联系许可。")}
                else {unreadable+=1}
            }
        }
        if let value=decode(EchoFollowupFormDraft.self,"echo.native.followup-form.v1."+encoded) {
            if value.origin == namespace && value.sessionID == sid {add("followup-form","未提交的跟进表单",value.content,"仅保留原文字；这里不恢复时间、周期或轻问许可，也不创建跟进。")}
            else {unreadable+=1}
        }
        let moodScope=Data((namespace+"|"+sid).utf8).base64EncodedString()
        let prefix="echo.native.mood-draft.v1."+moodScope+"."
        // Enumerate only this application's known exact identity prefix. The
        // decoded identity/date must also agree; foreign keys are never read.
        for key in defaults.dictionaryRepresentation().keys.filter({$0.hasPrefix(prefix)}).sorted() {
            let day=String(key.dropFirst(prefix.count))
            guard EchoMood.validDay(day) else {unreadable+=1;continue}
            guard let value=decode(EchoMoodDraft.self,key) else {continue}
            guard value.origin == namespace,value.sessionID == sid,value.day == day else {unreadable+=1;continue}
            guard value.dirty || value.pending != nil else {continue}
            let position="感受："+(value.xSelected ? String(value.x) : "未选择")+"；精力："+(value.ySelected ? String(value.y) : "未选择")
            add("mood-"+day,day+" 的心情草稿",position+(value.note.isEmpty ? "" : "\n"+value.note),value.pending == nil ? "本人记录的本机草稿，不是心理诊断；没有带到聊天。" : "含未决提交，可能已处理或删除；这里不恢复操作标识、不重试，也不代表已取消。")
        }
        return Self(entries:entries,unreadableCount:unreadable)
    }
}
