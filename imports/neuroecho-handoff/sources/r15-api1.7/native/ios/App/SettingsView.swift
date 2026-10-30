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
                else {Text(store.capabilities == nil ? "服务能力尚未核对，可在下方检查更新；尚不能判断联系边界是否可用。" : "当前服务未声明统一联系边界能力。").font(.footnote)}
            }
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
                ChangeSyncStatusText().font(.footnote)
                ChangeCheckButton()
                if store.capabilities != nil && store.capabilityReadFailed {Text("能力清单暂未重新读到，上次结果仍保留；可稍后再检查。").font(.footnote)}
                Text("仅发现同一服务的更新，不自动发送、不处理写入重试，也不是推送或离线合并。").font(.footnote).foregroundStyle(EchoPalette.muted)
            }
            Section("硬件") { Text("Rokid、脑电与手机系统写入均未联调。当前原生端不会申请这些权限，也不显示虚构的设备数据。").font(.footnote) }
            Section("服务能力") {
                if let capabilities = store.capabilities {
                    Text("接口契约 \(capabilities.contractVersion) · \(capabilities.servicePlatform)").font(.footnote)
                    Text(capabilities.features["memory_expected_version_patch"] == true && capabilities.features["memory_expected_version_delete"] == true ? "记忆修改与删除支持版本核对。" : "服务未声明完整的记忆版本保护，请避免同时在多个端修改同一条记忆。").font(.footnote)
                    Text("能力清单描述已实现的接口，不代表账号已授权或设备已连接。").font(.footnote)
                    if capabilities.features["remote_user_authentication"] != true || capabilities.features["realtime_multi_device_sync"] != true { Text("设备连接与实时同步是两件事。这里仅按设备许可访问同一服务，回到前台重新核对；没有跨设备即时推送同步。").font(.footnote) }
                } else { Text("尚未取得服务能力清单，不能据此判断账号、硬件或远程连接已就绪。上方「检查更新」可重新读取。").font(.footnote) }
            }
        }.navigationTitle("设置").toolbar { ToolbarItem(placement:.cancellationAction) { Button("完成") { dismiss() } } }.onAppear { address = store.endpoint }
    }
}
