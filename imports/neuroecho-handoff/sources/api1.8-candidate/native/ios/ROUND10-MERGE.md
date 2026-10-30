# iOS R10 分块合并记录

唯一修改路径为work/round10-integration-src/native/ios；没有修改original或R9交付。改前副本在native/ios/.build/backup-before-r10-moods，打包排除。

新Moods.swift定义独立日记DTO/草稿/不可变未决快照，MoodStore管理本机持久化和严格恢复，MoodViews承载手动界面。只在APIClient追加CRUD和必要的query +编码修复、RootViews插入卡片/sheet；原R9Models/EchoStore/ActionViews/BoundaryViews未覆盖。project用生成脚本重新生成，shared只同步root生成的本端副本。

保持R9每日跟进、F5统一边界、旧pending原payload、未知状态和targeted-stop回执。没有引入原工程“available即被动待办”的旧过滤，也没有用37项旧日志替换本轮54/30/13证据。

只实现本人手动日记，不接原生规则建议/心理练习/自动主动问。带到聊天只是本人选取后的原草稿追加；默认日记不进入模型或记忆。unknown没有账本便不虚构未执行，CAS冲突读最新后仍需本人采用版本再独立确认。

最新验收与限制见ACCEPTANCE-ROUND10.md。没有安装SDK或新增账号授权。
