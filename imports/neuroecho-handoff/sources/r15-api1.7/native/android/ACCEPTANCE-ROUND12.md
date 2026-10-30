# Android 第12轮：本人点选的本机朗读

本文件记录第12轮的历史验收；交付源码为本目录，不依赖开发机当时的 work 路径。第13轮设备连接以 `ACCEPTANCE-ROUND13.md` 和本目录源码为准。

## 实际实现

1. 每条完整可见 assistant 回复的“朗读 / 停止朗读”按钮沿用48dp热区与现有白卡；默认不初始化引擎、不播放。Shared 的 READ/STOP/DISCLOSURE/UNAVAILABLE/PREPARING 五个生成文案已被实际 UI 引用。
2. `ReadAloud.kt` 为无 Android 依赖的 policy/controller。按钮重新核对当前地址、唯一对话、消息ID、assistant角色、未pending及当前话题可见性；只读与聊天 UI 相同的 `displayParts`，不拿未展示的完整正文代替。新增 `deliveryFlagValid` 元数据：畸形 pending 字段不允许朗读，旧服务缺字段仍按其完整已显示文本处理。
3. `AndroidReadAloudDriver.kt` 仅在本人点选后绑定系统默认 TTS 引擎；过滤需联网、缺数据或语言不可用的 voice。每段在 setVoice 前重新核验，选后还要核对实际 voice 的身份与离线/安装状态。没有 setLanguage、安装/下载/设置 intent、其他引擎或网络 voice 回退。
4. 初始化标识与每段 utterance 标识分别绑定；初始化回调只接纳当前 PREPARING 一次。系统回调统一回主线程，再核对双标识与最新消息快照；旧初始化、重复初始化、旧段完成/错误都不能覆盖新播放。speak 返回成功仅表示入队，onStart 才展示正在朗读，最后一段 onDone 才结束。
5. 长文字按引擎声明的 UTF-16 长度上限完整分段；边界不拆 emoji 代理对，不静默截断。每段完成后才开始下一段；停止先使旧回调失效；系统确认后才释放引擎。无法完整分段或系统失败明确显示不可用，可继续阅读文字。
6. 初始化和入队各有10秒截止；播放按每段字符量估算15秒至5分钟硬上限，每段最多600 UTF-16字符且不超过引擎限制。可取消timer还带op/utterance/phase/generation核对；重复start不延长截止，旧timer即使已入主线程队列也不能误停新播放。超时只处理当前请求，要求系统停止，不自动重试。
7. 后台/页面离开、地址切换、对话或消息删改、显示片段变化和新播放均请求停止旧朗读；地址保存前显式停止，异步回调也读取最新 model 与前台状态。不会恢复或自动重播上次语音。
8. stop和shutdown使用实际Boolean回执。失败或异常保留“停止结果待核对”，阻止新建引擎/叠播，用户再次停止成功后才释放；没有把已发停止请求当成已停。driver在进程内保留未确认引擎，Activity重建的新driver也需先解决它，不能静默绕过。该Android进程注册薄适配仍未SDK/设备验收。
9. 无新增权限；manifest 仅补 Android 官方要求的 TTS_SERVICE package-visibility query，原 INTERNET 权限不变。没有录音、麦克风、ASR、语音文件、模型或服务端 TTS 请求。来源撤回、F5、记忆CAS及R11持久心情账本未改。

## 已运行

| 范围 | 本轮证据 | 能证明什么 |
|---|---|---|
| 实际 Temurin17 / Kotlin2.1.20 编译纯Core与JUnit | **130 / 130**；`verification-jvm-ROUND12.log` | R11 104项保留，新增26项纯policy/controller状态机；编译文件列表与SHA在日志内 |
| 既有实际 Kotlin EchoApi → 临时 FastAPI/SQLite | **85 / 85**；`verification-backend-http-ROUND12.log` | R11/F5/来源/心情API未受回归；不是系统TTS或Android运行证据 |
| Kotlin PSI语法解析 | **32文件、0语法错误**；`verification-syntax-ROUND12.log` | 仅语法，包括driver/Compose；不解析Android API或Compose类型 |
| 工程结构/XML/权限/契约 | **22项通过**；`verification-static-ROUND12.log` | 结构与XML合法，无新麦克风/存储/通知权限 |
| 共享生成资源 | 通过；`verification-shared-ROUND12.log` | 本端生成资源与根shared相符，已有用户偏好保留 |

26项新增状态机测试覆盖：不自动初始化；非assistant/pending/畸形字段/不可见/后台拒绝；精确可见parts；本机且已安装语音过滤；初始化失败；停止后晚回调；新播放替代；错误标识；入队与真实开始区别；失败不回退；地址/对话/内容/删除/话题/后台变化；回调时动态核对；完整Unicode分段（3999/4000 ASCII+emoji边界）；顺序播放与旧段防重；段间后台停止；引擎长度异常；释放后不重启；平台异常；重复初始化不倒退；init/queue/playback超时；旧timer跨阶段/请求失效；重复start不延期；失败stop阻止新引擎且不自动轮询；shutdown异常保留unknown。

复跑命令（本目录，使用工作区已有JDK与经SHA校验的公开Maven缓存，不联网、不安装SDK）：

```sh
python3 scripts/test_rules_cached.py /absolute/path/to/jdk17 /absolute/path/to/maven
python3 scripts/check_kotlin_cached.py /absolute/path/to/jdk17 /absolute/path/to/maven
python3 scripts/verify_project.py
python3 scripts/sync_shared.py --check
# 用已有FastAPI/uvicorn Python环境，在完整源码包内执行：
python scripts/test_backend_http_cached.py /absolute/path/to/jdk17 /absolute/path/to/maven
```

## 待 Android 平台验收

未安装Android SDK，**未运行Compose/Android类型编译、lint、APK/AAB、模拟器或真机**。driver薄适配只通过语法与只读核对，不能由130项Core或85项Host HTTP代替。系统引擎实际可用性、声音/静音音量、设备离线播放、停止时延、后台/旋转释放、Android11+可见性与200%字号/TalkBack都需开发同学在设备验收。

建议设备流程：在已有离线语音的设备中点完整消息 → 确认只读可见文本 → 点另一条/停止/切话题或地址/后台 → 确认无旧音续播；仅有网络或未安装语音时应明确不可用且不启动下载；长消息中断后旧回调不能续读。没有可用 voice 时不引导授权或自动打开设置。

## 官方依据（2026-10-30实际读取）

- [TextToSpeech](https://developer.android.com/reference/android/speech/tts/TextToSpeech)：初始化、getVoices/setVoice、speak异步入队与长度限制、stop/shutdown，以及Android11+的queries声明。
- [TextToSpeech.Engine](https://developer.android.com/reference/android/speech/tts/TextToSpeech.Engine)：未安装 voice 的选择可能触发下载，因此选择前排除 KEY_FEATURE_NOT_INSTALLED；使用 API21+ Voice离线标志。
- [Voice](https://developer.android.com/reference/android/speech/tts/Voice)：isNetworkConnectionRequired与features。
- [UtteranceProgressListener](https://developer.android.com/reference/android/speech/tts/UtteranceProgressListener)：utterance标识、onStart/onDone/onError/onStop，回调可能来自多个线程。

官方文档通过 web-access 技能规定的公开 Web 搜索/读取路径获取；未操作用户已有浏览器或登录状态。
