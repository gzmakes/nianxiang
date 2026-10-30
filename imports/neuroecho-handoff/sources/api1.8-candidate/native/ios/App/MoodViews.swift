import SwiftUI

struct MoodView: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var model=MoodStore()
    @State private var deleting=false
    @State private var discarding=false
    @State private var cancelling=false
    @State private var retrying=false
    @State private var confirmationID: UUID?
    let onChat: (String) -> Void
    private var supported: Bool {store.capabilities?.features["daily_mood_entries"] == true}
    private var ledgerSupported: Bool {store.capabilities?.features["mood_operation_ledger"] == true}
    private var scope: String {store.scopeIdentity+"|"+(store.sessionID ?? "")+"|\(supported)|\(ledgerSupported)|\(scenePhase == .active)"}
    private var date: Binding<Date> {Binding(get:{
        let f=DateFormatter();f.calendar=Calendar(identifier:.gregorian);f.locale=Locale(identifier:"en_US_POSIX");f.dateFormat="yyyy-MM-dd"
        return model.draft.flatMap {f.date(from:$0.day)} ?? Date()
    },set:{value in Task {guard model.isBound(origin:store.scopeIdentity,sessionID:store.sessionID) else {return};await model.select(day:EchoMood.day(value))}})}
    var body: some View {
        ScrollView {VStack(alignment:.leading,spacing:18) {
            Text(EchoSharedReference.copy_mood_title).font(.title2.bold())
            Text("不用给自己下定义。你可以留下一个位置、一句话，或者什么也不记。").foregroundStyle(EchoPalette.muted)
            Text(EchoSharedReference.copy_mood_context).font(.footnote).foregroundStyle(EchoPalette.muted)
            if let draft=model.draft, model.isBound(origin:store.scopeIdentity,sessionID:store.sessionID) {
                DatePicker("为哪一天留下感受",selection:date,in:...Date(),displayedComponents:.date).disabled(model.busy || !model.supported)
                Text("这是一条你为这一天选定的感受，不代表全天平均。未保存草稿会按日期留在本设备。").font(.footnote).foregroundStyle(EchoPalette.muted)
                GeometryReader {proxy in ZStack {
                    VStack(spacing:1) {HStack(spacing:1) {quadrant("不愉快 · 精力高",.orange);quadrant("愉快 · 精力高",.yellow)};HStack(spacing:1) {quadrant("不愉快 · 精力低",.blue);quadrant("愉快 · 精力低",.green)}}.clipShape(RoundedRectangle(cornerRadius:18))
                    if draft.xSelected && draft.ySelected {Circle().fill(EchoPalette.ink).frame(width:16,height:16).overlay(Circle().stroke(.white,lineWidth:3)).position(x:max(8,min(proxy.size.width-8,(draft.x+1)*proxy.size.width/2)),y:max(8,min(proxy.size.height-8,(1-draft.y)*proxy.size.height/2)))}
                }}.frame(height:190).accessibilityHidden(true)
                VStack(alignment:.leading,spacing:10) {
                    Text(EchoSharedReference.copy_mood_valence).font(.headline)
                    Text(draft.xSelected ? valueLabel(draft.x,low:"偏不愉快",high:"偏愉快") : "还没有选择")
                    Slider(value:Binding(get:{draft.x},set:{model.edit(x:$0)}),in:-1...1,step:0.1).accessibilityLabel(EchoSharedReference.copy_mood_valence).accessibilityValue(draft.xSelected ? valueLabel(draft.x,low:"偏不愉快",high:"偏愉快") : "还没有选择")
                    if !draft.xSelected {Button("感受选中间") {model.edit(x:0)}.frame(minHeight:44)}
                    Text(EchoSharedReference.copy_mood_energy).font(.headline)
                    Text(draft.ySelected ? valueLabel(draft.y,low:"精力偏低",high:"精力偏高") : "还没有选择")
                    Slider(value:Binding(get:{draft.y},set:{model.edit(y:$0)}),in:-1...1,step:0.1).accessibilityLabel(EchoSharedReference.copy_mood_energy).accessibilityValue(draft.ySelected ? valueLabel(draft.y,low:"精力偏低",high:"精力偏高") : "还没有选择")
                    if !draft.ySelected {Button("精力选中间") {model.edit(y:0)}.frame(minHeight:44)}
                    TextField(EchoSharedReference.copy_mood_note,text:Binding(get:{draft.note},set:{model.edit(note:$0)}),axis:.vertical).textFieldStyle(.roundedBorder).lineLimit(3...8)
                }.disabled(model.busy || draft.pending != nil || !model.supported)
                if draft.note.unicodeScalars.count > 1000 {Text("文字超过1000字，原文保留，请缩短后再确认。").font(.footnote)}
                if let pending=draft.pending {
                    VStack(alignment:.leading,spacing:10) {
                        Text(pending.kind == .save ? "上次保存仍待核对；原位置、文字与版本已保留。" : "上次删除仍待核对；原版本已保留。").font(.footnote)
                        if pending.hasLedgerIdentity {
                            if draft.cancelRequested == true {Text("取消意图已保留，不能再提交原写入。取消若晚于写入，不会撤回已经处理的内容。").font(.footnote)}
                            if model.canRetryLedger {Button(EchoSharedReference.copy_mood_recovery_retry) {confirmationID=pending.localID;retrying=true}.frame(minHeight:44)}
                            Button(EchoSharedReference.copy_mood_recovery_cancel) {confirmationID=pending.localID;cancelling=true}.frame(minHeight:44).disabled(!model.canRecoverLedger)
                        } else {Text("这是旧版本留下的未决请求，只能只读核对；不会补造编号或重发。").font(.footnote)}
                    }
                }
                if draft.needsReview {
                    VStack(alignment:.leading,spacing:10) {
                        Text("先看最新记录，再决定").font(.headline)
                        if model.ready {
                            if let current=model.current {Text("最新位置：\(valueLabel(current.x,low:"偏不愉快",high:"偏愉快"))，\(valueLabel(current.y,low:"精力偏低",high:"精力偏高"))。\n\(current.note)").textSelection(.enabled)}
                            else {Text("最新状态：这一天当前没有记录。")}
                        }
                        Button("我已核对，采用最新版本并保留草稿") {model.adoptLatestVersion()}.frame(minHeight:44).disabled(!model.canAdoptLatest)
                        Text("只更新版本，不会自动保存；仍需你再次确认。").font(.footnote)
                    }.echoCard()
                }
                if !model.notice.isEmpty {Text(model.notice).font(.footnote).foregroundStyle(EchoPalette.muted).textSelection(.enabled)}
                Button(EchoSharedReference.copy_mood_save) {Task {guard model.isBound(origin:store.scopeIdentity,sessionID:store.sessionID) else {return};await model.save()}}.buttonStyle(EchoPrimaryButton()).disabled(!model.canSave)
                Button(draft.pending?.hasLedgerIdentity == true ? EchoSharedReference.copy_mood_recovery_check : "只读刷新并核对") {Task {guard model.isBound(origin:store.scopeIdentity,sessionID:store.sessionID) else {return};await model.refresh()}}.frame(minHeight:44).disabled(model.busy || !model.supported)
                if draft.dirty && draft.pending == nil {Button("放弃这份未保存修改") {discarding=true}.frame(minHeight:44).disabled(model.busy || !model.ready)}
                if model.canDelete {Button("删除这一天的记录",role:.destructive) {deleting=true}.frame(minHeight:44)}
                if let current=model.current, model.ready && !draft.dirty && draft.pending == nil {
                    VStack(alignment:.leading,spacing:12) {
                        Text("如果你愿意，我们也可以聊聊").font(.headline)
                        Text(current.chatDraft).font(.footnote).textSelection(.enabled)
                        Button(EchoSharedReference.copy_mood_to_chat) {guard let text=model.reviewedChatDraft(origin:store.scopeIdentity,sessionID:store.sessionID) else {return};onChat(text);dismiss()}.frame(minHeight:44).disabled(model.busy)
                        Text("只追加到原聊天草稿，由你查看并按发送；不会自动发消息或保存为记忆。发送后，选定文字会按当前聊天模型处理。").font(.footnote).foregroundStyle(EchoPalette.muted)
                    }.echoCard()
                }
                Text("这只是本人的日记，不是心理诊断，也没有设备情绪识别或自动练习。").font(.footnote).foregroundStyle(EchoPalette.muted)
            } else {ProgressView("正在打开日记")}
        }.padding(20)}.disabled(!model.isBound(origin:store.scopeIdentity,sessionID:store.sessionID)).background(EchoBackground()).navigationTitle("心情记录").echoProtectingEdits().echoInlineNavigationTitle()
        .toolbar {ToolbarItem(placement:.cancellationAction) {Button("关闭，保留草稿") {dismiss()}.disabled(model.busy)}}
        .interactiveDismissDisabled(model.busy)
        .task(id:scope) {
            guard scenePhase == .active, let sid=store.sessionID else {model.suspend();return}
            await model.bind(api:store.api,sessionID:sid,supported:supported,ledgerSupported:ledgerSupported)
        }
        .onDisappear {model.suspend()}
        .confirmationDialog("删除这一天的心情记录？",isPresented:$deleting,titleVisibility:.visible) {
            Button("确认删除",role:.destructive) {Task {guard model.isBound(origin:store.scopeIdentity,sessionID:store.sessionID) else {return};await model.delete()}};Button("保留",role:.cancel) {}
        } message: {Text("仅删除这一天的日记，聊天与独立记忆保留；会核对已读版本。")}
        .confirmationDialog("放弃这份未保存修改？",isPresented:$discarding,titleVisibility:.visible) {
            Button("放弃修改",role:.destructive) {model.discardDraft()};Button("继续保留",role:.cancel) {}
        }
        .confirmationDialog(EchoSharedReference.copy_mood_recovery_retry,isPresented:$retrying,titleVisibility:.visible) {
            Button("确认用原编号与原内容重试") {Task {guard model.isBound(origin:store.scopeIdentity,sessionID:store.sessionID),model.draft?.pending?.localID == confirmationID else {return};await model.retryOperation()}};Button("先不重试",role:.cancel) {}
        } message: {Text("不会创建另一笔提交，也不会换编号或修改原内容；服务会核对原账本。如果已处理，会返回原结果。")}
        .confirmationDialog(EchoSharedReference.copy_mood_recovery_cancel,isPresented:$cancelling,titleVisibility:.visible) {
            Button("确认取消这次提交",role:.destructive) {Task {guard model.isBound(origin:store.scopeIdentity,sessionID:store.sessionID),model.draft?.pending?.localID == confirmationID else {return};await model.cancelOperation()}};Button("先只读核对",role:.cancel) {}
        } message: {Text("先保存取消意图，再请求服务取消。若写入已经处理，取消不会回滚；仍会读取当前记录核对。草稿保留。")}
    }
    private func quadrant(_ text: String,_ color: Color) -> some View {Text(text).font(.caption).frame(maxWidth:.infinity,maxHeight:.infinity).background(color.opacity(0.18))}
    private func valueLabel(_ value: Double,low: String,high: String) -> String {abs(value) < 0.05 ? "中间" : value < 0 ? low : high}
}
