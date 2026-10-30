# Brain Bookmark 与 dsh-pet：实际实现、许可与最薄集成核查

核查日期：2026-10-27。范围为公开网站、GitHub原始文件、原始数据集与npm元数据；没有运行仓库代码、安装软件、启动插件、访问用户凭据或修改演示站。静态代码审阅可以证明代码路径存在，不能证明本机硬件/插件已经跑通。

## 结论先行

1. **Brain Bookmark已经有可用的交互书签流程，但公开站不是实时BCI或真正的分心识别。** 波形和模型事件是公开EEG的预计算回放，书签取的是当前网页编辑器。这个边界写得诚实，应保留。
2. **dsh-pet能减少角色展示层的开发，不提供BCI、个人理解或任务代理内核。** 原作者仓库当前0.3.8已有外部HTTP控制、播放回执与独立运行方案。97段是旧描述，本轮原仓树有106个`.webm`文件。
3. **代码与素材许可分开。** 原仓代码MIT，但README明确动画/提示词/源视频禁止商用。不能根据GitHub顶部MIT就把蓝色大肥鱼动画当任意可商用素材。最稳妥的产品路线是复用允许的代码结构，换团队有明确权利的原创角色；对现成素材的比赛展示与获奖/商业转化适用范围，应取得权利人解释，不能由本核查替其授权。
4. 建议的薄链路：`真实采集器/诚实标注的回放 → 质量门控 → 用户可纠正的事件策略 → 工作书签/下一步 → 展示适配器 → 网页/物理终端/可选桌宠`。让桌宠表现“已确认的系统状态”，不要让动画代替算法证据。

## 1 三个不同东西，不要混为一谈

| 名称 | 本轮确认的身份 | 与用户素材的关系 |
|---|---|---|
| DeepSeek模型 | 提供生成/推理能力的模型或API | 可以用于回复或总结，但不等于桌面宠物，也不等于运行时 |
| DeepSeek Harness（dsh） | `deepseek-ai/deepseek-harness`，官方开源Agent运行时，Cordis插件架构，开发者预览，MIT | 官方README明确有破坏性兼容变更；采用它不是采用某个角色素材的授权 |
| PC2005-cloud/dsh-pet | 社区开发的DSH桌宠，含动画、气泡、聊天、事件显示与独立运行 | “97透明动画/蓝色大肥鱼”的描述能对应其旧版本；当前主分支已变化，不是DeepSeek官方角色产品 |
| 用户11秒视频 | 关键画面读取：手机聊天标题“大肥鱼”、蓝发Q版女仆、语音气泡/转写与角色复述 | 这说明一种关系聊天表达。仅凭视频无法确认使用哪个模型、客户端或与dsh-pet是否同源，不可当作同一产品的技术证据 |

同名`dsh-pet`仓库很多，搜索首先命中的`oyang666/dsh-plugin-pet-offline`是离线封装分支，包版本0.2.5，README链接回PC2005-cloud。它的目录结构、能力和原仓当前版本不同；不应把某fork的安装命令/API当原版结论。[P4][P5][P9]

## 2 Brain Bookmark：实现了什么

原站：<https://dililianxice.github.io/brain-bookmark/>。网页明确链接的源码是`Dililianxice/Dililianxice.github.io`仓库的`brain-bookmark/`子目录，不是单独的`brain-bookmark`仓库。[P1][P2]

本轮公开仓快照：`994202d72f665a40279a7f6a5eb8d0853fa404ad`，该子目录仅README、HTML、CSS、`app.js`、`demo-data.json`。没有公开Python训练工程或模型二进制。README提到完整本地工程的`python scripts/export_web_demo.py`，该脚本不在此次公开目录中。

