MindLink 本地实时 EEG 与专注度接口（2026-10-28）

Ubuntu：python3 app.py --port /dev/ttyUSB0
浏览器：http://127.0.0.1:8876
Windows：安装 Python 3.11 x64，双击 setup_windows.cmd，再双击 start_windows.cmd，输入列出的 COM 编号。
也可运行 .venv\Scripts\python.exe app.py --port COM3。
不要与其他串口调试软件同时打开该串口。无需重接板子针脚，电脑端改为对应 COM 口。
若 Windows 不出现 COM 口，检查设备管理器里的 CP210x USB-UART 驱动；只从 Silicon Labs 官方下载。
本包已在 Ubuntu 实机验证；尚未在 Windows 实机执行，C# 示例未编译验证。

波形与噪声
RAW单位ADC counts，保留最近10秒滚动显示。大噪声掩蔽，不清空整屏、不拼接或插值补信号。
abs(raw)>1500 或相邻差>600时标记，并掩蔽后续0.25秒；接触质量非0或未知也掩蔽。
“显示被遮蔽的原始值”可检查原始幅度。阈值是工程筛选，不能消除全部眼电/肌电。
坏包或RAW超时重置连续分析段，显示历史保留并插入断点。真实丢失的数据不能补回来。
时间是主机接收时间和512Hz名义采样率估计，设备无包序号；不是硬件精确时间戳。
包络：4阶1–45Hz因果带通，250ms后向RMS；每次恢复后预热0.5秒。
热图：最近120秒；每约1秒计算4秒窗，Welch 2秒Hann、50%重叠。
频带[1,4)、[4,8)、[8,13)、[13,30)、[30,45)Hz，dB re 1 count²，固定色标[-10,60]。
受硬件频响影响，delta仅供查看。接触质量0不保证没有眼电/肌电。

分数与小球
主界面仅显示“专注度”“放松度”；原始来源在接口和详情保留为 neurosky_esense。
eSense 1–100有效，0/坏接触/过期/噪声期间返回null，不把无效值当成0分。
公开数据冻结模型是闭眼休息/中等心算/困难心算；原测试平衡准确率59.48%，不是你当前设备准确率。
它没有被改名为专注或情绪模型。模型4秒窗、约2秒更新；噪声后等待完整干净窗口。
小球为分数反馈任务；坏信号暂停，不代表已经证明可以提升注意力。

独立应用调用
GET http://127.0.0.1:8876/api/v1/state
GET /api/v1/events 为SSE，每0.5秒一次，event: metrics。
GET /api/v1/schema 为状态JSON Schema；GET /api/v1/health 为服务状态。
接口详细说明见 API接口说明.txt；Python/C#/网页示例见 sdk。
http://127.0.0.1:8876/demo 演示专注度持续达标后展示内容。
服务仅监听本机；迁移Windows后URL和字段不变，修改串口即可。

记录与个人模型
默认不写盘，点击“开始记录”才保存 recordings/*.jsonl。停止后文件可训练/分析。
记录保留原始幅度、掩蔽标记、连续段ID、全局样本编号、质量和主动标签。
标签由人填写；fixation和thinking不自动当作focus，eSense不当作训练真值。
至少3个独立服务会话、建议不同日期，均采集focus/mind_wandering；保留最后一天作测试。
同一服务内反复停止/开始录制不算独立会话。标签切换后4秒不纳入训练。
python train_personal.py --recordings recordings --test-session 文件名不含扩展名 --output personal.joblib
每类训练/测试至少10个有效窗口只是运行门槛，不是样本量充分性保证。
生成个人模型后：python app.py --port COM3 --attention-model personal.joblib --attention-source personal
只加载你自己或可信来源的joblib文件。当前包没有伪造的个人训练结果；未训练时接口返回不可用。
个人模型分数是自报focus相对mind_wandering的未校准模型输出；不是专注度百分比或临床测量。
当前尚无情绪模型。情绪标注与文献方案见 research/单通道情绪解码核查.txt。

验证：python -m unittest discover -v；node test_feedback.js。
完整导出按钮仅为当前显示窗口，持续全量记录须显式开始记录。
