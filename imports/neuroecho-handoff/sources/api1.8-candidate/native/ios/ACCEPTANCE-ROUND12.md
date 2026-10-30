# iOS R12 显式朗读验收

本轮交付是原生 SwiftUI / AVFoundation 源码增量，没有安装 Xcode / iOS SDK，没有模拟器、签名、IPA 或手机真机验收。修改只在 R12 隔离副本的 `native/ios`；R11 / 原始工程保留。

## 用户可用的范围

完整 assistant 回复下新增一个“朗读 / 停止朗读”小按钮，最小触控区 44pt。准备期间显示共享状态文案，不增加大播放器。只有本人点按才调用系统语音，打开聊天、消息到达、刷新、回前台或完成上一段均不会自动朗读。

- `delivery_pending=true` 一律不可朗读。完整或旧版本消息只取**当前画面实际采用的 `displayParts`**，不取尚未呈现的 `text` 后段。多个可见段按顺序组成一段，去掉表情标记、Markdown 标记与链接地址，保留链接文字。空文字不发起语音。
- 切换服务 / 对话 / 话题导致消息不可见、离前台 / 离开聊天、消息删除、正文或段落改变、开始另一条播放时请求 `stopSpeaking(.immediate)`。刷新内容不变可继续；停止后不会自动恢复。
- 每次播放生成独立 UUID / utterance delegate。旧 `didStart` / `didFinish` / `didCancel` 不能更新或清除新播放。Apple 对排队但未播出的 utterance 未必回调 `didCancel`，因此本机先使旧状态失效，不依赖该回调解锁。
- driver 的 stop 若未确认且系统仍在 speaking，不启动重叠的新播放。界面不声称扬声器已经静音；10 秒仍未收到开始回调时显示系统语音暂不可用，用户可继续看文字并另行点按。
- 使用设备可用的 Apple system voice，不选择第三方 provider，不请求 Personal Voice 权限。应用没有 TTS 上传、`/api/voice/clip`、模型调用、麦克风 / ASR、聊天发送、日记或记忆保存路径。没有添加录音权限、后台 audio 模式、系统音量修改或声音下载逻辑。
- 不创建 App 语音文件。下述 WAV 只属于合成验收脚本，运行后立即删除，不是产品功能或用户语音缓存。
- 真实使用共享 `copy_voice_read / stop / disclosure / unavailable / preparing` 五个生成常量。

## 实现入口

| 文件 | 职责 |
|---|---|
| `Sources/EchoCore/SpeechPlayback.swift` | 可见回复准入、可朗读文字、纯状态机、scope / 内容变化失效与 UUID 回调保护；无网络 / 设备 / 存储 |
| `App/SpeechController.swift` | 可替换 `EchoSpeechDriver`、AVSpeechSynthesizer 实现、准备超时、显式停止与错误状态 |
| `App/RootViews.swift` | 每条完整回复的小按钮、共享披露、消息 / 场景变化与 onDisappear 停止；不修改已有聊天发送路径 |
| `HostChecks/SpeechLifecycleChecks.swift` | 用假 driver 驱动真实 Controller，测试晚回调与生命周期，不发声音 |
| `HostChecks/SpeechBufferSmoke.swift` | 真实系统 AVSpeechSynthesizer.write → 临时 WAV，不调用 speak，不播放扬声器 |

原 EchoStore、APIClient、Mood DTO / Store / View、F5 / daily、来源连接、单一持续对话与记忆 CAS 源文件均保持 R11 原样。`Info.plist` 不变。

## 本轮证据

- `VALIDATION-ROUND12.log`：工程生成 / plist 与 pbxproj / Swift parse / Foundation **64 / 64**。原 59 保留，加 5 组准入、旧部分正文、UUID 晚回调、scope / 内容变化失效及无自动恢复检查。
- `HOST-ROUND12.log`：完整 App / Core 在 **macOS** 的 SwiftUI / AVFoundation 类型检查；R9 Store **30**、MoodStore **13**、LedgerStore **17** 组回归；新增实际 SpeechController + 假 driver **9 / 9** 组。覆盖无自动播放、准备 / 开始 / 完成、第二次点按停止、新旧回调隔离、旧可见段、服务 / 对话 / 话题 / 前后台 / 删改、超时、不可用与失败、stop 未确认不重叠。未运行 iOS UIKit 分支。
- `HOST-AVFOUNDATION-BUFFER-ROUND12.log`：真实 macOS AVSpeechSynthesizer.write 使用合成中文与设备 zh-CN 语音，产生 **106,578 字节 / 51,241 帧** RIFF/WAVE PCM16，读取确认有效帧与非零采样。临时 WAV 已删除。这证明此宿主可合成缓冲音频，**不证明产品 speak 的扬声器播放、主观音色或 iOS 真机音频路由**。
- XCTest 源码同步新增场景，仅语法检查；没有运行 XCTest / UI test。历史 R8–R11 日志与 manifest 仍只代表各轮历史证据，R12 未重跑历史 HTTP。

## Apple 官方依据（2026-10-30 核对）

1. [AVSpeechSynthesizer](https://developer.apple.com/documentation/avfaudio/avspeechsynthesizer)：排队 utterance、需保留 synthesizer、delegate 监控开始 / 完成。本轮同时核对本机 macOS SDK 的 `AVSpeechSynthesis.h`。
2. [stopSpeaking(at:)](https://developer.apple.com/documentation/avfaudio/avspeechsynthesizer/stopspeaking(at:))：指定停止边界，返回 Bool，停止会移除未读队列。
3. [didCancel](https://developer.apple.com/documentation/avfaudio/avspeechsynthesizerdelegate/speechsynthesizer(_:didcancel:))：未播出的 utterance 不保证取消回调，因此不得用回调到达作为清理前提。
4. [speechVoices()](https://developer.apple.com/documentation/avfaudio/avspeechsynthesisvoice/speechvoices())：获得设备可用语音；本轮不申请个人声音权限或下载语音。
5. [write(_:toBufferCallback:)](https://developer.apple.com/documentation/avfaudio/avspeechsynthesizer/write(_:tobuffercallback:))：返回合成缓冲区，可供写文件或处理；只用于有界合成验收。

官方页面正文由搜索返回的一手索引与本机 SDK 声明交叉核对；部分文档页面直接打开要求 JavaScript，Markdown 链接工具不支持其 content type，未伪称完成了浏览器交互验收。

## 设备首轮与复跑

1. 安装完整 Xcode / iOS SDK 后编译、签名；真机点按朗读 / 停止，检查声音可用性、静音 / 耳机 / 蓝牙 / 系统中断、VoiceOver、动态字体和 44pt 触控区。
2. 真机复验离前台、杀进程、切话题 / 服务、消息改删、连续快速点击与旧回调；没有声卡 / 扬声器实测时不宣称实际可听或完全停止。
3. `sh native/ios/validate.sh`、`sh native/ios/validate_host.sh`。可选 `sh native/ios/validate_speech_buffer.sh` 仅生成并删除合成 WAV；无可用语音或 15 秒不完成时明确 NOT_COVERED，不安装语音或绕过权限。

打包排除 `.build/`（含备份 / 二进制）、DerivedData、xcuserdata、DB、凭据、签名材料与任何临时音频。仍无跨设备账号同步、原生自动主动问候或后台通知交付。