| 能力 | 审阅到的实现 | 准确表述 |
|---|---|---|
| EEG波形与热图 | 从同目录JSON读取历史数据，浏览器Canvas播放；波形为128Hz展示抽样 | 真实公开信号回放，非访问者的实时脑电 |
| 模型得分 | JSON预存每窗口13特征、分类得分、质量与事件；网页按播放时间取出 | 冻结Python模型结果回放，非浏览器在线推理 |
| 触发书签 | `tick()`遍历已到时间且`good && event`的预计算输出，调用`capture()` | 模型事件到书签保存路径存在；类别变化不代表真实走神 |
| 工作上下文 | 本页目标输入、textarea、下一步计划、光标位置；用户输入事件更新位置 | 无跨App读取、无系统截图、无浏览器扩展、无电脑工作上下文采集 |
| 书签持久化 | 两个命名localStorage键；保存全文、当前行片段、用户计划、触发来源与时间 | 当前浏览器的本地保存；不是云端长期记忆、没有跨设备同步 |
| 续做提示 | 有计划直接引用；无计划则拼接已保存行与片段 | 本地规则，不调用LLM、不理解当前取舍理由 |
| “知道了，继续写” | 修改按钮文字 | 不能宣称已自动恢复文件、跳回编辑位置或完成后续工作 |
| 书签下载 | 生成JSON Blob并下载 | 可导出书签数据；没看到外部文件写回或任务执行 |
| 后端/服务 | GitHub Pages静态站；运行期仅`fetch('demo-data.json')` | 没有Python/API后端，未读取用户凭据或上传草稿 |

这里的“真实”分两层：**历史EEG样本真实，访客当前文字输入也真实；二者不是同一人在同一时刻同步采集。** 代码没有伪装成实时BCI，但路演不得省掉这句话。

默认演示片段是`1909017_task3_row1231`：21秒，全程真值为困难心算。JSON中唯一候选事件在20秒，平滑状态由1转2（中等→困难），并非由专注转分心。它适合作为工程链路联调样例，不适合估计真实走神触发率，也不能据此说发生了现实注意力恢复。[P2]

## 3 解码链：已公开参数与未公开证据

### 可以确认的算法声明

网站与README写明：Fp1单通道、名义512Hz、质量检查、1–40Hz四阶因果Butterworth带通；4秒窗、2秒步长；Welch频谱13项特征；比较逻辑回归、随机森林、梯度提升并按验证集选默认模型。窗内重置滤波器，训练/回放同处理是项目声明，尚无训练脚本独立复核。

13项为四频段δ1–4、θ4–8、α8–13、β13–30Hz的log绝对功率4项和相对功率4项，再加logθ/β、logα/β、logRMS、log方差、归一化谱熵；相对功率分母1–40Hz。连续判定使用三次得分平均、连续三次满足规则、最高得分至少0.5、冷却15秒，质量不佳暂停。网页读取预计算事件，**这些状态门控不在网页端重新运算**。

JSON有`model_sha256`，但未包含可取得的对应模型文件；这只提供一个标识，不构成可复现实验。[P2]

### 数据源原文真正说了什么

Mendeley Data v1于2025-07-04发布，作者Asadul Islam Hamzah、Md Zahid Hasan、Fazlul Khondakar，DOI`10.17632/gy4sbnn389.1`，CC BY4.0。原页描述Neurosky Mindwave、FP1单通道，三个指定任务分别是闭眼放松、中等心算、更难心算，标签为0/0.5/1；每人每任务约60秒。原页没交代本项目所需的精确时钟、参考电极、原始物理单位或跨设备标定。[P3]

原页称50位参与者，Demo称51个原始ID、48个有合格窗。**ID数量与真实参与者数量的差异尚未解释，不能把51ID写成已确认51人。**

### 59.5%能说到哪

网站声明冻结默认模型的三类平衡准确率59.5%，多数类基线平衡准确率33.3%；固定划分的测试11个ID中10个有合格窗、255个窗，窗口存在重叠。页面对口径和局限有清楚说明，但公开版没有训练代码、划分ID清单、完整测试预测/真值、超参数与模型文件，因此本次不能复算，也不能独立确认无泄漏。这里是**项目自报且边界清楚的实验结果**，不是本次审计验证成绩。

任务标签不等于连续心理状态真值：闭眼会显著改变某些节律，心算难度也不等于走神。分类高于基线只能说明特定数据上的任务可分性；不能证明识别日常分心、情绪、工作负荷真值或休息需求。

