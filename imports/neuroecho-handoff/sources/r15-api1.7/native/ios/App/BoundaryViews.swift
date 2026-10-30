import SwiftUI

private struct BoundaryProposal: Identifiable {
    let id=UUID()
    let mode: String
    let until: Date?
    let timeZone: String
}

/// Shared service policy only. This view never requests notification permission
/// and never claims a contact opportunity or displays an unsolicited question.
struct BoundarySettingsView: View {
    @EnvironmentObject private var store: EchoStore
    @State private var boundary: EchoCompanionBoundary?
    @State private var expectedRevision: Int?
    @State private var timeZone=TimeZone.current.identifier
    @State private var untilDate=Date().addingTimeInterval(3600)
    @State private var proposal: BoundaryProposal?
    @State private var busy=false
    @State private var needsReview=false
    @State private var latestReadConfirmed=false
    @State private var notice: String?
    @State private var scope=""
    @State private var request=UUID()
    private var supported: Bool {store.capabilities?.features["companion_boundaries"] == true}
    private var canEdit: Bool {supported && boundary?.hasKnownMode == true && expectedRevision != nil && !busy && !needsReview}
    var body: some View {
        Form {
            Section("现在的边界") {
                if let boundary {
                    Text(boundary.mode == "active" ? EchoSharedReference.copy_companion_boundary_active : boundary.label)
                    if let until=boundary.until {Text("至 \(until) · \(boundary.timeZone)").font(.footnote)}
                    Text("版本 \(boundary.revision)"); Text(EchoSharedReference.copy_companion_boundary_effect).font(.footnote).foregroundStyle(EchoPalette.muted)
                } else {Text("尚未读取边界，不会猜测你允许什么。")}
                if let notice {Text(notice).font(.footnote).foregroundStyle(EchoPalette.muted)}
                Button("只读刷新状态") {Task {await read(preserveDraft:true)}}.disabled(busy || !supported)
                if needsReview {
                    Text("上次设置需核对。保留当前选择，不会自动覆盖其他端的新设置。").font(.footnote)
                    Button("我已核对最新状态，继续保留我的选择") {
                        guard latestReadConfirmed, let boundary else {return}
                        expectedRevision=boundary.revision; needsReview=false; notice="已核对；如需更改，请再次选择并确认。"
                    }.disabled(!latestReadConfirmed || busy)
                }
            }
            Section("由你决定") {
                TextField("IANA 时区，例如 Asia/Shanghai",text:$timeZone).echoURLInput()
                Button(EchoSharedReference.copy_companion_boundary_today) {
                    do {proposal=BoundaryProposal(mode:"until",until:try EchoCompanionBoundary.nextMidnight(timeZone:timeZone),timeZone:timeZone)}
                    catch {notice=error.localizedDescription}
                }
                Button(EchoSharedReference.copy_companion_boundary_pause) {proposal=BoundaryProposal(mode:"paused",until:nil,timeZone:timeZone)}
                DatePicker("也可以暂停到",selection:$untilDate,displayedComponents:[.date,.hourAndMinute]).environment(\.timeZone,TimeZone(identifier:timeZone) ?? .current)
                Button("暂停到所选时间") {proposal=BoundaryProposal(mode:"until",until:untilDate,timeZone:timeZone)}.disabled(untilDate <= Date())
                Button(EchoSharedReference.copy_companion_boundary_resume) {proposal=BoundaryProposal(mode:"active",until:nil,timeZone:timeZone)}
            }.disabled(!canEdit)
            Section {
                Text("暂停约束主动联系，你主动聊天仍会得到回应。已有轻问许可（包括未来尚未到期的）失效，之后需重新约定；历史待办仍可查看、完成或取消。恢复不会恢复旧许可或补发错过的联系。").font(.footnote)
                Text("当前 iOS 没有自动轻问或系统通知。这里修改共用服务的边界，已实现呈现的 Web / 桌面也应遵守；不会申请新的账号或通知权限。").font(.footnote).foregroundStyle(EchoPalette.muted)
                if !supported {Text("当前服务尚未声明统一边界能力，更新服务后可用。").font(.footnote)}
            }
        }.navigationTitle(EchoSharedReference.copy_companion_boundary_title).echoProtectingEdits().echoInlineNavigationTitle()
        .task {await read(preserveDraft:false)}
        .onDisappear {request=UUID()}
        .confirmationDialog("确认这个主动联系边界？",isPresented:Binding(get:{proposal != nil},set:{if !$0 {proposal=nil}}),titleVisibility:.visible) {
            Button("确认设置") {guard let value=proposal else {return};proposal=nil;Task {await save(value)}}
            Button("再想想",role:.cancel) {proposal=nil}
        } message: {
            Text(proposal.map {value in value.mode == "active" ? "只恢复今后新约定的联系。已有轻问许可失效，之后需重新约定；待办仍可查看。" : value.mode == "paused" ? "暂停主动联系，直到你明确恢复。已有轻问许可失效，之后需重新约定；待办仍可查看。" : "暂停至 \(value.until.map {ISO8601DateFormatter().string(from:$0)} ?? "待核对") · \(value.timeZone)。已有轻问许可失效，之后需重新约定；待办仍可查看。"} ?? "")
        }
    }
    private func read(preserveDraft: Bool) async {
        guard supported, let sid=store.sessionID else {return}
        let origin=store.scopeIdentity, client=store.api, token=UUID()
        let newScope=origin+"|"+sid
        if scope != newScope {boundary=nil;expectedRevision=nil;needsReview=false;scope=newScope}
        request=token;busy=true;latestReadConfirmed=false
        defer {if request == token {busy=false}}
        do {
            let value=try await client.boundary(sessionID:sid)
            guard request == token, store.scopeIdentity == origin, store.sessionID == sid else {return}
            boundary=value;latestReadConfirmed=true
            if !needsReview {expectedRevision=value.revision}
            if !preserveDraft {timeZone=value.revision == 0 ? TimeZone.current.identifier : value.timeZone}
            if !value.hasKnownMode {notice="服务返回了尚未支持的边界状态；只读保留，请更新客户端。"}
        } catch {if request == token, store.scopeIdentity == origin, store.sessionID == sid {notice="边界暂未读到：\(error.localizedDescription) 已有选择保留。"}}
    }
    private func save(_ value: BoundaryProposal) async {
        guard canEdit, let sid=store.sessionID, let expectedRevision else {return}
        let origin=store.scopeIdentity, client=store.api, token=UUID()
        request=token;busy=true;latestReadConfirmed=false
        defer {if request == token {busy=false}}
        do {
            let result=try await client.updateBoundary(sessionID:sid,expectedRevision:expectedRevision,mode:value.mode,until:value.until,timeZone:value.timeZone)
            guard request == token, store.scopeIdentity == origin, store.sessionID == sid else {return}
            boundary=result;self.expectedRevision=result.revision;notice="已收到边界保存回执，正在只读核对。"
            await store.refreshBoundary();await store.refreshFollowups()
            await read(preserveDraft:true)
            guard store.scopeIdentity == origin, store.sessionID == sid, scope == origin+"|"+sid else {return}
            notice=latestReadConfirmed && boundary?.revision == result.revision
                ? "边界已保存并重新读取。只影响主动联系，历史待办与主动聊天保留。"
                : "已收到保存回执，最新边界仍需核对。请只读刷新，不会自动重发设置。"
        } catch {
            guard request == token, store.scopeIdentity == origin, store.sessionID == sid else {return}
            needsReview=true
            notice=(error as? EchoAPIError)?.statusCode == 409 ? "其他端已改过边界。请刷新并核对，当前选择保留；没有自动覆盖。" : "设置结果需核对，当前选择保留；没有自动重发。"
            await read(preserveDraft:true)
        }
    }
}
