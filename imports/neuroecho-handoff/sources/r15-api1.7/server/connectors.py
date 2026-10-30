"""连接器目录、场景推荐、读取与洞察（演示数据）。

设计对齐 PRD 19/20：
- 从场景开始，而不是从"连接列表"开始；
- 推荐先给 3 个，其余收进"更多"；
- 读取前明确范围与用途；连接成功 ≠ 已经理解；
- 读取后先给洞察卡（事实/推测/问题 + 洞察），再进入对话。
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

SCENARIOS = [
    {
        "id": "work",
        "title": "工作与项目",
        "desc": "最近在做的项目、文档与协作",
        "recommend": ["feishu", "notion", "linear", "github"],
        "question": "你最近在推进哪件事？",
    },
    {
        "id": "daily",
        "title": "日常与关系",
        "desc": "日历、消息、承诺与家人朋友",
        "recommend": ["apple_reminders", "apple_calendar", "gmail", "apple_messages"],
        "question": "最近哪件小事让你有点挂心？",
    },
    {
        "id": "body",
        "title": "身体与状态",
        "desc": "睡眠、运动、心率与作息",
        "recommend": ["apple_health", "oura", "apple_watch"],
        "question": "最近身体或作息有什么变化？",
    },
    {
        "id": "create",
        "title": "创作与灵感",
        "desc": "笔记、收藏、音乐与灵感碎片",
        "recommend": ["apple_notes", "notion", "spotify"],
        "question": "最近在酝酿什么？",
    },
]

# 演示连接器目录（真实接入时替换为 OAuth/本地权限实现）
CONNECTORS = [
    {
        "id": "feishu", "name": "飞书", "category": "工作协作", "icon": "飞",
        "blurb": "文档、消息与日程", "reads": ["最近文档", "会议纪要", "日程"],
        "scopes": ["docx:readonly", "calendar:readonly"], "mode": "real-readonly",
        "items": [
            {"type": "doc", "title": "交互原型 v3", "meta": "2 小时前 · 你编辑", "summary": "卡在「如何让助手记住上下文又不过度打扰」"},
            {"type": "doc", "title": "团队周会纪要", "meta": "昨天 · 会议", "summary": "下周三要给团队演示最小闭环"},
            {"type": "event", "title": "下周三 15:00 团队演示", "meta": "日历 · 45 分钟", "summary": "需要准备三分钟演示"},
        ],
        "inferences": [
            "你可能需要在演示前先冻结一个最小闭环，而不是继续加功能。",
            "你在意「被理解」而不是「被安排」。",
        ],
        "questions": ["下周三演示，你最想证明的是理解力，还是完成度？"],
        "insights": [
            {"type": "pattern", "title": "同一件事出现了三次", "text": "原型、周会、日历都指向「记忆分寸」；这是当前真正的卡点。"},
            {"type": "risk", "title": "演示前功能膨胀", "text": "距离演示 5 天，新增功能会挤压排练时间。"},
            {"type": "opportunity", "title": "把卡点变成演示主线", "text": "用「可纠正的理解」作为三分钟主线，比堆功能更有记忆点。"},
        ],
    },
    {
        "id": "notion", "name": "Notion", "category": "工作协作", "icon": "N",
        "blurb": "项目页、会议记录与知识库", "reads": ["最近编辑的页面", "项目看板"],
        "scopes": ["read_content"], "mode": "demo",
        "items": [
            {"type": "page", "title": "Q4 路线图", "meta": "昨天 · 你编辑", "summary": "三个候选方向，尚未定优先级"},
            {"type": "page", "title": "用户访谈 07", "meta": "3 天前", "summary": "用户说「不想再教一个助手重新认识我」"},
        ],
        "inferences": ["你可能在「方向很多、优先级未定」的状态里。", "用户反复提到「不想重复解释自己」。"],
        "questions": ["这周你最想先砍掉哪一个方向？"],
        "insights": [
            {"type": "pattern", "title": "用户要的是连续性", "text": "访谈与路线图都指向「不要重新认识我」。"},
            {"type": "risk", "title": "三个方向同时推进", "text": "没有冻结优先级，容易都做一半。"},
            {"type": "opportunity", "title": "用一条访谈原话做北极星", "text": "「不想重复解释自己」可以成为产品一句话。"},
        ],
    },
    {
        "id": "linear", "name": "Linear", "category": "工作协作", "icon": "L",
        "blurb": "任务、迭代与阻塞", "reads": ["进行中 issue", "本周迭代"],
        "scopes": ["issues:read"], "mode": "demo",
        "items": [
            {"type": "issue", "title": "记忆删除联动", "meta": "进行中 · 高优", "summary": "删除来源后派生记忆未清理"},
            {"type": "issue", "title": "移动端 onboarding", "meta": "待排期", "summary": "缺少连接器推荐步骤"},
        ],
        "inferences": ["你手上的高优任务集中在「记忆与删除」。", "移动端 onboarding 被排后，可能影响首次体验。"],
        "questions": ["这周只清一个高优，你选哪个？"],
        "insights": [
            {"type": "pattern", "title": "高优都围绕信任", "text": "删除联动与记忆边界是同一条信任链。"},
            {"type": "risk", "title": "移动端首用被拖后", "text": "首次体验缺失会让 H5 只能演示、不能留存。"},
            {"type": "opportunity", "title": "把删除做成可见能力", "text": "现场演示「撤回来源」比讲十句隐私更有效。"},
        ],
    },
    {
        "id": "github", "name": "GitHub", "category": "工作协作", "icon": "G",
        "blurb": "仓库、PR 与 issue", "reads": ["最近提交", "待评审 PR"],
        "scopes": ["repo:read"], "mode": "demo",
        "items": [
            {"type": "pr", "title": "feat: onboarding 连接器推荐", "meta": "待评审", "summary": "新增 3 步引导与推荐排序"},
            {"type": "commit", "title": "fix: 记忆历史迁移", "meta": "今天", "summary": "为旧数据补 citations 字段"},
        ],
        "inferences": ["你正在把「理解」做成可演示的入口。", "迁移类改动说明已有真实数据需要兼容。"],
        "questions": ["这个 PR 你更担心体验还是数据迁移？"],
        "insights": [
            {"type": "pattern", "title": "从功能转向体验", "text": "近期提交都在打磨首次使用与可解释性。"},
            {"type": "risk", "title": "迁移未回放验证", "text": "旧库结构变化需要一次回放测试。"},
            {"type": "opportunity", "title": "把迁移脚本当演示素材", "text": "能证明「可带走、可恢复」。"},
        ],
    },
    {
        "id": "slack", "name": "Slack", "category": "工作协作", "icon": "S",
        "blurb": "频道、提及与决策", "reads": ["最近提及", "关键频道"],
        "scopes": ["channels:read"], "mode": "demo",
        "items": [
            {"type": "message", "title": "#product 讨论", "meta": "今天 · 12 条", "summary": "团队在争论先做连接器还是先做记忆"},
            {"type": "mention", "title": "@你：演示脚本", "meta": "昨天", "summary": "需要你确认三分钟脚本"},
        ],
        "inferences": ["团队对优先级有分歧，需要你拍板。", "演示脚本还缺你的确认。"],
        "questions": ["连接器与记忆，这周只能保一个，你选哪个？"],
        "insights": [
            {"type": "pattern", "title": "分歧集中在优先级", "text": "不是方向错，而是顺序未定。"},
            {"type": "risk", "title": "等待你确认的阻塞", "text": "脚本未定会影响彩排。"},
            {"type": "opportunity", "title": "用一句话统一团队", "text": "先把「可纠正的理解」讲成一句话。"},
        ],
    },
    {
        "id": "google_calendar", "name": "Google 日历", "category": "日常", "icon": "日",
        "blurb": "日程、会议与空闲", "reads": ["未来 7 天日程", "冲突时段"],
        "scopes": ["calendar:readonly"], "mode": "demo",
        "items": [
            {"type": "event", "title": "周三 15:00 团队演示", "meta": "45 分钟 · 已确认", "summary": "需要准备 demo"},
            {"type": "event", "title": "周四 10:00 1:1", "meta": "30 分钟", "summary": "与合伙人同步进度"},
        ],
        "inferences": ["你本周有一个明确的外部承诺（周三演示）。", "周四的 1:1 可能是决策窗口。"],
        "questions": ["周三演示前，你最需要谁给你反馈？"],
        "insights": [
            {"type": "pattern", "title": "承诺驱动节奏", "text": "本周的关键节点是周三演示。"},
            {"type": "risk", "title": "准备时间被切碎", "text": "日程碎片化，需要整块时间排练。"},
            {"type": "opportunity", "title": "把 1:1 变成预演", "text": "周四可以先小范围试讲。"},
        ],
    },
    {
        "id": "gmail", "name": "Gmail", "category": "日常", "icon": "M",
        "blurb": "邮件、承诺与跟进", "reads": ["最近未读", "待回复"],
        "scopes": ["gmail.readonly"], "mode": "demo",
        "items": [
            {"type": "email", "title": "投资人跟进", "meta": "未读 · 2 天前", "summary": "询问产品进展与数据"},
            {"type": "email", "title": "场地确认", "meta": "已回复", "summary": "比赛场地与设备清单"},
        ],
        "inferences": ["有一个未回复的对外承诺（投资人）。", "比赛准备事项在邮件里。"],
        "questions": ["投资人这封，你想先回一句还是先放一放？"],
        "insights": [
            {"type": "pattern", "title": "对外沟通在堆积", "text": "未读里有一封关键跟进。"},
            {"type": "risk", "title": "沉默被解读为回避", "text": "拖太久会增加解释成本。"},
            {"type": "opportunity", "title": "用一句话先接住", "text": "不必完整汇报，先给时间点。"},
        ],
    },
    {
        "id": "apple_messages", "name": "iMessage", "category": "日常", "icon": "i",
        "blurb": "家人朋友的消息与约定", "reads": ["最近对话", "未回复"],
        "scopes": ["messages:read"], "mode": "demo",
        "items": [
            {"type": "message", "title": "妈妈：周末回来吗", "meta": "昨天 · 未回复", "summary": "询问周末安排"},
            {"type": "message", "title": "朋友：演出票", "meta": "3 天前", "summary": "问要不要一起去看"},
        ],
        "inferences": ["有两个关系里的未回复。", "你最近可能把精力都放在项目上。"],
        "questions": ["周末这件事，你想怎么回？"],
        "insights": [
            {"type": "pattern", "title": "关系消息被延后", "text": "不是不重要，而是被项目挤后。"},
            {"type": "risk", "title": "沉默累积成误会", "text": "越晚回复越难开口。"},
            {"type": "opportunity", "title": "先回一句具体的", "text": "给出时间点比解释更有效。"},
        ],
    },
    {
        "id": "apple_reminders", "name": "提醒事项", "category": "日常", "icon": "✓",
        "blurb": "待办与承诺（只读）", "reads": ["未完成提醒"], "scopes": ["reminders:read"], "mode": "local-real",
        "items": [
            {"type": "reminder", "title": "给团队发演示脚本", "meta": "工作 · 今天", "summary": "周三演示前要确认"},
            {"type": "reminder", "title": "预约牙医", "meta": "个人 · 本周", "summary": "拖了两周"},
        ],
        "inferences": ["你有两条未完成提醒，一条工作一条个人。", "工作和个人承诺在同一个清单里，容易互相挤压。"],
        "questions": ["今天只能完成一条，你选哪个？"],
        "insights": [
            {"type": "pattern", "title": "两条承诺悬着", "text": "工作和个人各一条，都拖了几天。"},
            {"type": "risk", "title": "靠记忆硬扛", "text": "未完成项越多，越容易在演示前分心。"},
            {"type": "opportunity", "title": "先清一条", "text": "把「给团队发演示脚本」变成 10 分钟动作。"},
        ],
    },
    {
        "id": "apple_calendar", "name": "Apple 日历", "category": "日常", "icon": "日",
        "blurb": "未来 7 天日程（只读）", "reads": ["未来 7 天日程"], "scopes": ["calendar:readonly"], "mode": "local-real",
        "items": [
            {"type": "event", "title": "周三 15:00 团队演示", "meta": "45 分钟 · 已确认", "summary": "需要准备 demo"},
            {"type": "event", "title": "周四 10:00 1:1", "meta": "30 分钟", "summary": "与合伙人同步"},
        ],
        "inferences": ["你本周有一个明确的外部承诺（周三演示）。", "周四 1:1 是演示前的反馈窗口。"],
        "questions": ["演示前最需要谁给你反馈？"],
        "insights": [
            {"type": "pattern", "title": "承诺驱动节奏", "text": "本周关键节点是周三演示。"},
            {"type": "risk", "title": "准备时间碎片化", "text": "需要整块时间排练。"},
            {"type": "opportunity", "title": "把 1:1 变成预演", "text": "周四先小范围试讲。"},
        ],
    },
    {
        "id": "apple_health", "name": "健康", "category": "身体", "icon": "H",
        "blurb": "睡眠、步数与心率", "reads": ["近 7 天睡眠", "活动量"],
        "scopes": ["health:read"], "mode": "demo",
        "items": [
            {"type": "health", "title": "睡眠 5h42m", "meta": "昨夜 · 偏短", "summary": "连续 3 天低于 6 小时"},
            {"type": "health", "title": "步数 3,120", "meta": "昨天 · 偏低", "summary": "久坐时间增加"},
        ],
        "inferences": ["你最近可能处于高投入、低恢复的状态。", "睡眠不足会影响演示前的判断力。"],
        "questions": ["这周你愿意为睡眠让出哪一块时间？"],
        "insights": [
            {"type": "pattern", "title": "恢复不足", "text": "连续三天睡眠偏短，活动量下降。"},
            {"type": "risk", "title": "演示前透支", "text": "高压力 + 低睡眠容易在台上卡壳。"},
            {"type": "opportunity", "title": "把休息写进排练", "text": "每轮彩排后强制 10 分钟离屏。"},
        ],
    },
    {
        "id": "oura", "name": "Oura", "category": "身体", "icon": "O",
        "blurb": "睡眠质量与恢复度", "reads": ["睡眠评分", "恢复指数"],
        "scopes": ["daily:read"], "mode": "demo",
        "items": [
            {"type": "health", "title": "恢复度 62", "meta": "今天 · 一般", "summary": "深睡比例偏低"},
        ],
        "inferences": ["今天不适合做高强度决策。", "可以先把演示脚本顺一遍，不写新代码。"],
        "questions": ["今天要不要把最难的决策挪到明天？"],
        "insights": [
            {"type": "pattern", "title": "状态一般", "text": "恢复度偏低，适合低负荷任务。"},
            {"type": "risk", "title": "硬做决策", "text": "疲劳时容易反复。"},
            {"type": "opportunity", "title": "安排轻任务", "text": "今天只做彩排与整理。"},
        ],
    },
    {
        "id": "apple_watch", "name": "Apple Watch", "category": "身体", "icon": "W",
        "blurb": "心率、运动与站立", "reads": ["今日活动", "静息心率"],
        "scopes": ["health:read"], "mode": "demo",
        "items": [
            {"type": "health", "title": "静息心率 72", "meta": "今天 · 略高", "summary": "比上周高 6"},
        ],
        "inferences": ["可能有压力或睡眠不足。", "今天适合把节奏放慢。"],
        "questions": ["今天最想先完成哪一件小事？"],
        "insights": [
            {"type": "pattern", "title": "压力信号", "text": "静息心率略高。"},
            {"type": "risk", "title": "连续高压", "text": "需要主动安排恢复。"},
            {"type": "opportunity", "title": "散步十分钟", "text": "比硬撑更有效。"},
        ],
    },
    {
        "id": "apple_notes", "name": "备忘录", "category": "创作", "icon": "笔",
        "blurb": "随手记与灵感碎片", "reads": ["最近笔记", "未整理片段"],
        "scopes": ["notes:read"], "mode": "demo",
        "items": [
            {"type": "note", "title": "演示开场白草稿", "meta": "今天", "summary": "「先理解你，再决定怎样陪你」"},
            {"type": "note", "title": "没想完的句子", "meta": "昨天", "summary": "陪伴不是替你决定，而是…"},
        ],
        "inferences": ["你已经有一句不错的开场白。", "你在找「陪伴」的下半句。"],
        "questions": ["下半句你想落在「更清楚」还是「更安心」？"],
        "insights": [
            {"type": "pattern", "title": "一句话已成型", "text": "开场白可以成为全场主线。"},
            {"type": "risk", "title": "金句太多", "text": "三分钟只能留一句。"},
            {"type": "opportunity", "title": "用一句收尾", "text": "「只让你更清楚地做决定」。"},
        ],
    },
    {
        "id": "spotify", "name": "Spotify", "category": "创作", "icon": "♪",
        "blurb": "最近播放与歌单", "reads": ["最近播放", "收藏"],
        "scopes": ["user-read-recently-played"], "mode": "demo",
        "items": [
            {"type": "music", "title": "最近常听：环境钢琴", "meta": "深夜", "summary": "集中写东西时会放"},
        ],
        "inferences": ["你习惯用音乐切换状态。", "深夜是你的深度工作时间。"],
        "questions": ["演示当天你想用什么状态上场？"],
        "insights": [
            {"type": "pattern", "title": "深夜深度工作", "text": "音乐与产出高度相关。"},
            {"type": "risk", "title": "演示在白天", "text": "需要提前调整节奏。"},
            {"type": "opportunity", "title": "设计一个上场仪式", "text": "用同一首歌切换状态。"},
        ],
    },
    {
        "id": "local_files", "name": "本地文件", "category": "本地", "icon": "⌂",
        "blurb": "桌面与文稿（只读）", "reads": ["最近修改的文档"],
        "scopes": ["fileRoots:documents,desktop"], "mode": "local",
        "items": [
            {"type": "file", "title": "PRD-0.4.md", "meta": "文稿 · 今天", "summary": "产品需求全文"},
            {"type": "file", "title": "demo-notes.md", "meta": "桌面 · 昨天", "summary": "演示脚本草稿"},
        ],
        "inferences": ["资料都在本地，适合做只读上下文。", "演示脚本已有草稿。"],
        "questions": ["要不要把演示脚本也纳入理解？"],
        "insights": [
            {"type": "pattern", "title": "资料在本地", "text": "不一定要上云才能被理解。"},
            {"type": "risk", "title": "路径越权", "text": "只读白名单与明确选择是边界。"},
            {"type": "opportunity", "title": "本地优先叙事", "text": "隐私可以是产品卖点。"},
        ],
    },
    {
        "id": "screen", "name": "屏幕上下文", "category": "本地", "icon": "▣",
        "blurb": "当前窗口与屏幕（只读）", "reads": ["当前前台窗口"],
        "scopes": ["screen:read"], "mode": "demo",
        "items": [
            {"type": "screen", "title": "正在看：产品原型", "meta": "屏幕 · 刚刚", "summary": "浏览器中的交互原型"},
        ],
        "inferences": ["你正在做视觉与交互的比对。", "屏幕上下文可以帮助「刚才停在这一页」。"],
        "questions": ["要不要记住这一页，下次继续？"],
        "insights": [
            {"type": "pattern", "title": "上下文就在屏幕上", "text": "比问用户更自然。"},
            {"type": "risk", "title": "隐私边界", "text": "必须显式授权与可停止。"},
            {"type": "opportunity", "title": "续接体验", "text": "下次打开直接回到这一页。"},
        ],
    },
    {
        "id": "clipboard", "name": "剪贴板", "category": "本地", "icon": "▤",
        "blurb": "最近复制的内容（只读）", "reads": ["最近一次复制"],
        "scopes": ["clipboard:read"], "mode": "demo",
        "items": [
            {"type": "clipboard", "title": "复制了一段用户原话", "meta": "2 分钟前", "summary": "「不想再教一个助手重新认识我」"},
        ],
        "inferences": ["这句话可能是你的北极星。", "你正在收集用户语言。"],
        "questions": ["要把这句放进产品一句话吗？"],
        "insights": [
            {"type": "pattern", "title": "用户原话", "text": "比内部术语更有力量。"},
            {"type": "risk", "title": "断章取义", "text": "需要确认上下文。"},
            {"type": "opportunity", "title": "直接引用", "text": "开场就用用户原话。"},
        ],
    },
]

BY_ID = {c["id"]: c for c in CONNECTORS}


def catalog() -> dict:
    return {
        "scenarios": SCENARIOS,
        "connectors": [
            {k: c[k] for k in ("id", "name", "category", "icon", "blurb", "reads", "mode")}
            for c in CONNECTORS
        ],
    }


def recommend(scenario_id: str) -> list[dict]:
    scenario = next((s for s in SCENARIOS if s["id"] == scenario_id), None)
    if not scenario:
        return []
    out = []
    for cid in scenario["recommend"]:
        c = BY_ID.get(cid)
        if not c:
            continue
        out.append({
            "connector": {k: c[k] for k in ("id", "name", "category", "icon", "blurb", "reads", "mode")},
            "reason": f"你在意「{scenario['title']}」——它能提供：{'、'.join(c['reads'][:2])}",
            "recommended": True,
        })
    return out


STARTERS = {
    "feishu": ["这周先做什么？", "为什么你这么判断？", "把洞察变成下一步"],
    "notion": ["三个方向先砍哪个？", "为什么这么判断？", "帮我排出本周优先级"],
    "linear": ["这周只清一个高优，选哪个？", "为什么？", "变成下一步"],
    "github": ["这个 PR 先看体验还是迁移？", "依据是什么？", "变成下一步"],
    "slack": ["团队分歧怎么收？", "为什么？", "帮我起草一句话"],
    "google_calendar": ["演示前最需要谁反馈？", "这周怎么排？", "变成下一步"],
    "gmail": ["那封未读先怎么回？", "为什么？", "草拟一句"],
    "apple_messages": ["周末怎么回？", "为什么？", "帮我起草"],
    "apple_health": ["这周为睡眠让出什么？", "依据是什么？", "变成下一步"],
    "oura": ["今天适合做什么？", "为什么？", "变成下一步"],
    "apple_watch": ["今天先完成哪件小事？", "依据是什么？", "变成下一步"],
    "apple_notes": ["开场白留哪一句？", "为什么？", "变成下一步"],
    "spotify": ["演示当天用什么状态上场？", "为什么？", "变成下一步"],
    "local_files": ["先读哪份资料？", "为什么？", "变成下一步"],
    "screen": ["记住这一页吗？", "为什么？", "变成下一步"],
    "clipboard": ["这句能当北极星吗？", "为什么？", "变成下一步"],
}


def starters(connector_id: str) -> list[str]:
    return STARTERS.get(connector_id, ["先聊哪一件？", "为什么？", "变成下一步"])


def read(connector_id: str) -> dict:
    c = BY_ID.get(connector_id)
    if not c:
        return {"ok": False, "error": "未知连接器"}
    facts = [f"{i['title']}：{i['summary']}" for i in c["items"][:3]]
    return {
        "ok": True,
        "connector": {k: c[k] for k in ("id", "name", "category", "icon", "blurb", "reads", "scopes", "mode")},
        "items": c["items"],
        "understanding": {
            "facts": facts,
            "inferences": c["inferences"],
            "questions": c["questions"],
        },
        "insights": c["insights"],
        "starters": starters(connector_id),
        "synthetic": True,
        "read_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def greeting(connector_id: str) -> str:
    c = BY_ID.get(connector_id)
    if not c:
        return "我在。想从哪儿说起？"
    return f"我看过你的{c['name']}（演示读取）。有件事想先和你确认：{c['insights'][0]['title']}。"