**还缺的最小研究证据**：原始记录单位/参考/时钟；按受试者和连续记录分组的split manifest；滤波与质量规则；训练代码/依赖版本/超参数；冻结模型及哈希；每ID混淆矩阵、宏平均口径；独立于任务条件的真实中断/走神标注；新设备新人的迁移评测。4秒窗意味着至少4秒原始观察，再叠步长与连续证据；不能把低延迟动画写成毫秒级生理判定。

## 4 dsh-pet原仓：当前能力与版本

原仓：<https://github.com/PC2005-cloud/dsh-pet>。快照`b78e3fcf92ac78cee569aed7cc27eeb2a8d51757`。主分支`dsh-pet/package.json`与读取到的npm `latest`均为**0.3.8**。作者提醒主分支小修可能尚未发布，所以最后实施仍应锁定commit、包版本与DSH版本，不采用模糊“最新版”。[P4][P5]

README称在DSH`0.2.1-rc.2`开发/测试；manifest声明`0.2.0-rc.1`、`0.2.0-rc.2`、`0.2.1-rc.2`兼容、`0.1.7-rc.2`不兼容。包要求Node≥22.12，React18.2，注入DSH宿主与客户端服务；这些是作者声明，未在当前机器安装验收。[P5]

**入口分层**：

- 宿主`dsh-pet/src/host/index.ts`：Cordis插件，注入webServer、agentDefaultModel、credentials、llm、commands、connection；组装路由、记忆、事件、桌面helper。
- 浏览器`dsh-pet/src/client/`：Web overlay；并非普通独立React组件入口即插即用。
- 桌面`runtime/electron-helper/`：透明置顶小窗、独立渲染与共享逻辑，需要桌面运行环境。
- 独立CLI`dsh-pet-standalone`：不启动完整DSH的本机服务/桌宠路径存在；独立AI功能的源码和文档正在演进，不能默认继承DSH全部凭据、模型、通知和代理能力。

**已有的外部通道**：[P6]

| 通道 | 能做的事 | 集成边界 |
|---|---|---|
| HTTP `/dsh-pet-7340` | 状态、独占锁、外来文本气泡、点播动画、播放回执、位置、菜单、配置、外写工作状态 | 本机服务，不是公共云API。数据由`GET /state`读，支持counter长轮询 |
| Cordis `petApi7340` | 页内状态/姿态/播放进度/菜单读取；宿主侧另有余额注册 | 宿主与浏览器容器各自一份，不可把同名服务当跨进程总线。外部驱动动作优先走HTTP |
| DSH session events | 监听`session/event`的turn/start、tool/call、tool/result、approval/asked、turn/end、todo/write等 | 表示Agent任务生命周期，**不是用户生理/情绪事件**；需由我们适配新的事件模型 |

原代码与OpenAPI已读到`/lock`、`/broadcast`、`/anim`和回执等实际路由，不只是README想法。`/anim`返回playbackId；`GET /playback/{id}`查渲染回执。这样可以区分“已请求播放”与“实际播完”。用户拖动/隐藏会撤销控制锁，适合保留用户优先。

本机HTTP文档明确只监听127.0.0.1且无鉴权，不能直接端口转发为云端控制。跨域网页/HTTPS访问本机还需浏览器本地网络与来源策略；不能把“有HTTP端点”理解成云端H5直接fetch必然成功。最薄方案是同源或本地桥接、只开放必要命令、让用户看到当前连接状态，而不是向公网暴露全部管理接口。

### 角色素材与播放格式

旧fork为97段VP9-alpha WebM，原仓当前树计数106段，不能固定承诺“97就是当前资产清单”。无需把全部素材下载/预加载；原型只需待机、等确认、执行中、完成、信号不可用等少量自己有权使用的表现。

原仓作者描述Chromium/Firefox可透明播放，Safari WebM alpha存在黑底，另提供HEVC MOV流程/发布资产；本次未做跨端实播。网页上可技术性复用透明video+双缓冲renderer，但脱离DSH必须重写配置/状态/资源服务适配；不能原样import宿主插件期待它成为H5。

