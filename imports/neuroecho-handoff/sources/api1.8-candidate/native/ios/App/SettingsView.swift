import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var store: EchoStore
    @Environment(\.dismiss) private var dismiss
    @AppStorage("echo.native.reduceMotion") private var reduceMotion = EchoSharedReference.defaultReduceMotion
    @AppStorage("echo.native.reduceTransparency") private var reduceTransparency = EchoSharedReference.defaultReduceTransparency
    @AppStorage("echo.native.lightStrength") private var strength = EchoSharedReference.defaultLightIntensity
    @State private var address = ""
    var body: some View {
        Form {
            Section("由你决定") { NavigationLink("连接与收回资料") { ConnectionsView() }; if !store.isRemote {NavigationLink("任务与消息草稿") { ActionsView() }} }
            Section("给未来的自己") { NavigationLink("跟进 · 待回应的事") {FollowupsView()}
                if store.capabilities?.features["companion_boundaries"] == true {NavigationLink(EchoSharedReference.copy_companion_boundary_title) {BoundarySettingsView()}}
                else {Text("当前服务未声明统一联系边界能力。").font(.footnote)}
            }
            Section("实验区") { NavigationLink("心情表达实验") { MoodLabView() }; Text("比较两种心情表达方式；结果不会保存。") .font(.footnote).foregroundStyle(EchoPalette.muted) }
            Section("它的光") { Toggle("减少动态",isOn:$reduceMotion); Toggle("降低透明度",isOn:$reduceTransparency); Slider(value:$strength,in:EchoSharedReference.minLightIntensity...EchoSharedReference.maxLightIntensity) { Text("光的强度") }; Text("系统的减少动态与降低透明度设置优先生效；这些偏好只保存在本设备。").font(.footnote).foregroundStyle(EchoPalette.muted) }
            Section("记忆由你决定") { Toggle("聊天后，可以提议记住一件小事",isOn:$store.memoryProposals); Text("默认关闭。开启后只产生待确认提议，不自动成为你确认的事实；也可以长按自己的消息，明确选择「记下这句」。这次发送的选择会与发送标识一起保留，核对与重试不改变原请求。").font(.footnote).foregroundStyle(EchoPalette.muted) }
            Section("回响服务") {
                NavigationLink(EchoSharedReference.copy_connection_devices_title) {DeviceConnectionView()}
                if let notice=store.connectionNotice {Text(notice).font(.footnote).foregroundStyle(EchoPalette.muted)}
                DisclosureGroup("本机开发连接") {
                    TextField("仅模拟器 / 本机 HTTP 地址",text:$address).echoURLInput()
                    Button("连接本机开发服务") {Task {await store.connect(to:address)}}.disabled(store.busy || store.verifyingDevice)
                    Text("此入口仅接受 localhost / 127.0.0.1 / ::1 的 HTTP 开发服务，不发送设备令牌。真机的回环地址指手机自身；连接电脑请使用上方 HTTPS 设备连接。旧无身份的未决状态不迁移到设备连接。").font(.footnote).foregroundStyle(EchoPalette.muted)
                }
                if let error=store.error {Text(error).font(.footnote)}
            }
            Section("其他设备上的变化") {
                if !store.canDiscoverChanges {Text(EchoSharedReference.copy_connection_sync_unsupported).font(.footnote)}
                else if store.changeSyncStatus == .pending {Text(EchoSharedReference.copy_connection_sync_pending).font(.footnote)}
                else if store.changeSyncStatus == .offline {Text(EchoSharedReference.copy_connection_sync_offline).font(.footnote)}
                else if store.changeSyncStatus == .updated {Text(EchoSharedReference.copy_connection_sync_updated).font(.footnote)}
                else {Text("前台会定时只读检查；正在编辑或核对的原请求会保留。").font(.footnote)}
                Button(EchoSharedReference.copy_connection_sync_check) {Task {await store.refreshFromForeground()}}.disabled(store.busy)
                Text("仅发现同一服务的更新，不自动发送、不处理写入重试，也不是推送或离线合并。").font(.footnote).foregroundStyle(EchoPalette.muted)
            }
            Section("硬件") { Text("Rokid、脑电与手机系统写入均未联调。当前原生端不会申请这些权限，也不显示虚构的设备数据。").font(.footnote) }
            Section("服务能力") {
                if let capabilities = store.capabilities {
                    Text("接口契约 \(capabilities.contractVersion) · \(capabilities.servicePlatform)").font(.footnote)
                    Text(capabilities.features["memory_expected_version_patch"] == true && capabilities.features["memory_expected_version_delete"] == true ? "记忆修改与删除支持版本核对。" : "服务未声明完整的记忆版本保护，请避免同时在多个端修改同一条记忆。").font(.footnote)
                    Text("能力清单描述已实现的接口，不代表账号已授权或设备已连接。").font(.footnote)
                    if capabilities.features["remote_user_authentication"] != true || capabilities.features["realtime_multi_device_sync"] != true { Text("设备连接与实时同步是两件事。这里仅按设备许可访问同一服务，回到前台重新核对；没有跨设备即时推送同步。").font(.footnote) }
                } else { Text("尚未取得服务能力清单，不能据此判断账号、硬件或远程连接已就绪。").font(.footnote) }
            }
        }.navigationTitle("设置").toolbar { ToolbarItem(placement:.cancellationAction) { Button("完成") { dismiss() } } }.onAppear { address = store.endpoint }
    }
}

