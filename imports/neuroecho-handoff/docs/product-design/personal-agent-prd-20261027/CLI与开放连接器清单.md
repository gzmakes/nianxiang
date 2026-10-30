# CLI与开放连接器清单

核查日期：2026-10-27。眼镜主候选为Rokid。公开资料核查不等于账户／设备联调通过。

先读主PRD第19节冷启动、第20节嘉宾映射；25项包括CLI、SDK、API及尚待核实项目，以下分清形态。

| 产品／入口 | 公开形态与维护方 | 可做与适合我们的事 | 授权与限制 |
|---|---|---|---|
| [飞书 lark-cli](https://github.com/larksuite/cli)<br>lark-cli | CLI；官方 | 文档、日历等业务工具及用户授权。 一份选定文档形成初步理解，支持后续任务上下文。 | 应用配置＋后台scope＋本人授权＋资源ACL；--as user读取本人资源。 只核帮助和文档；不使用已有用户凭据。文档选择白名单需自建。 |
| [GitHub gh](https://cli.github.com/manual/)<br>gh | CLI；官方 | 仓库、Issue、PR等开发协作操作。 记住一个Issue的断点、核查状态，服务开发者。 | GitHub身份、仓库权限；按实际endpoint限制读写。 不是面向所有C端用户；不以能读PR等同可合并或发布。 |
| [Google Workspace gws](https://github.com/googleworkspace/cli)<br>gws | CLI；googleworkspace仓库项目 | Google Workspace接口的命令行调用。 日历、文档和邮件的国际化上下文。 | Google Cloud项目、OAuth与具体API权限。 README明确不是Google官方支持产品；不因组织名省略该限制。 |
| [Microsoft 365 m365](https://github.com/pnp/cli-microsoft365)<br>m365 | CLI；Microsoft 365 PnP社区 | Microsoft 365、SharePoint、Teams等工作负载。 企业资料和个人工作交接。 | Entra应用与目标权限；部分范围需管理员批准。 社区维护工具；租户管理能力不适合作为C端默认授权范围。 |
| [Apple shortcuts](https://support.apple.com/zh-cn/guide/shortcuts-mac/apd455c82f02/mac)<br>shortcuts | CLI／URL scheme；Apple官方 | Mac上运行用户已有快捷指令并收发文件或文本。 一键交接、用户主动捕捉一个片段。 | macOS本地运行，快捷指令所需权限仍适用。 不是任意App的万能读取API；有交互的指令可能等待用户。 |
| [Home Assistant hass-cli](https://github.com/home-assistant-ecosystem/home-assistant-cli)<br>hass-cli | CLI；Home Assistant生态项目 | 读实体状态、列服务并调用受支持服务。 接一个灯或显示器，核对实际状态与用户停止。 | 可访问的HA实例和个人访问凭据；实体与服务按实例实际清单。 长期token权限未必细到单设备，需在我们执行层做白名单。 |
| [米家 Xiaomi Home 集成](https://github.com/XiaoMi/ha_xiaomi_home)<br>Xiaomi Home → Home Assistant → hass-cli／API | HA集成；可经hass-cli；小米官方支持集成 | 把受支持的小米IoT设备接入Home Assistant。 环境灯光或离场交接，替代再开一个手机弹窗。 | 小米OAuth、HA、账号区域、设备型号和可能需要的网关。 本身不是独立米家CLI；不是所有设备和能力都可用或支持本地控制。 |
| [python-miio miiocli](https://github.com/rytilahti/python-miio)<br>miiocli | CLI＋Python库；社区 | 通过miIO相关协议控制支持的小米家电。 已有兼容设备时探索本地反馈。 | 指定设备、网络与所需设备凭据；按支持矩阵核型号。 与小米官方HA集成是不同路线；兼容、凭据取得和协议变动风险较高。 |
| [Rokid 当前眼镜平台](https://open.rokid.com/)<br>AIUI Studio；CXR-L／CXR-S（按型号） | SDK／Agent入口；官方 | AIUI Studio提供Agent构建／调试／发布；CXR-L经Rokid AI App接IO，CXR-S用于Glasses独立应用。 让用户抬眼看一张来源卡、通过按键或语音继续。 | 先确认Glasses／Max／企业型号、手机端、系统版本和SDK许可。 公开平台不证明已拿到设备或开发权限；当前不以历史CLI冒充现款支持。 |
| [Rokid rokidos-cli（历史）](https://github.com/rokid/rokidos-cli)<br>rokidos-cli 历史仓库，当前不列安装指引 | 开发CLI；官方历史仓库 | 历史RokidOS的配置、安装、构建和测试工具。 用于理解既有开发工具，不列现款Glasses的快接承诺。 | 须核其目标系统与兼容版本。 README历史项目存在不等于支持当下CXR／YodaOS-Sprite；当前优先SDK。 |
| [千问眼镜开放平台（对照）](https://device.qianwen.com/docs/qwen/6679322)<br>Skill／OpenAPI／App SDK | SDK／Skill／OpenAPI；官方平台 | 公开平台列出设备能力、Skill与云云／App SDK对接。 可作为多终端架构对照，当前眼镜主线已换Rokid。 | 开发者入驻、账号、型号、测试绑定和具体开放范围。 未核到独立通用眼镜CLI；平台接入不等于所有拍摄／实时流能力无需准入。 |
| [Apple Health／HealthKit](https://developer.apple.com/documentation/healthkit/authorizing-access-to-health-data)<br>HealthKit 原生接口 | 原生SDK；Apple官方 | 按数据类型申请健康数据访问。 用户允许的活动和睡眠可作为弱上下文。 | 兼容原生App、HealthKit能力与分项授权。 普通H5不能直接读取；读取空结果不能区分拒绝与无样本，不等于EEG。 |
| [Oura Cloud](https://cloud.ouraring.com/docs/authentication)<br>Oura OAuth2 API | OAuth API；官方 | 睡眠、活动等用户授权数据。 可补充前一晚或跨日节奏；无需假定苹果原生桥。 | 注册OAuth应用、本人授权、设备与具体数据可用性。 不是官方CLI；依赖云同步，不当实时脑电或即时情绪。 |
| [Tesla tesla-control＋Fleet API](https://github.com/teslamotors/vehicle-command)<br>tesla-control；Fleet API | 官方CLI＋API；Tesla官方 | 车辆命令协议工具与Fleet数据服务。 研究停车后的任务交接或充电状态，先以只读为范围。 | 开发者应用、用户授权、车型支持及必要的虚拟钥匙；地区／计费另核。 不是全品牌车载接口；公开工具不表示账号已获批准。比赛不做行车控制。 |
| [Android for Cars](https://developer.android.com/training/cars/parked)<br>Android for Cars SDK | SDK／开发工具；Google官方 | 按类别与停车／行驶条件构建车载App。 停车后继续一项任务的交互探索。 | 兼容车机、应用类别、质量要求及分发审核。 开发CLI／adb不是已授权车辆数据或控制API；车机展示与车辆控制不同。 |
| [富途 FutuOpenD](https://openapi.futunn.com/futu-api-doc/en/opend/opend-cmd.html)<br>FutuOpenD网关＋官方SDK | 命令行网关＋SDK；官方 | 命令行启动OpenD，SDK访问行情与获准账户服务。 有授权时为交易复盘提供行情／事件背景。 | OpenD、本人账户、地区与市场数据权限。 启动网关不是一条完整行情／交易CLI；查行情不自动有持仓或下单权限。 |
| [同花顺 hithink-finance](https://fuyao.aicubes.cn/docs/developer-tools/cli/)<br>hithink-finance | CLI＋API／MCP／SDK；服务方官方文档 | 金融数据查询、能力发现及结构化JSON。 在用户预先定义的复盘流程中补充行情事实。 | Node版本、API Key、数据范围与使用许可。 官网CLI页可读，npm元数据latest为0.1.13；对应GitHub直链本轮404，未安装或验证Key，不保证仓库持续公开。数据查询不等于读个人炒股App或持仓。 |
| [OpenCLI／雪球适配](https://github.com/jackwener/opencli/blob/main/docs/adapters/browser/xueqiu.md)<br>opencli xueqiu | 浏览器CLI；社区 | 仓库文档列出行情、自选与讨论等浏览器适配。 探索本人显式允许的市场信息与关注内容。 | Browser Bridge与用户登录态；只按实际可见与允许范围读取。 不是雪球官方OAuth/API授权；协议、限流、平台条款与维护风险独立存在。不提取或分发cookies。 |
| [ComfyUI comfy-cli](https://github.com/Comfy-Org/comfy-cli)<br>comfy | CLI；Comfy Org官方 | 管理ComfyUI并运行工作流。 将用户确认的经历／书签做成原创视觉卡，输出可带走结果。 | 本地工作流需要相应算力、模型；云能力另核账号与费用。 图片生成属于输出，不提供用户记忆；许可、模型和素材分别核。 |
| [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-welcome.html)<br>aws | CLI；AWS官方 | 操作AWS云服务资源与服务API。 部署受控执行、存储与任务日志。 | AWS账号、IAM与具体区域／服务权限。 运行底座，不是用户生活数据源；云资源可能收费。 |
| [Google Cloud gcloud](https://docs.cloud.google.com/sdk/docs/overview)<br>gcloud | CLI；Google官方 | 管理Google Cloud资源。 控制服务部署和身份／日志管理。 | Google Cloud项目、身份与权限。 不是Google Calendar或Google Ads的通用个人数据CLI；别与gws混淆。 |
| [EvoMap Evolver](https://github.com/EvoMap/evolver)<br>evolver | CLI；EvoMap项目 | 生成演化提示与审计经验资产，依赖宿主采用。 把一次失败／纠正沉淀成可审核的回归材料。 | Node、Git及明确选定版本，联网网络功能另行配置。 不是个人资料连接器；输出提示不等于自动修改成功。README有许可迁移提示，核实际版本LICENSE；本次不安装或自改Agent。 |
| [支付宝AI付开发工具](https://aipay.alipay.com/)<br>官方Skill安装工具；支付SDK／沙箱 | Skill安装器＋SDK／平台；官方 | 提供支付接入Skill、SDK与沙箱路径。 未来付费验证或应用收款；不进入当前主闭环。 | 具体产品、申请主体、应用配置、沙箱与正式准入。 安装Skill的npx命令不等于有通用支付执行CLI，更不等于能读取个人账单。 |
| [dsh-pet](https://github.com/PC2005-cloud/dsh-pet)<br>本机HTTP展示服务 | 本地HTTP／插件；社区 | 角色文本、动画与播放回执等本机展示。 表现已保存、等确认和静默状态。 | DeepSeek Harness／插件兼容、本地服务与受限桥接。 不是独立通用CLI；动画素材许可与代码分开；不暴露管理端口。 |
| [Flowith](https://flowith.io/updates/)<br>未核实公开CLI入口 | 公开CLI未确认；产品方公开网站 | 已读官网产品更新及文档入口。 若提供外部调用，可研究生成任务；尚不是确定依赖。 | 需要产品方提供正式API／MCP／CLI入口与准入。 搜索中的Flow CLI可能是另一款类型检查器，不冒认。未找到不代表产品没有未公开接口。 |

未安装、未登录、未执行家居／车辆／金融动作。Skill安装器、SDK、命令行客户端与实际服务权限分开核对。每行附原始来源；Today截图仅作交互参考，不能证明内部技术。