## 5 许可边界：三个层次

| 部分 | 本轮读到的许可 | 对产品的处理 |
|---|---|---|
| Brain Bookmark公开代码 | GitHub仓库metadata无许可证，公开目录未找到授权文件 | 看得见不等于可复制重分发；队友原作可由本人明确授权团队，需确认完整本地工程的权利 |
| 原始EEG数据 | 原始发布页CC BY4.0，Demo已有作者/DOI/加工说明 | 保留署名、许可链接、处理说明，不暗示原作者背书；算法文件仍是另一份许可问题 |
| dsh-pet代码 | LICENSE为MIT，版权所有PC2005-cloud | 按许可保留版权与声明；不是取得DeepSeek商标或任意附带资产的权利 |
| dsh-pet动画/提示词/源视频 | README明确“允许开源使用，禁止商用” | 不直接作为可商用的默认角色包；比赛展示、获奖与后续发布边界不在本核查中擅自扩大 |
| 字体/音频/表情包及角色近似 | 当前未逐项证明完整权利链 | 不能因为代码MIT就自动归为MIT；生产包改用明确授权素材，避免复制未核的字体/声音 |
| DeepSeek品牌 | 官方Brand Guidelines允许准确说明关联，要求避免造成官方授权/合作误解 | “社区桌宠适配”与“DeepSeek官方产品/官方合作”分开，不以官方品牌包装参赛作品 |

这是对公开许可文本的读取，不代替权利人授权解释。最省时间的路径是**把允许复用的交互/状态结构与自有角色素材组合**；不需要为了交互实验先取得整套蓝色大肥鱼资产的商业权利。[P8]

## 6 最薄集成方案：先接口化，不先换整套内核

### 方案A 优先：现有页面/Agent保留，桌宠只做可替换输出端

```
SignalAdapter (live/replay/synthetic + quality + model/version)
    → PolicyGate (拒绝/静默/质量/授权/冷却)
    → BookmarkService (来源/文档版本/光标/下一步)
    → ActionEvent (需要用户确认的建议或已核实执行状态)
    → PresentationAdapter
         ├─ Web圆形终端/自有角色
         ├─ 物理屏幕/按键/振动
         └─ 可选 dsh-pet本机HTTP
```

优点是BCI、Agent、角色解耦：脑电事件不直接驱动开心/悲伤，先通过质量与权限；动画失败不影响真实任务结果；角色可以替换而不丢记忆。

**桌宠动作最小合同（建议，不是原仓已为我们实现）**：

1. 本地适配器确认`GET /state`和可见petId。
2. 需要呈现一次建议时获取短期`POST /lock?pet=...`。
3. 用`POST /broadcast?...&lock=...`显示由我们的Agent生成/确认的文字；需要动画再`POST /anim`。
4. 保存playbackId并查询回执；只在真实任务回执到达时展示“任务完成”，不是动画结束就宣告任务完成。
5. 用户拒绝/关闭立即更新我们自己的PolicyGate，停止本次展示，释放锁；后续同类事件不重试骚扰。
6. 断连显示“展示端未连接”，保留任务状态与待显示事件，不伪报已触达。

不要为了调用气泡启用dsh-pet自身的完整聊天记忆再与自有Agent竞争。优先使用`broadcast`接受外部文本；是否双写记忆要明确选定单一事实源。桌宠本身的工作状态、模型账户余额和原始生理指标不混成一个状态分数。

### 方案B 更轻：纯H5 renderer

只做一个video/SVG角色壳，接受统一`PresentationEvent`，动作由我们自己的状态机驱动，使用自己明确有权使用的2—5段素材。无需安装DSH、无需额外Electron、无需读取其credentials。桌面悬浮窗作为后续适配，不妨碍本次网页/硬件屏幕演示。

**这条路线只解决表示层。** Agent仍需要可纠正记忆、授权、事件处理、工具执行与真实结果；EEG仍需要设备接入和独立验证，不能因画面很像桌宠就宣称已有Personal Agent。