/// A local-only comparison of two input methods. State belongs to this view,
/// not the store, so leaving the experiment discards it.
private struct MoodLabView: View {
    @State private var method = 0
    @State private var x = 0.0
    @State private var y = 0.0
    @State private var selected = false
    @State private var selectedX = false
    @State private var selectedY = false

    var body: some View {
        ScrollView { VStack(alignment:.leading,spacing:18) {
            Text("给感受一个位置").font(.title2.bold())
            Text("试试哪一种方式更容易表达此刻。切换方式时会保留这个试验位置，离开后清空。")
                .foregroundStyle(EchoPalette.muted)
            Picker("表达方式",selection:$method) {
                Text("拖动位置").tag(0); Text("两条滑杆").tag(1)
            }.pickerStyle(.segmented)
            if method == 0 {
                Text("点击或拖动，找到更接近的位置。需要无障碍操作时可切换到两条滑杆。")
                    .font(.footnote).foregroundStyle(EchoPalette.muted)
                map
            } else {
                Text("舒服程度").font(.headline)
                Slider(value:Binding(get:{x},set:{x = $0; selectedX = true; selected = selectedX && selectedY}),in:-1...1,step:0.1)
                    .accessibilityLabel("舒服程度，从不舒服到舒服")
                if !selectedX { Button("舒服程度选中间") { x = 0; selectedX = true; selected = selectedX && selectedY } }
                Text("能量水平").font(.headline)
                Slider(value:Binding(get:{y},set:{y = $0; selectedY = true; selected = selectedX && selectedY}),in:-1...1,step:0.1)
                    .accessibilityLabel("能量水平，从低到高")
                if !selectedY { Button("能量水平选中间") { y = 0; selectedY = true; selected = selectedX && selectedY } }
            }
            Text(selected ? "舒服程度：\(description(x,low:"不舒服",high:"舒服")) · 能量：\(description(y,low:"低",high:"高"))" : "还没有选定位置。")
                .font(.headline)
            Button("重新试试", action:reset).frame(minHeight:44)
            Text("这是交互实验，不是心理诊断。不会保存或上传，也不会读取对话、手表、眼镜或脑电数据。")
                .font(.footnote).foregroundStyle(EchoPalette.muted)
        }.padding(20) }.navigationTitle("心情表达实验").onDisappear { reset() }
    }

    private func reset() { x = 0; y = 0; selected = false; selectedX = false; selectedY = false; method = 0 }

    private var map: some View {
        GeometryReader { proxy in
            ZStack {
                VStack(spacing:2) {
                    HStack(spacing:2) { quadrant("不舒服 · 能量高",EchoPalette.peach.opacity(0.35)); quadrant("舒服 · 能量高",EchoPalette.blue.opacity(0.3)) }
                    HStack(spacing:2) { quadrant("不舒服 · 能量低",EchoPalette.blue.opacity(0.18)); quadrant("舒服 · 能量低",EchoPalette.peach.opacity(0.2)) }
                }.clipShape(RoundedRectangle(cornerRadius:18))
                if selected {
                    Circle().fill(EchoPalette.ink).frame(width:18,height:18).overlay(Circle().stroke(.white,lineWidth:3))
                        .position(x:max(9,min(proxy.size.width-9,(x+1)*proxy.size.width/2)),y:max(9,min(proxy.size.height-9,(1-y)*proxy.size.height/2)))
                }
            }.contentShape(Rectangle()).gesture(DragGesture(minimumDistance:0).onChanged { value in
                guard proxy.size.width > 0, proxy.size.height > 0 else { return }
                let horizontal = Double(value.location.x / proxy.size.width)
                let vertical = Double(value.location.y / proxy.size.height)
                x = max(-1.0, min(1.0, 2.0 * horizontal - 1.0))
                y = max(-1.0, min(1.0, 1.0 - 2.0 * vertical))
                selectedX = true; selectedY = true; selected = true
            })
        }.frame(height:240).accessibilityHidden(true)
    }
    private func quadrant(_ label: String,_ color: Color) -> some View {
        Text(label).font(.caption).multilineTextAlignment(.center).frame(maxWidth:.infinity,maxHeight:.infinity).background(color)
    }
    private func description(_ value: Double,low: String,high: String) -> String {
        if abs(value) < 0.05 { return "中间" }
        return "\(value < 0 ? low : high) \(Int((abs(value)*100).rounded()))%"
    }
}
