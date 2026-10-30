import SwiftUI

struct DeviceConnectionView: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.scenePhase) private var scenePhase
    @State private var address=""
    @State private var token=""
    @State private var leaving=false
    @State private var forgetting=false
    @State private var oldCredential: EchoDeviceProfile?
    var body: some View {
        ScrollView {VStack(alignment:.leading,spacing:18) {
            Text(EchoSharedReference.copy_connection_devices_title).font(.title2.bold())
            Text("把这台设备接回你的同一段对话。先在电脑上的回响生成设备令牌，再把 HTTPS 地址与令牌粘贴到这里。无需新建账号。")
            Text(EchoSharedReference.copy_connection_devices_scope).font(.footnote).echoCard()
            VStack(alignment:.leading,spacing:12) {
                TextField("你的回响 HTTPS 地址",text:$address).echoURLInput().textFieldStyle(.roundedBorder)
                SecureField("电脑一次显示的设备令牌",text:$token).echoURLInput().textFieldStyle(.roundedBorder).privacySensitive()
                Text("连接码由电脑显示一次，仅粘贴到你自己的设备，不要发进聊天或公开分享。").font(.footnote).foregroundStyle(EchoPalette.muted)
                Button(store.verifyingDevice ? "正在核对连接…" : EchoSharedReference.copy_connection_devices_verify) {Task {let accepted=await store.connectDevice(address:address,token:token);if accepted {token=""}}}.buttonStyle(EchoPrimaryButton()).disabled(store.busy || store.verifyingDevice || address.isEmpty || token.isEmpty)
                Text("只有核对设备许可、服务实例与主对话后才保存到本应用钥匙串。验证失败保留原连接；不会忽略证书问题，也不会匿名重试。模型密钥留在电脑上，不要贴到这里。") .font(.footnote).foregroundStyle(EchoPalette.muted)
            }.echoCard()
            if let profile=store.deviceProfile {
                VStack(alignment:.leading,spacing:10) {
                    Text(store.deviceConnected ? "这台设备已连接" : "本机保留的设备连接").font(.headline)
                    Text(profile.origin).textSelection(.enabled)
                    Text(profile.label).font(.subheadline)
                    if let expiry=EchoFollowup.parse(profile.expiresAt) {Text("设备许可到期："+expiry.formatted(date:.abbreviated,time:.shortened)).font(.footnote)}
                    if !store.deviceConnected && !store.forgottenDeviceGenerations.contains(profile.credentialGeneration) {Button("恢复设备连接") {Task {await store.restoreDeviceConnection()}}.frame(minHeight:44).disabled(store.busy || store.verifyingDevice)}
                    if store.forgottenDeviceGenerations.contains(profile.credentialGeneration) {Text("此连接的本机凭据已移除，不能自动恢复。请在电脑上核对或生成新的设备连接；原身份的草稿仍隔离保留。").font(.footnote)}
                    NavigationLink("只读查看这份连接的本机草稿") {LocalDraftArchiveView(profile:profile)}.frame(minHeight:44)
                    if store.deviceConnected {Button("退出本机连接，保留草稿") {leaving=true}.frame(minHeight:44)}
                    Button("移除这台设备保存的令牌",role:.destructive) {forgetting=true}.frame(minHeight:44)
                }.echoCard()
            }
            ForEach(store.savedDeviceProfiles.filter {$0 != store.deviceProfile},id:\.credentialGeneration) {profile in
                VStack(alignment:.leading,spacing:10) {
                    Text("本机保留的原连接 · "+profile.label).font(.headline)
                    Text(profile.origin).font(.footnote).textSelection(.enabled)
                    if store.forgottenDeviceGenerations.contains(profile.credentialGeneration) {Text("本机凭据已移除；原身份草稿仍保留，不会迁给当前连接。").font(.footnote)}
                    else {
                        Button("验证并恢复这份原连接") {Task {if await store.restoreDeviceConnection(profile) {address=store.endpoint}}}.frame(minHeight:44).disabled(store.busy || store.verifyingDevice)
                        Button("移除这份旧连接的本机令牌",role:.destructive) {oldCredential=profile}.frame(minHeight:44)
                    }
                    Text("恢复会先核对同一服务实例、设备和主对话。只读取原身份的草稿与请求状态，不自动重发。").font(.footnote).foregroundStyle(EchoPalette.muted)
                    NavigationLink("只读查看这份连接的本机草稿") {LocalDraftArchiveView(profile:profile)}.frame(minHeight:44)
                }.echoCard()
            }
            if store.connectionFailureCode == "paired_authentication_required" {Text(EchoSharedReference.copy_connection_devices_invalid).font(.footnote).foregroundStyle(EchoPalette.muted)}
            if let notice=store.connectionNotice {Text(notice).font(.footnote).foregroundStyle(EchoPalette.muted).textSelection(.enabled)}
            Text("这不是云端多设备同步。当前只在打开应用时读取同一后端；系统通知、CLI、电脑系统动作与硬件仍不向手机开放。旧身份的本机草稿和未决请求不会自动迁入新设备许可。") .font(.footnote).foregroundStyle(EchoPalette.muted)
        }.padding(20)}.background(EchoBackground()).navigationTitle("设备连接").echoProtectingEdits().echoInlineNavigationTitle()
        .onAppear {address=store.endpoint.hasPrefix("https://") ? store.endpoint : ""}
        .onDisappear {token="";store.cancelDeviceVerification()}
        .onChange(of:scenePhase) {phase in if phase != .active {token="";store.cancelDeviceVerification()}}
        .confirmationDialog("退出本机连接？",isPresented:$leaving,titleVisibility:.visible) {
            Button("退出并保留原身份草稿") {token="";store.disconnectDevice(forgetCredential:false)};Button("继续连接",role:.cancel) {}
        } message: {Text("停止本机继续读取并清除当前画面的私密快照。已发出的操作可能仍在服务端完成；原身份的草稿和未决状态保留，不会自动发送到新连接。")}
        .confirmationDialog("移除本机保存的设备令牌？",isPresented:$forgetting,titleVisibility:.visible) {
            Button("移除本机令牌",role:.destructive) {token="";store.disconnectDevice(forgetCredential:true)};Button("保留",role:.cancel) {}
        } message: {Text("只移除本应用保存的这一份设备凭据，不清除其他钥匙串项目。电脑端许可仍须在电脑撤销；不会删除服务中的对话、日记、记忆或原身份的本机草稿。")}
        .confirmationDialog("移除这份旧连接的本机令牌？",isPresented:Binding(get:{oldCredential != nil},set:{if !$0 {oldCredential=nil}}),titleVisibility:.visible) {
            Button("仅移除这份旧连接的本机令牌",role:.destructive) {if let profile=oldCredential {store.forgetSavedDeviceCredential(profile)};oldCredential=nil};Button("保留",role:.cancel) {oldCredential=nil}
        } message: {Text("当前连接不变。不发送服务端撤销、不删除草稿，只删除本应用为所选身份保存的精确钥匙串条目。移除后不能凭本机记录自动恢复该身份。")}
    }
}