### 方案C 完整DSH＋插件（条件选）

只有团队确实要它的现成会话/工具/模型插件体系，且能在锁定版本上走通时才选。它能提供Agent运行时，但引入运行时、插件和桌面三层兼容成本。不能为一个宠物形象改掉全部后端。此报告仅分析，没有安装授权或安装动作。

## 7 团队还需补齐的接口与证据

**Brain Bookmark团队接口**：

- 可复现训练包与split manifest、冻结模型/特征顺序/质量规则、测试口径；不要只交JSON动画。
- `SignalEvent`：source、device、channel/reference、sample_rate、units、timestamp、quality、window范围、model与features版本；模型分数必须标记uncalibrated。
- `ContextSnapshot`：材料版本/哈希、授权范围、光标/锚点、用户明确的下一步、采集来源、可纠正解释；真实应用材料不得靠回放EEG自动越权截取。
- `CandidateEvent`：原始任务分类事件与产品推断分开；先允许用户点“这不是走神/我想休息/现在别提醒”，存为局部反馈而非人格结论。
- `TaskReceipt`：创建/执行/查询/撤销分开；重试幂等，不将生成过一段文本当成外部任务完成。

**桌宠/实体终端接口**：

- `PresentationEvent`：eventId、允许显示内容、优先级、过期时间、用户确认要求、期望动作；不要裸转全部脑电/草稿。
- `PresentationReceipt`：accepted/started/finished/cancelled/failed，另有用户点击/拒绝事件；与真实工具回执分开。
- 原仓锁定版本与资产权利、目标浏览器透明播放、硬件屏幕解码格式/帧率/尺寸、断连与停止按钮验收。

## 对PRD最有价值的改动建议

把队友的现有演示纳入“已具备：公开信号回放＋本页书签链路”，把设备/现实分心/真实工作上下文放在独立验收项。把dsh-pet纳入“可复用展示层参考与条件依赖”，而不是新项目核心卖点。真正有说服力的一幕是：系统提出一条有来源的帮助，用户纠正一次，下一次软硬件行为真的改变，真实任务结果可以打开检查。

## 来源索引

P1 原站 https://dililianxice.github.io/brain-bookmark/
P2 演示源码 https://github.com/Dililianxice/Dililianxice.github.io/tree/994202d72f665a40279a7f6a5eb8d0853fa404ad/brain-bookmark
P3 原始EEG数据 https://data.mendeley.com/datasets/gy4sbnn389/1
P4 dsh-pet原仓README https://github.com/PC2005-cloud/dsh-pet/blob/b78e3fcf92ac78cee569aed7cc27eeb2a8d51757/README.md
P5 包清单 https://github.com/PC2005-cloud/dsh-pet/blob/b78e3fcf92ac78cee569aed7cc27eeb2a8d51757/dsh-pet/package.json ；npm元数据 https://registry.npmjs.org/dsh-pet/latest
P6 对外API https://github.com/PC2005-cloud/dsh-pet/blob/b78e3fcf92ac78cee569aed7cc27eeb2a8d51757/API.md ；https://github.com/PC2005-cloud/dsh-pet/blob/b78e3fcf92ac78cee569aed7cc27eeb2a8d51757/openapi.yaml
P7 事件实现 https://github.com/PC2005-cloud/dsh-pet/blob/b78e3fcf92ac78cee569aed7cc27eeb2a8d51757/dsh-pet/src/host/plugin/session-watch.ts
P8 原仓LICENSE https://github.com/PC2005-cloud/dsh-pet/blob/b78e3fcf92ac78cee569aed7cc27eeb2a8d51757/LICENSE ；DeepSeek品牌说明 https://github.com/deepseek-ai/deepseek-harness/blob/22ddee3792402c3e70ec5f86a63c3e3e895a2f60/BRAND_GUIDELINES.md
P9 被排除为原版依据的旧fork https://github.com/oyang666/dsh-plugin-pet-offline
P10 Harness官方仓 https://github.com/deepseek-ai/deepseek-harness
