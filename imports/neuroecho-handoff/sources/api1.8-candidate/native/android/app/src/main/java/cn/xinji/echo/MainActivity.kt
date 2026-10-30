package cn.xinji.echo

import android.animation.ValueAnimator
import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.os.Bundle
import android.provider.OpenableColumns
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import cn.xinji.echo.shared.EchoSharedReference as Shared
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.time.LocalDate
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState); setContent { val model: EchoViewModel = viewModel(); EchoApp(model) } }
}
private fun sharedColor(value: String): Color {
    if (value.startsWith("#")) return Color(android.graphics.Color.parseColor(value))
    val parts = value.substringAfter('(').substringBefore(')').split(',').map { it.trim().toFloat() }
    return Color(parts[0] / 255f, parts[1] / 255f, parts[2] / 255f, parts[3])
}
private val Ink = sharedColor(Shared.COLOR_INK)
private val Muted = sharedColor(Shared.COLOR_INK_MUTE)
private val Blue = sharedColor(Shared.COLOR_CHIP_BLUE)
private val UserBubble = sharedColor(Shared.COLOR_USER_BUBBLE)

@Composable private fun EchoTheme(content: @Composable () -> Unit) {
    // An opaque Material 3 fallback is intentional; this is not a simulated blur.
    MaterialTheme(colorScheme = lightColorScheme(primary = Ink, onPrimary = Color.White, secondary = Muted, surface = Color.White, background = sharedColor(Shared.COLOR_BG_START), onSurface = Ink, error = sharedColor(Shared.COLOR_DANGER)),
        typography = Typography(bodyLarge = androidx.compose.ui.text.TextStyle(fontSize = Shared.DIMENSION_BODY_FONT.sp, lineHeight = 24.sp), bodyMedium = androidx.compose.ui.text.TextStyle(fontSize = Shared.DIMENSION_BODY_FONT.sp, lineHeight = 24.sp), titleLarge = androidx.compose.ui.text.TextStyle(fontSize = 24.sp, lineHeight = 32.sp, fontWeight = FontWeight.Medium)), content = content)
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable private fun EchoApp(model: EchoViewModel) = EchoTheme {
    val state = model.state
    var page by rememberSaveableInt(0)
    var subpage by remember { mutableIntStateOf(0) }
    var settings by remember { mutableStateOf(false) }
    var search by remember { mutableStateOf(false) }
    var memory by remember { mutableStateOf<Memory?>(null) }
    var forgetting by remember { mutableStateOf<Memory?>(null) }
    var removing by remember { mutableStateOf<Source?>(null) }
    var sourcePlan by remember { mutableStateOf<JSONObject?>(null) }
    var sourceUrl by remember { mutableStateOf("") }
    var fileSelectionContext by remember { mutableStateOf("") }
    var fileSelectionActive by remember { mutableStateOf(false) }
    LaunchedEffect(model.dataContextId) {
        memory = null; forgetting = null; removing = null; sourcePlan = null; sourceUrl = ""; search = false
    }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    var resumed by remember { mutableStateOf(lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) }
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, _ -> resumed = lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
    var readAloudState by remember { mutableStateOf(ReadAloudState()) }
    val readAloud = remember(model, context.applicationContext) {
        ReadAloudController(AndroidReadAloudDriver(context.applicationContext), context = {
            val current = model.state
            val visible = if (page == 1) current.conversation?.messages.orEmpty().filter { TopicPolicy.matches(current.topics, it.id, current.selectedTopic) }.map { it.id }.toSet() else emptySet()
            ReadAloudContext(model.baseUrl, current.conversation, visible, resumed && page == 1)
        }, timer = AndroidReadAloudTimer(), changed = { readAloudState = it })
    }
    SideEffect { readAloud.refresh() }
    DisposableEffect(lifecycle, readAloud) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_PAUSE || event == Lifecycle.Event.ON_STOP) readAloud.stop() }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer); readAloud.close() }
    }
    SideEffect { model.updatePresentationBlocked(settings || search || memory != null || forgetting != null || removing != null || sourcePlan != null || fileSelectionActive) }
    DisposableEffect(lifecycle, model) {
        val observer = LifecycleEventObserver { _, _ -> model.foregroundUpdates(lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) }
        lifecycle.addObserver(observer)
        model.foregroundUpdates(lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))
        onDispose { lifecycle.removeObserver(observer); model.foregroundUpdates(false) }
    }
    LaunchedEffect(resumed, model.dataContextId, state.changesAvailable) {
        while (resumed && state.changesAvailable) { model.pollUpdates(); kotlinx.coroutines.delay(1_000) }
    }
    val deliveryPending = state.conversation?.messages?.any { it.deliveryPending } == true
    LaunchedEffect(resumed, model.baseUrl, state.conversation?.id, deliveryPending) {
        while (resumed && model.state.conversation?.messages?.any { it.deliveryPending } == true) {
            val delayMs = model.state.conversation?.messages?.filter { it.deliveryPending }?.minOfOrNull { it.deliveryNextMs } ?: 800L
            kotlinx.coroutines.delay(delayMs.coerceIn(100L, 2000L))
            model.refreshDelivery()
        }
    }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        val selectedFor = fileSelectionContext
        fileSelectionActive = false
        if (uris.isNotEmpty()) scope.launch {
            if (selectedFor != model.dataContextId) { model.tell("连接身份已变化，没有读取之前选择的文件。请在当前连接重新选择。"); return@launch }
            runCatching {
                require(uris.size <= 3) { "一次最多选择 3 份文本。" }
                withContext(Dispatchers.IO) { uris.map { uri ->
                    val name = context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor -> if (cursor.moveToFirst()) cursor.getString(0) else null } ?: "未命名.txt"
                    val bytes = context.contentResolver.openInputStream(uri)?.use { input ->
                        val output = ByteArrayOutputStream(); val buffer = ByteArray(8192)
                        while (output.size() <= FilePreviewPolicy.MAX_BYTES) { val count = input.read(buffer); if (count < 0) break; output.write(buffer, 0, count) }
                        output.toByteArray()
                    } ?: error("未能读取你选择的文件。")
                    FilePreviewPolicy.preview(name, bytes)
                } }
            }.onSuccess { files -> if (selectedFor == model.dataContextId) model.selectedFiles(files) else model.tell("连接身份已变化，未导入之前选择的文件。") }.onFailure { model.tell(it.message ?: "文件不可读取，请重新选择。") }
        }
    }
    fun showSources() { page = 0; subpage = 2; model.sources() }
    Scaffold(containerColor = Color.Transparent, topBar = {
        // Wrap-content top bar remains readable at 200% system font size.
        Surface(color = sharedColor(Shared.COLOR_BG_START)) {
            Row(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Orb(36, model.comfort, presenceLabel(state.pending, state.busy, state.draft, state.chatSending))
                Column(Modifier.weight(1f)) { Text(Shared.COPY_APP_NAME, style = MaterialTheme.typography.titleLarge); Text(presenceLabel(state.pending, state.busy, state.draft, state.chatSending), fontSize = 12.sp, color = Muted) }
                TextButton(onClick = { readAloud.stop(); search = true }, modifier = Modifier.heightIn(min = Shared.DIMENSION_TOUCH_ANDROID.dp)) { Text("搜索") }
                TextButton(onClick = { readAloud.stop(); settings = true }, modifier = Modifier.heightIn(min = Shared.DIMENSION_TOUCH_ANDROID.dp)) { Text(Shared.COPY_NAV_SETTINGS) }
            }
        }
    }, bottomBar = {
        NavigationBar(containerColor = Color.White.copy(alpha = if (model.comfort.reduceTransparency) 1f else .94f), modifier = Modifier.navigationBarsPadding()) {
            listOf(Shared.COPY_NAV_TODAY to "◉", Shared.COPY_NAV_CHAT to "◌", Shared.COPY_NAV_MEMORY to "◇").forEachIndexed { index, (title, symbol) ->
                NavigationBarItem(selected = page == index, onClick = { readAloud.stop(); page = index }, icon = { Text(symbol, fontSize = 24.sp) }, label = { Text(title) }, colors = NavigationBarItemDefaults.colors(indicatorColor = Blue))
            }
        }
    }) { insets ->
        Column(Modifier.fillMaxSize().background(Brush.linearGradient(listOf(sharedColor(Shared.COLOR_BG_START), sharedColor(Shared.COLOR_BG_MID), sharedColor(Shared.COLOR_BG_END)))).padding(insets)) {
            if (state.notice.isNotBlank()) Surface(color = Color.White, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp), shape = RoundedCornerShape(16.dp)) {
                Column(Modifier.padding(12.dp)) { Text(state.notice, fontSize = 14.sp, color = Ink); TextButton(onClick = { model.tell("") }, modifier = Modifier.heightIn(min = Shared.DIMENSION_TOUCH_ANDROID.dp)) { Text("收起说明") } }
            }
            if (state.conversation != null) Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                val updateText = when (state.updateStatus) {
                    UpdateStatus.PENDING -> Shared.COPY_CONNECTION_SYNC_PENDING
                    UpdateStatus.UPDATED -> Shared.COPY_CONNECTION_SYNC_UPDATED
                    UpdateStatus.OFFLINE -> Shared.COPY_CONNECTION_SYNC_OFFLINE
                    UpdateStatus.UNSUPPORTED -> Shared.COPY_CONNECTION_SYNC_UNSUPPORTED
                    UpdateStatus.IDENTITY_CHANGED -> "服务身份有变化，已保留草稿；请到设置核对原连接。"
                    UpdateStatus.CHECKING -> "正在检查更新…"
                    else -> if (!state.changesAvailable) Shared.COPY_CONNECTION_SYNC_UNSUPPORTED else ""
                }
                if (updateText.isNotBlank()) Text(updateText, Modifier.weight(1f), fontSize = 12.sp, color = Muted)
                else Spacer(Modifier.weight(1f))
                TextButton(onClick = model::checkUpdates, enabled = !state.busy && state.updateStatus != UpdateStatus.CHECKING,
                    modifier = Modifier.heightIn(min = Shared.DIMENSION_TOUCH_ANDROID.dp)) { Text(Shared.COPY_CONNECTION_SYNC_CHECK) }
            }
            if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth(), color = Ink)
            if (state.conversation == null) Column(Modifier.padding(20.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Orb(88, model.comfort); Text("先连上你自己的回响。", style = MaterialTheme.typography.titleLarge)
                Text("在电脑的设备连接中，为这部手机生成一次显示的令牌；再填入 HTTPS 地址和令牌，接回同一段对话。服务的网络入口默认关闭，需要先由电脑端明确配置。")
                Primary("重新连接", !state.busy, model::refresh); Secondary("配置后端地址") { settings = true }
            } else when (page) {
                0 -> Column {
                    PrimaryTabRow(selectedTabIndex = subpage, containerColor = Color.Transparent) { listOf("今天", "任务", "连接").forEachIndexed { index, text -> Tab(selected = subpage == index, onClick = { subpage = index; if (index == 2) model.sources() }, text = { Text(text) }, modifier = Modifier.heightIn(min = Shared.DIMENSION_TOUCH_ANDROID.dp)) } }
                    when (subpage) {
                        0 -> Today(model, toChat = { text -> model.bringToChat(text); page = 1 }, toTasks = { subpage = 1 }, toMemories = { page = 2 }, toSources = ::showSources)
                        1 -> Tasks(model)
                        else -> Sources(model, chooseFiles = { run { if (!fileSelectionActive) { fileSelectionContext = model.dataContextId; fileSelectionActive = true; picker.launch(arrayOf("text/*", "application/json", "application/javascript")) } else model.tell("请先完成或取消上一次文件选择。") } }, onPlan = { sourcePlan = it; sourceUrl = "" }, onRemove = { removing = it })
                    }
                }
                1 -> Chat(model, readAloud, readAloudState)
                else -> Memories(model, onOpen = { memory = it }, onForget = { forgetting = it })
            }
        }
    }
    if (settings) SettingsSheet(model, beforeEndpointChange = readAloud::stop) { settings = false }
    if (search) SearchSheet(model, onClose = { search = false }) { hit ->
        search = false
        if (hit.kind == SearchKind.MESSAGE) { model.focusMessage(hit.id); page = 1 }
        else { state.conversation?.memories?.find { it.id == hit.id }?.let { memory = it }; page = 2 }
    }
    if (state.memoryEditorOpen && state.memoryDraft != null) MemoryEditorSheet(model)
    if (state.moodEditorOpen) MoodEditor(model) { text -> model.bringToChat(text); model.closeMoods(); page = 1 }
    if (state.followupEditorOpen && state.followupDraft != null) FollowupEditorSheet(model)

    memory?.let { item -> MemorySheet(item, model, onClose = { memory = null }, onForget = { memory = null; forgetting = item }) }
    forgetting?.let { item -> ConfirmSheet("忘掉这条？", "这条记忆及相关派生内容会停止用于回复；关联来源也可能暂停，需要重新核对。与它无关的独立资料、你的原话和已保存的动作保留。", onCancel = { forgetting = null }) { model.forget(item); forgetting = null } }
    removing?.let { source -> ConfirmSheet("移除这份资料？", "停止使用「${source.title}」及其派生记忆。其他来源、手动记忆和原话会保留；第三方账号授权不会因此撤销。", onCancel = { removing = null }) { model.revoke(source); removing = null } }
    sourcePlan?.let { descriptor ->
        val id = descriptor.str("id")
        val status = descriptor.str("status")
        Sheet(Shared.COPY_PLAN_TITLE, onClose = { sourcePlan = null }) {
            Text(descriptor.str("name"), fontWeight = FontWeight.SemiBold)
            Text("1. 只读取你明确选择的资料；不遍历账号或目录。\n2. 先展示片段，由你确认接入同一条对话。\n3. 后续聊天可能把标题、摘要和按问题检索的必要片段发给已配置的模型服务。")
            Text(descriptor.str("hint"), color = Muted)
            descriptor.optJSONArray("reads")?.let { values -> Text("本次范围：" + (0 until values.length()).joinToString("、") { values.optString(it) }) }
            if (id == "feishu") {
                Text("飞书由当前后端的已授权身份读取。Android 不会自动新建授权，也不会共享你的手机登录态。")
                OutlinedTextField(sourceUrl, { sourceUrl = it }, label = { Text("选定的单篇文档链接") }, modifier = Modifier.fillMaxWidth())
                Text("请求读取整篇，提取后最多保留 12000 字；预览仅展示开头。聊天时每来源最多 3 段，全部最多 8 段、3200 字；无匹配时不发送检索片段，但摘要等上下文仍可能发送。", fontSize = 13.sp)
            }
            if (id == "notion") {
                OutlinedTextField(sourceUrl, { sourceUrl = it }, label = { Text("选定的单个 Notion 页面链接") }, modifier = Modifier.fillMaxWidth())
                Text("仅复用后端已有的官方 ntn CLI 登录，只读此页前 50 个顶层文本块。未登录会报错；不会发起登录或申请 Token。", fontSize = 13.sp)
            }
            if (id == "git") {
                OutlinedTextField(sourceUrl, { sourceUrl = it }, label = { Text("后端 Mac 上代码库的完整目录") }, modifier = Modifier.fillMaxWidth())
                Text("只读取指定仓库最近最多 8 条提交，不读工作区文件、不修改仓库；这里填写目录，不是终端命令。", fontSize = 13.sp)
            }
            if (id == "github") Text("仅使用后端 gh CLI 已有登录读取最近 PR；不会发起新登录或扩大授权。", fontSize = 13.sp)
            if (id in setOf("apple_calendar", "apple_reminders")) Text("读取的是后端 Mac 的日历或提醒，不是这部 Android 手机。权限未核验时此端不触发系统授权。", fontSize = 13.sp)
            val permitted = id == "local_files" || SourcePolicy.mayPreview(id, status, sourceUrl)
            if (!permitted) Text(if (id !in SourcePolicy.supported) "此端尚未开放这个来源；没有读取。" else "请先补齐上述目标或在后端电脑核对已有条件；不会启动新授权。", color = Muted)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Secondary("不用") { sourcePlan = null }
                if (id == "local_files") Primary("选择文本文件") { sourcePlan = null; run { if (!fileSelectionActive) { fileSelectionContext = model.dataContextId; fileSelectionActive = true; picker.launch(arrayOf("text/*", "application/json")) } else model.tell("请先完成或取消上一次文件选择。") } }
                else Primary("好，读取预览", permitted && !state.busy) { model.previewSource(id, sourceUrl); sourcePlan = null }
            }
            Text("为什么先问你：连接范围由你决定。开始后可在连接页移除来源。", fontSize = 13.sp, color = Muted)
        }
    }
    if (state.files.isNotEmpty()) Sheet("先核对你选的文本", model::dismissFiles) {
        Text("只保留下方已预览的内容，每份最多前 4000 个字符。确认前不会上传给后端；确认后在后端保存，聊天可能向模型发送必要片段。")
        state.files.forEach { file -> Text(file.name + if (file.truncated) " · 仅前 4000 字符" else " · 完整内容", fontWeight = FontWeight.SemiBold); SelectionContainer { Text(file.text) } }
        Primary("确认接入当前对话", !state.busy && !state.filesUncertain, model::attachFiles)
        if (state.filesUncertain) Secondary("刷新已接入资料", !state.busy, model::refresh)
    }
    state.sourcePreview?.let { preview -> Sheet("核对这次读取", model::dismissSource) {
        val review = sourceReview(preview.result, preview.sourceId)
        review.sections.forEach { section -> Text(section.title, fontWeight = FontWeight.SemiBold); if (section.body.isNotBlank()) SelectionContainer { Text(section.body) } }
        listOf(review.facts to "资料事实", review.inferences to "推测 · 待确认", review.questions to "想问你").forEach { (values, label) -> if (values.isNotEmpty()) { Text(label, fontWeight = FontWeight.SemiBold); values.forEach { Text(it) } } }
        review.scope?.let { Text(it, fontSize = 13.sp, color = Muted) }
        review.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (!review.canAttach) Text("没有可核对的资料内容，不能确认接入。请关闭后重新读取预览。", color = MaterialTheme.colorScheme.error)
        Text("确认后保存在同一条对话；不会创建另一条聊天。若已启用模型，摘要和提取内容可能用于生成理解。")
        Primary("确认接入当前对话", !state.busy && !preview.uncertain && review.canAttach, model::attachSource)
        if (preview.uncertain) Secondary("刷新已接入资料", !state.busy, model::refresh)
    } }
    state.editor?.let { editor -> ActionSheet(editor, model) }
}

@Composable private fun rememberSaveableInt(initial: Int): MutableIntState = androidx.compose.runtime.saveable.rememberSaveable { mutableIntStateOf(initial) }

@Composable private fun SearchSheet(model: EchoViewModel, onClose: () -> Unit, onPick: (SearchHit) -> Unit) {
    var query by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf("") }
    val hits = searchConversation(model.state.conversation, query)
    Sheet("搜索对话与记忆", onClose) {
        OutlinedTextField(query, { query = it }, label = { Text("搜一句说过或记下的话") }, modifier = Modifier.fillMaxWidth())
        Text("只搜索本机已加载的对话与记忆，不读取外部账号，不上传搜索词。", fontSize = 13.sp, color = Muted)
        if (query.isNotBlank() && hits.isEmpty()) Text("没有找到匹配的记录。")
        hits.forEach { hit ->
            Surface(onClick = { onPick(hit) }, color = Color.White, shape = RoundedCornerShape(20.dp), border = BorderStroke(1.dp, Blue), modifier = Modifier.fillMaxWidth().heightIn(min = Shared.DIMENSION_TOUCH_ANDROID.dp)) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) { Text(hit.label, color = Muted, fontSize = 12.sp); Text(hit.text, fontSize = Shared.DIMENSION_BODY_FONT.sp) }
            }
        }
    }
}

@Composable private fun TopicSheet(message: Message, model: EchoViewModel, onClose: () -> Unit) {
    var label by remember(message.id) { mutableStateOf(TopicPolicy.label(model.state.topics, message.id)) }
    Sheet("标记话题", onClose) {
        Text("仅改变本设备的查看方式，不建立新对话，不变成个人记忆。", fontSize = 13.sp, color = Muted)
        SelectionContainer { Text(message.text) }
        OutlinedTextField(label, { label = it }, label = { Text("话题 · 1–20 字") }, modifier = Modifier.fillMaxWidth())
        Primary("保存这个标记", label.isNotBlank() && label != "全部" && label.codePointCount(0, label.length) <= 20) { model.tagMessage(message.id, label); onClose() }
    }
}

@Composable private fun MemoryEditorSheet(model: EchoViewModel) {
    val draft = model.state.memoryDraft ?: return
    var discard by remember { mutableStateOf(false) }
    Sheet(if (draft.id == null) "记一件事，由你确认" else "改一改这条", model::closeMemoryEditor) {
        Text(if (draft.id == null) "先保存为候选；你核对后点「是的」，才作为确认记忆。不记也可以。" else "只修改这条记忆；会核对你开始编辑时的版本，避免覆盖别处的改动。", fontSize = 13.sp, color = Muted)
        OutlinedTextField(draft.text, model::editMemoryDraft, label = { Text("想留下或纠正的文字") }, modifier = Modifier.fillMaxWidth(), minLines = 3, readOnly = model.state.busy)
        if (draft.conflict) {
            Text("这条记忆已有更新。你的草稿保留，尚未覆盖。", color = Ink, fontWeight = FontWeight.SemiBold)
            Text(draft.serverText?.let { "最新 v${draft.serverVersion}：$it" } ?: "服务端已经没有这条记忆。你可以复制草稿后关闭，或核对列表。")
            if (draft.serverVersion != null) Secondary("已比较，保留草稿并采用最新版本作核对", !model.state.busy, model::rebaseMemoryDraft)
        }
        if (draft.uncertain) Text("上次保存结果尚未确认，不能再次保存。文字保留；先关闭并刷新记忆列表核对。", color = Muted)
        Primary(if (draft.id == null) "加入待确认记忆" else "核对版本并保存纠正", !model.state.busy && !draft.conflict && !draft.uncertain && draft.text.isNotBlank(), model::saveMemoryDraft)
        Secondary("保留草稿，稍后再说", !model.state.busy, model::closeMemoryEditor)
        TextButton(onClick = { discard = true }, enabled = !model.state.busy, modifier = Modifier.heightIn(min = Shared.DIMENSION_TOUCH_ANDROID.dp)) { Text("丢弃本机草稿", color = MaterialTheme.colorScheme.error) }
        Text("草稿只存这台设备，不会自动保存到服务端。", fontSize = 12.sp, color = Muted)
    }
    if (discard) ConfirmSheet("丢弃本机草稿？", "只移除这台设备未保存的修改；服务端已有记忆不会删除。", onCancel = { discard = false }) { model.discardMemoryDraft(); discard = false }
}

private fun displayFollowupTime(value: String, zone: String = ZoneId.systemDefault().id): String = followupTimeLabel(value, zone)

@OptIn(ExperimentalLayoutApi::class)
@Composable private fun FollowupEditorSheet(model: EchoViewModel) {
    val draft = model.state.followupDraft ?: return
    val context = LocalContext.current
    val locked = draft.requestId.isNotEmpty()
    Sheet("留一条跟进", model::closeFollowup) {
        Text("只在打开回响时查看；关闭期间不通知。它不会发送消息，也不会设置手机系统提醒。", fontSize = 13.sp, color = Muted)
        OutlinedTextField(draft.content, { model.editFollowup(content = it) }, label = { Text("想跟进什么 · 最多1000字") }, modifier = Modifier.fillMaxWidth(), minLines = 3, readOnly = locked || model.state.busy)
        Text(if (draft.dueAt.isEmpty()) "还没有选择时间" else displayFollowupTime(draft.dueAt, draft.timeZone) + " · " + draft.timeZone)
        Secondary("选择日期与时间", !locked && !model.state.busy) {
            val day = LocalDate.now().plusDays(1)
            DatePickerDialog(context, { _, year, month, date -> TimePickerDialog(context, { _, hour, minute ->
                val local = LocalDateTime.of(year, month + 1, date, hour, minute)
                val zone = runCatching { ZoneId.of(draft.timeZone) }.getOrNull()
                if (zone == null) model.tell("请先填写有效时区。")
                else if (zone.rules.getValidOffsets(local).size != 1) model.tell("这个时间遇到夏令时切换，请选择其他时间。")
                else model.editFollowup(dueAt = local.atZone(zone).toInstant().toString())
            }, 10, 0, true).show() }, day.year, day.monthValue - 1, day.dayOfMonth).show()
        }
        if (model.state.recurringFollowups) FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = draft.repeatRule == "once", onClick = { model.editFollowup(repeatRule = "once") }, label = { Text("一次") }, enabled = !locked && !model.state.busy)
            FilterChip(selected = draft.repeatRule == "daily", onClick = { model.editFollowup(repeatRule = "daily") }, label = { Text("每天") }, enabled = !locked && !model.state.busy)
        }
        OutlinedTextField(draft.timeZone, { model.editFollowup(timeZone = it) }, label = { Text("时区 · 如 Asia/Shanghai") }, modifier = Modifier.fillMaxWidth(), singleLine = true, readOnly = locked || model.state.busy)
        Text("时间按此时区保存；更改时区后请重新选择时间。每日跟进保留一条待处理事项，完成后才安排下一次。", fontSize = 12.sp, color = Muted)
        OutlinedTextField(draft.quietStart, { model.editFollowup(quietStart = it) }, label = { Text("安静开始 · HH:mm，可留空") }, modifier = Modifier.fillMaxWidth(), singleLine = true, readOnly = locked || model.state.busy)
        OutlinedTextField(draft.quietEnd, { model.editFollowup(quietEnd = it) }, label = { Text("安静结束 · HH:mm，需成对填写") }, modifier = Modifier.fillMaxWidth(), singleLine = true, readOnly = locked || model.state.busy)
        if (model.state.boundedFollowups) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(Shared.COPY_FOLLOWUP_CONTACT_CONSENT, modifier = Modifier.weight(1f))
                Switch(checked = draft.allowContact, onCheckedChange = { model.editFollowup(allowContact = it) }, enabled = !locked && !model.state.busy)
            }
            Text("默认不主动问。未允许或窗口过期仍保留待办；本手机不自动弹出或发送后台通知，其他已支持客户端也须遵守统一静默规则。", fontSize = 12.sp, color = Muted)
            if (draft.allowContact) {
                Text("从所选时间起 " + draft.contactWindowMinutes + " 分钟内，过期不补问")
                Slider(value = draft.contactWindowMinutes.toFloat(), onValueChange = { model.editFollowup(window = it.toInt()) }, valueRange = 5f..180f, steps = 34, enabled = !locked && !model.state.busy)
                OutlinedTextField(draft.contactTopic, { model.editFollowup(topic = it) }, label = { Text("只问这个话题 · 留空使用跟进正文") }, modifier = Modifier.fillMaxWidth(), readOnly = locked || model.state.busy)
            }
        }
        if (locked) Text("原保存结果仍待核对。内容与同一个请求标识已保留，先读列表核对，再由你决定是否用原请求重试。", color = Muted)
        Primary(if (locked) "核对并用原请求保存" else "确认保存这次跟进", !model.state.busy && draft.content.isNotBlank() && draft.dueAt.isNotEmpty(), model::saveFollowup)
        Secondary("先收起，保留文字", !model.state.busy, model::closeFollowup)
        if (!locked) Secondary("取消这份未保存的跟进", !model.state.busy, model::discardFollowup)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable private fun FollowupCards(model: EchoViewModel) {
    val state = model.state
    var showPast by remember { mutableStateOf(false) }
    var cancelling by remember { mutableStateOf<Followup?>(null) }
    WhiteCard("给未来的自己") {
        Text("打开回响时查看到期跟进；关闭期间不通知，不等同手机闹钟或后台推送。", fontSize = 13.sp, color = Muted)
        if (!state.followupsAvailable) Text("当前服务尚未提供本机跟进；更新服务后刷新即可。", color = Muted)
        FlowRow { Secondary(if (state.followupDraft == null) "留一条跟进" else "继续已保留的跟进", state.followupsAvailable && !state.busy, model::openFollowup); Secondary("刷新跟进", state.followupsAvailable && !state.busy, model::refreshFollowups) }
        val pending = state.followups.filter { it.status == "pending" }
        if (pending.isEmpty() && state.followupsAvailable) Text("还没有待跟进的事。", color = Muted)
        state.followups.filter { it.status == "pending" || showPast }.forEach { item ->
            Column(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(followupStateLabel(item), fontWeight = FontWeight.SemiBold)
                SelectionContainer { Text(item.content) }; Text(displayFollowupTime(item.dueAt, item.timeZone) + " · " + item.timeZone, color = Muted, fontSize = 13.sp)
                if (item.repeatRule == "daily") Text("每天", fontSize = 12.sp, color = Muted)
                if (item.quietStart != null && item.quietEnd != null) Text("安静时段 " + item.quietStart + "–" + item.quietEnd, fontSize = 12.sp, color = Muted)
                Text(followupContactLabel(item), fontSize = 12.sp, color = Muted)
                if (item.allowContact) {
                    Text("原约定话题：" + item.contactTopic + " · 窗口 " + item.contactWindowMinutes + " 分钟", fontSize = 12.sp, color = Muted)
                    item.contactExpiresAt?.let { Text("窗口截至 " + displayFollowupTime(it, item.timeZone) + " · " + item.timeZone, fontSize = 12.sp, color = Muted) }
                }
                if (!item.supportsNativeTransitions || (item.repeatRule == "daily" && !state.recurringFollowups)) Text("当前重复方式或服务能力未能核对，先只读查看。", color = Muted, fontSize = 13.sp)
                if (item.status == "pending" && item.supportsNativeTransitions && (item.repeatRule == "once" || state.recurringFollowups)) FlowRow {
                    Secondary(if (item.repeatRule == "daily") "完成本次" else "完成", !state.busy && (item.repeatRule != "daily" || item.due)) { model.changeFollowup(item, "done") }
                    if (state.recurringFollowups && item.pausedKnown) Secondary(if (item.paused) "恢复" else "暂停", !state.busy) { model.changeFollowup(item, if (item.paused) "resumed" else "paused") }
                    Secondary("取消", !state.busy) { cancelling = item }
                }
            }
        }
        if (state.followups.any { it.status != "pending" }) Secondary(if (showPast) "收起已处理跟进" else "查看已处理跟进") { showPast = !showPast }
    }
    cancelling?.let { item -> ConfirmSheet("取消这次跟进？", item.content + "\n取消后不会再作为待跟进显示；已保存的聊天和记忆不受影响。", onCancel = { cancelling = null }) { model.changeFollowup(item, "cancelled"); cancelling = null } }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable private fun CompanionBoundaryCard(model: EchoViewModel) {
    if (!model.state.boundaryAvailable) return
    val boundary = model.state.boundary
    WhiteCard(Shared.COPY_COMPANION_BOUNDARY_TITLE) {
        Text(when (boundary?.mode) {
            "active" -> Shared.COPY_COMPANION_BOUNDARY_ACTIVE
            "until" -> "先安静到 " + displayFollowupTime(boundary.until.orEmpty(), boundary.timeZone) + " · " + boundary.timeZone
            "paused" -> "主动轻问已暂停"
            else -> "边界状态暂时未能读取"
        }, fontWeight = FontWeight.SemiBold)
        Text(Shared.COPY_COMPANION_BOUNDARY_EFFECT + " 不会改系统通知权限。", fontSize = 12.sp, color = Muted)
        FlowRow {
            Secondary(Shared.COPY_COMPANION_BOUNDARY_TODAY, boundary != null && !model.state.busy) { model.changeBoundary("until") }
            Secondary(if (boundary?.isPaused == true) Shared.COPY_COMPANION_BOUNDARY_RESUME else Shared.COPY_COMPANION_BOUNDARY_PAUSE, boundary != null && !model.state.busy) { model.changeBoundary(if (boundary?.isPaused == true) "active" else "paused") }
            Secondary("重新读取", !model.state.busy, model::refreshBoundary)
        }
    }
}

@Composable private fun Orb(size: Int, comfort: Comfort, status: String = Shared.COPY_STATE_QUIET) {
    val motion = !comfort.reduceMotion && ValueAnimator.areAnimatorsEnabled()
    val scale = if (motion) rememberInfiniteTransition(label = "缓慢呼吸").animateFloat(1f, 1.045f, infiniteRepeatable(tween(9000, easing = LinearEasing), RepeatMode.Reverse), label = "光的呼吸").value else 1f
    Box(Modifier.size(size.dp).scale(scale).semantics { contentDescription = status + if (motion) "，雾蓝淡杏的光缓慢呼吸" else "，静止的雾蓝淡杏光" }.background(Brush.radialGradient(listOf(Color.White, sharedColor(if (status == "在听你说") Shared.COLOR_BLOB_PEACH else Shared.COLOR_BLOB_BLUE).copy(alpha = comfort.lightIntensity), sharedColor(Shared.COLOR_BLOB_PEACH).copy(alpha = comfort.lightIntensity))), RoundedCornerShape(50)))
}

@Composable private fun Primary(text: String, enabled: Boolean = true, click: () -> Unit) { Button(onClick = click, enabled = enabled, modifier = Modifier.heightIn(min = Shared.DIMENSION_TOUCH_ANDROID.dp), shape = RoundedCornerShape(28.dp)) { Text(text) } }
@Composable private fun Secondary(text: String, enabled: Boolean = true, click: () -> Unit) { TextButton(onClick = click, enabled = enabled, modifier = Modifier.heightIn(min = Shared.DIMENSION_TOUCH_ANDROID.dp)) { Text(text) } }
@Composable private fun WhiteCard(title: String, content: @Composable ColumnScope.() -> Unit) {
    Surface(color = Color.White, shape = RoundedCornerShape(Shared.DIMENSION_CARD_RADIUS.dp), modifier = Modifier.fillMaxWidth()) { Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) { Text(title, fontSize = 18.sp, fontWeight = FontWeight.SemiBold); content() } }
}
@OptIn(ExperimentalLayoutApi::class)
@Composable private fun Today(model: EchoViewModel, toChat: (String) -> Unit, toTasks: () -> Unit, toMemories: () -> Unit, toSources: () -> Unit) {
    val state = model.state; val conversation = state.conversation ?: return
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Orb(90, model.comfort); Text("留一点空间给自己。", style = MaterialTheme.typography.titleLarge)
        WhiteCard(if (conversation.bookmark.isBlank()) "今天，从这里开始" else "上次停在这里") {
            Text(conversation.bookmark.ifBlank { state.nextStep.ifBlank { "可以先说一件正在发生的事。" } })
            if (conversation.bookmarkNext.isNotBlank()) Text(conversation.bookmarkNext)
            Primary("把这条带回对话") { toChat(conversation.bookmarkNext.ifBlank { conversation.bookmark.ifBlank { state.nextStep } }) }
            Text(Shared.COPY_CHAT_DRAFT_DISCLOSURE, fontSize = 13.sp, color = Muted)
        }
        WhiteCard("你愿意留下的") { Text("${conversation.memories.size} 条记忆 · ${conversation.sources.size} 份已接入资料"); FlowRow { Secondary("看看记忆", click = toMemories); Secondary("查看任务", click = toTasks); Secondary("连接资料", click = toSources) } }
        if (state.moodsAvailable) MoodEntryCard(model)
        CompanionBoundaryCard(model)
        FollowupCards(model)
        Secondary("刷新今天", !state.busy, model::refresh)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable private fun Chat(model: EchoViewModel, readAloud: ReadAloudController, speech: ReadAloudState) {
    val state = model.state; val conversation = state.conversation ?: return
    val scroll = rememberLazyListState()
    var tagging by remember { mutableStateOf<Message?>(null) }
    var remembering by remember { mutableStateOf<Message?>(null) }
    val displayed = conversation.messages.filter { TopicPolicy.matches(state.topics, it.id, state.selectedTopic) }
    LaunchedEffect(state.focusMessageId, displayed.size) {
        val target = state.focusMessageId?.let { id -> displayed.indexOfFirst { it.id == id }.takeIf { it >= 0 } }
        if (target != null) { scroll.scrollToItem(target); model.clearMessageFocus() }
    }
    LaunchedEffect(conversation.messages.size, state.pending?.id) {
        if (displayed.isNotEmpty() && state.focusMessageId == null) {
            if (model.comfort.reduceMotion || !ValueAnimator.areAnimatorsEnabled()) scroll.scrollToItem(displayed.size - 1)
            else scroll.animateScrollToItem(displayed.size - 1)
        }
    }
    tagging?.let { message -> TopicSheet(message, model) { tagging = null } }
    remembering?.let { message -> ConfirmSheet("记下这句原话？", message.text + "\n确认后可能在相关聊天中参考；之后可修改或忘掉。不记也可以。", onCancel = { remembering = null }) { model.rememberQuote(message); remembering = null } }
    Column(Modifier.fillMaxSize().imePadding()) {
        FlowRow(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            TopicPolicy.labels(state.topics).forEach { label -> FilterChip(selected = state.selectedTopic == label, onClick = { model.selectTopic(label) }, label = { Text(label) }, modifier = Modifier.heightIn(min = Shared.DIMENSION_TOUCH_ANDROID.dp)) }
        }
        Text("话题只是本设备的查看方式，仍是同一条对话。", modifier = Modifier.padding(horizontal = 16.dp), fontSize = 12.sp, color = Muted)
        Text(Shared.COPY_VOICE_DISCLOSURE, modifier = Modifier.padding(horizontal = 16.dp), fontSize = 12.sp, color = Muted)
        if (speech.stopUncertain) {
            Text("系统尚未确认停止，当前不会开始另一条朗读。", modifier = Modifier.padding(horizontal = 16.dp), fontSize = 13.sp, color = Muted)
            Secondary(Shared.COPY_VOICE_STOP, click = readAloud::stop)
        }
        LazyColumn(state = scroll, modifier = Modifier.weight(1f).fillMaxWidth(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            if (displayed.isEmpty()) item { WhiteCard("回响在这里") { Text(if (state.selectedTopic != "全部") "这个话题还没有消息。可以在消息下标记，或切回全部。" else "先说此刻想说的，资料可以稍后再连。") } }
            items(displayed, key = { it.id }) { message ->
                val mine = message.role == "user"
                Row(Modifier.fillMaxWidth(), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        message.displayParts.forEach { part ->
                            Surface(color = if (mine) UserBubble else Color.White, shape = RoundedCornerShape(topStart = 22.dp, topEnd = if (mine) 6.dp else 22.dp, bottomEnd = 22.dp, bottomStart = if (mine) 22.dp else 6.dp), modifier = Modifier.widthIn(max = 310.dp)) {
                                SelectionContainer { Text(part, modifier = Modifier.padding(16.dp), fontSize = Shared.DIMENSION_BODY_FONT.sp, lineHeight = 25.sp) }
                            }
                        }
                        if (ReadAloudPolicy.target(ReadAloudContext(model.baseUrl, conversation, displayed.map { it.id }.toSet(), true), message.id) != null) {
                            val selected = speech.target?.let { it.endpoint == model.baseUrl && it.sessionId == conversation.id && it.messageId == message.id } == true
                            Secondary(if (selected && speech.active) Shared.COPY_VOICE_STOP else Shared.COPY_VOICE_READ) {
                                if (selected && speech.active) readAloud.stop() else readAloud.play(message.id)
                            }
                            if (selected) when (speech.phase) {
                                ReadAloudPhase.PREPARING, ReadAloudPhase.QUEUED -> Text(Shared.COPY_VOICE_PREPARING, color = Muted, fontSize = 13.sp)
                                ReadAloudPhase.SPEAKING -> Text("正在朗读这条回复。", color = Muted, fontSize = 13.sp)
                                ReadAloudPhase.UNAVAILABLE -> Column {
                                    Text(Shared.COPY_VOICE_UNAVAILABLE, color = Muted, fontSize = 13.sp)
                                    Text(when (speech.unavailable) {
                                        ReadAloudUnavailable.NO_LOCAL_VOICE -> "尚未找到可用的已安装离线语音。"
                                        ReadAloudUnavailable.INITIALIZATION -> "系统语音引擎暂未就绪。"
                                        ReadAloudUnavailable.INPUT_LIMIT -> "这段内容无法由当前引擎完整朗读，原文仍保留。"
                                        ReadAloudUnavailable.TIMEOUT -> "系统语音未及时回应，这次朗读未能完成。"
                                        ReadAloudUnavailable.STOP_UNCERTAIN -> "系统尚未确认停止；当前不会开始另一条朗读。"
                                        else -> "这次朗读未能完成，可稍后重新点选。"
                                    }, color = Muted, fontSize = 13.sp)
                                }
                                ReadAloudPhase.IDLE -> Unit
                            }
                        }
                        if (!mine && message.deliveryPending && state.targetedDeliveryStop && state.pending == null && conversation.messages.lastOrNull()?.id == message.id) Secondary("停止展开", !state.busy) { model.stopDelivery(message) }
                        if (mine) Secondary("记下这句", !state.busy && state.pending == null) { remembering = message }
                        Secondary("标记话题") { readAloud.stop(); tagging = message }
                    }
                }
            }
            state.pending?.let { turn -> item { WhiteCard("发送状态待核对") { Text(turn.text); Text("原话和同一个请求标识保存在这台设备。不会自动重发。", fontSize = 13.sp) } } }
        }
        state.memoryOffer?.takeIf { it.matches(state.conversation) }?.let { offer -> WhiteCard("这句偏好，要留下吗？") {
            SelectionContainer { Text(offer.text) }; Text("只在你选择后保存这句原话；之后相关时可能参考，可在记忆中修改或忘掉。", fontSize = 13.sp, color = Muted)
            FlowRow { Secondary("不用", !state.busy, model::dismissMemoryOffer); Primary("记住这句", !state.busy && state.pending == null) { conversation.messages.find { it.id == offer.messageId }?.let(model::rememberQuote) } }
        } }
        state.quoteForReview?.takeIf { it.matches(state.conversation) }?.let { review -> WhiteCard("这句尚未直接选存") {
            SelectionContainer { Text(review.text) }; Text("你可以整理原话并明确保存为待确认候选；这一步不会自动记住，也不会确认候选。", fontSize = 13.sp, color = Muted)
            FlowRow { Secondary("暂时不用", !state.busy, model::dismissQuoteReview); Primary("整理为候选记忆", !state.busy, model::prepareQuoteCandidate) }
            if (state.memoryDraft != null) Secondary("继续已有记忆草稿", !state.busy) { model.openMemoryEditor() }
        } }
        state.pending?.let { Column(Modifier.padding(horizontal = 12.dp)) { FlowRow { Secondary("核对状态", !state.busy, model::recover); Secondary("停止回复", click = model::cancelTurn); Secondary("核对原请求", !state.busy, model::retrySameId) }; Secondary("核对记录后把原话放回输入框", !state.busy, model::returnUncertainText) } }
        Surface(color = Color.White, shape = RoundedCornerShape(28.dp), modifier = Modifier.fillMaxWidth().padding(12.dp)) {
            Column(Modifier.padding(10.dp)) {
                OutlinedTextField(state.draft, model::draft, modifier = Modifier.fillMaxWidth(), placeholder = { Text("说说此刻想说的…") }, minLines = 1, maxLines = 6, shape = RoundedCornerShape(Shared.DIMENSION_CARD_RADIUS.dp), colors = OutlinedTextFieldDefaults.colors(focusedContainerColor = Color.White, unfocusedContainerColor = Color.White))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) { Primary("发送", !state.busy && state.pending == null && state.draft.isNotBlank(), model::send) }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable private fun Memories(model: EchoViewModel, onOpen: (Memory) -> Unit, onForget: (Memory) -> Unit) {
    val state = model.state; val memories = state.conversation?.memories.orEmpty()
    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item { Text("记得，也能改。", style = MaterialTheme.typography.titleLarge); FlowRow { Secondary("手动记一件事", !state.busy) { model.openMemoryEditor() }; Secondary("刷新记忆", !state.busy, model::refresh) }; if (state.memoryDraft != null) Secondary("继续已保留的记忆草稿") { model.openMemoryEditor() } }
        if (memories.isEmpty()) item { Text("还没有留下的记忆。你可以在自己的消息下点「记下这句」。") }
        items(memories, key = { it.id }) { memory -> WhiteCard(memory.text) {
            val inference = memory.kind == "inference" && memory.status != "confirmed"
            Text(if (inference) Shared.COPY_MEMORY_SOURCE_INFERENCE else if (memory.sourceMessageId.isNotBlank()) Shared.COPY_MEMORY_SOURCE_USER else if (memory.sourceAttachmentId.isNotBlank()) Shared.COPY_MEMORY_SOURCE_DOCUMENT else if (memory.source.contains("手动")) "你主动记下" else memory.source.ifBlank { "来源待核对" }, color = Muted, fontSize = 13.sp)
            Text("${memory.source} · v${memory.version}", fontSize = 13.sp, color = Muted)
            Text(if (memory.status == "confirmed") "我会在相关话题里参考；你随时能纠正或忘掉。" else "这条尚待核对；点「是的」后才作为确认记忆。")
            FlowRow { Secondary("查看与修改") { onOpen(memory) }; if (memory.status != "confirmed") { Secondary("是的", !state.busy) { model.confirmMemory(memory) }; Secondary("不是") { onForget(memory) } } }
        } }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable private fun Tasks(model: EchoViewModel) {
    val state = model.state; val clipboard = LocalClipboardManager.current
    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item { Text("由你决定的下一步", style = MaterialTheme.typography.titleLarge)
            if (model.pairedMode) Text("配对手机可以查看你约定的关心与待办；电脑动作请在电脑上核对。", fontSize = 13.sp, color = Muted)
            else FlowRow { Secondary("消息草稿", !state.busy) { model.newAction("message") }; Secondary("提醒", !state.busy) { model.newAction("reminder") }; Secondary("日历安排", !state.busy) { model.newAction("calendar") } }
        }
        if (model.pairedMode) item { FollowupCards(model) }
        if (!model.pairedMode && state.actions.isEmpty()) item { Text("还没有保存的动作。可以先写一条，再核对。") }
        items(state.actions, key = { it.id }) { action -> WhiteCard(action.title) {
            Text(when (action.status) { "previewed" -> "待你确认"; "unknown", "executing" -> "结果待核对"; "failed" -> "未能完成"; "committed" -> if (action.kind == "message") "草稿已保存 · 未发送" else if (action.real) "后端曾写入系统" else "仅存本机 · 未写入系统"; else -> "未识别的状态，请刷新核对" }, color = Muted)
            if (action.whenText.isNotBlank()) Text(action.whenText)
            SelectionContainer { Text(action.detail.ifBlank { "没有补充说明。" }) }
            if (action.receipt.isNotBlank()) Text("回执：${action.receipt}", fontSize = 13.sp)
            when (actionRoute(action.status)) { ActionRoute.CONFIRM_EXISTING -> Primary("继续确认同一条记录", !state.busy) { model.savedAction(action) }; ActionRoute.CHECK_ONLY -> Secondary("核对本机状态", !state.busy) { model.savedAction(action) }; else -> Unit }
            if (action.kind == "message") Secondary("复制完整草稿") { clipboard.setText(AnnotatedString(action.detail)); model.tell("已复制，尚未发送。") }
        } }
        item { Secondary("刷新任务状态", !state.busy, model::refresh) }
    }
}

@Composable private fun Sources(model: EchoViewModel, chooseFiles: () -> Unit, onPlan: (JSONObject) -> Unit, onRemove: (Source) -> Unit) {
    val state = model.state
    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item { Text("只连接需要的片段", style = MaterialTheme.typography.titleLarge); Text("文件由 Android 系统选择器选择；其他来源由后端所在电脑读取，手机不会取得它的 CLI 登录身份。") }
        item { WhiteCard("本机文本") { Text("最多 3 份 UTF-8 文本，单份最多 256 KB。先在 App 中预览，再确认上传前 4000 字符。") ; Primary("选择文本文件", !state.busy && state.pending == null, chooseFiles) } }
        items(state.conversation?.sources.orEmpty(), key = { it.id }) { source -> WhiteCard(source.title) { Text("${source.label} · ${if (source.stale) "待核对，暂不使用" else "已接入当前对话"}"); Secondary("移除这份资料", !state.busy) { onRemove(source) } } }
        items(state.descriptors.filter { !model.pairedMode && it.str("id") != "local_files" }, key = { it.str("id") }) { descriptor -> WhiteCard(descriptor.str("name")) { Text(descriptor.str("blurb")); Text(when { descriptor.str("id") !in SourcePolicy.supported -> "此端尚未开放"; descriptor.str("status") == "ready" -> "后端已有条件 · 仍需指定范围与预览"; descriptor.str("status") == "needs_auth" -> "后端需要授权 · 本机未发起"; descriptor.str("status") == "needs_click" -> "系统权限尚待核验 · 本机不触发授权"; else -> descriptor.str("hint", "暂不可用") }, color = Muted); Secondary("查看范围", !state.busy && state.pending == null) { onPlan(descriptor) } } }
        if (model.pairedMode) item { Text("飞书、Notion、Git、GitHub 和电脑日历等来源请在电脑接入；此手机不会启动 CLI、系统授权或硬件动作。", fontSize = 13.sp, color = Muted) }
        item { WhiteCard("Rokid 与脑电") { Text("设备仍在队友处待联调。当前 Android 版不连接眼镜、不采集脑电，也不把专注度当作情绪。") }; Secondary("重新检查连接", !state.busy, model::sources) }
    }
}

@Composable private fun Sheet(title: String, onClose: () -> Unit, content: @Composable ColumnScope.() -> Unit) {
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(shape = RoundedCornerShape(28.dp), color = Color.White, modifier = Modifier.fillMaxWidth(.94f).widthIn(max = 560.dp).fillMaxHeight(.9f)) {
            Column(Modifier.verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) { Text(title, style = MaterialTheme.typography.titleLarge); content(); Secondary("关闭", click = onClose) }
        }
    }
}
@Composable private fun ConfirmSheet(title: String, explanation: String, onCancel: () -> Unit, confirm: () -> Unit) {
    Sheet(title, onCancel) { Text(explanation); Primary("确认", click = confirm); Secondary("不用", click = onCancel) }
}
@Composable private fun MemorySheet(memory: Memory, model: EchoViewModel, onClose: () -> Unit, onForget: () -> Unit) {
    val latest = model.state.conversation?.memories?.find { it.id == memory.id } ?: memory
    val originalTime = latest.sourceMessageId.takeIf { it.isNotBlank() }?.let { sourceId -> model.state.conversation?.messages?.firstOrNull { it.id == sourceId }?.createdAt?.takeIf { it.isNotBlank() } } ?: "未提供原话时间"
    Sheet("这条记忆", onClose) {
        Text("说于：$originalTime\n来源：${latest.source.ifBlank { "未提供来源" }}\n记下于：${latest.createdAt.ifBlank { "暂无时间记录" }}\n用在：相关话题的回答；未经确认的推测不当作你的事实。", fontSize = 14.sp, color = Muted)
        Text("下次可能这样提起：你曾说过「${memory.text}」，现在还符合吗？")
        SelectionContainer { Text(latest.text) }
        Primary("改一改这条", !model.state.busy) { onClose(); model.openMemoryEditor(latest) }
        Text("当前版本 v${latest.version}；修改时会核对版本，避免覆盖其他端的纠正。", fontSize = 13.sp, color = Muted)
        Secondary("查看版本历史", !model.state.busy) { model.history(memory) }
        model.state.revisions.filter { it.str("memory_id", memory.id) == memory.id }.forEach { Text("v${it.optInt("version")} · ${it.str("text")}", fontSize = 14.sp) }
        TextButton(onClick = onForget, modifier = Modifier.heightIn(min = Shared.DIMENSION_TOUCH_ANDROID.dp)) { Text("忘掉这条", color = MaterialTheme.colorScheme.error) }
    }
}
@OptIn(ExperimentalLayoutApi::class)
@Composable private fun ActionSheet(editor: ActionEditor, model: EchoViewModel) {
    val context = LocalContext.current
    Sheet(Shared.COPY_PLAN_TITLE, model::closeAction) {
        Text("1. 保存下方你核对的标题与内容。\n2. 结果留在后端本机，可在任务中查看。\n3. 不发送消息，也不写入系统日历或提醒事项。")
        if (editor.immutable) Text("继续确认已保存的原预览，同一 ID 不会重复新建；需要改内容时请关闭并新建。", color = Muted)
        OutlinedTextField(editor.title, { model.editAction(editor.copy(title = it)) }, label = { Text("标题") }, readOnly = editor.immutable, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(editor.detail, { model.editAction(editor.copy(detail = it)) }, label = { Text(if (editor.kind == "message") "完整草稿正文" else "补充说明") }, readOnly = editor.immutable, modifier = Modifier.fillMaxWidth(), minLines = 3)
        if (editor.kind == "calendar") {
            Text(editor.whenText.ifBlank { "尚未选择时间" })
            Secondary("选择日期与时间", !editor.immutable && !model.state.busy) {
                val day = LocalDate.now().plusDays(1)
                DatePickerDialog(context, { _, year, month, date -> TimePickerDialog(context, { _, hour, minute -> model.editAction(editor.copy(whenText = String.format(Locale.ROOT, "%04d-%02d-%02dT%02d:%02d", year, month + 1, date, hour, minute))) }, 10, 0, true).show() }, day.year, day.monthValue - 1, day.dayOfMonth).show()
            }
        }
        if (editor.uncertain) Text("保存结果尚未确认，请先关闭并刷新任务。不会盲目重复创建或写入。", color = Muted)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) { Secondary("不用", click = model::closeAction); Primary("好，保存本机", !model.state.busy && !editor.uncertain, model::commitAction) }
        Text("为什么先问你：这次批准只对应当前内容。开始后关闭窗口不代表撤回已发出的保存请求。", fontSize = 13.sp, color = Muted)
    }
}
@Composable private fun SettingsSheet(model: EchoViewModel, beforeEndpointChange: () -> Unit, onClose: () -> Unit) {
    var endpoint by remember { mutableStateOf(model.baseUrl) }
    var recovery by remember { mutableStateOf<PairedProfile?>(null) }
    var removingConnection by remember { mutableStateOf<PairedProfile?>(null) }
    LaunchedEffect(model) { model.loadSavedConnections() }
    var deviceToken by remember { mutableStateOf("") } // Never save to savedInstanceState or plain preferences.
    LaunchedEffect(model.dataContextId) { deviceToken = ""; recovery = null }
    var lab by remember { mutableStateOf(false) }
    if (lab) { MoodExperiment { lab = false }; return }
    Sheet("设置", onClose) {
        Text("实验区", fontWeight = FontWeight.SemiBold)
        Secondary("心情表达实验") { deviceToken = ""; recovery = null; lab = true }
        Text("比较两种心情表达方式；结果不会保存。", fontSize = 13.sp, color = Muted)
        Text("记忆由你决定", fontWeight = FontWeight.SemiBold)
        SettingSwitch("聊天后，可以提议记住一件小事", model.memoryProposals, model::memoryProposals)
        Text("默认关闭。开启后只展示待你选择的原话提议，不自动成为确认事实。每次发送的选择与标识一起保留；之后切换开关不会改变未决请求。", fontSize = 13.sp, color = Muted)
        Text("阅读与光", fontWeight = FontWeight.SemiBold)
        SettingSwitch("减少动态", model.comfort.reduceMotion) { model.preferences(model.comfort.copy(reduceMotion = it)) }
        SettingSwitch("降低透明度", model.comfort.reduceTransparency) { model.preferences(model.comfort.copy(reduceTransparency = it)) }
        Text("光的强度 · ${(model.comfort.lightIntensity * 100).toInt()}%")
        Slider(model.comfort.lightIntensity, { model.preferences(model.comfort.copy(lightIntensity = it)) }, modifier = Modifier.semantics { contentDescription = "光的强度，仅改变品牌光球，不改变设备屏幕亮度" })
        Text("字号跟随 Android 系统设置，不限制到 200% 以下。减少动态也遵循系统关闭动画的选择。", fontSize = 13.sp, color = Muted)
        Text(Shared.COPY_CONNECTION_DEVICES_TITLE, fontWeight = FontWeight.SemiBold)
        Text(model.connectionStatus.ifBlank { "尚未核对连接" }, color = Muted)
        if (model.connectionNeedsPairing) Text(Shared.COPY_CONNECTION_DEVICES_INVALID, fontSize = 13.sp, color = Muted)
        if (model.connectionIdentity.isNotBlank()) Text(model.connectionIdentity, fontSize = 13.sp)
        if (model.connectionExpiry.isNotBlank()) Text("设备许可到期：" + model.connectionExpiry, fontSize = 13.sp, color = Muted)
        OutlinedTextField(endpoint, { endpoint = it }, label = { Text("HTTPS 后端地址") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(deviceToken, { deviceToken = it }, label = { Text("此设备的配对令牌") }, modifier = Modifier.fillMaxWidth(), singleLine = true, visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, autoCorrectEnabled = false))
        Text(Shared.COPY_CONNECTION_DEVICES_SCOPE, fontSize = 13.sp, color = Muted)
        Text(Shared.COPY_CONNECTION_DEVICES_SECRET, fontSize = 13.sp, color = Muted)
        Text("仅 HTTPS、受信任证书；不会跳过证书错误。验证成功后用本机 Keystore 密钥加密保存，失败保留原连接；这里不填写模型 Key。", fontSize = 13.sp, color = Muted)
        Primary(if (recovery == null) Shared.COPY_CONNECTION_DEVICES_VERIFY else "验证并恢复此身份", !model.state.busy && deviceToken.isNotBlank()) { beforeEndpointChange(); model.pairDevice(endpoint, deviceToken, recovery) }
        recovery?.let { profile -> Text("正在核对旧身份：${profile.label}。只接受同一服务、对话和设备的有效原令牌；不自动重发旧操作。", fontSize = 13.sp, color = Muted); Secondary("改为配对新设备") { recovery = null; deviceToken = "" } }
        if (model.pairedMode) Secondary("停止使用此设备令牌", !model.state.busy) { beforeEndpointChange(); model.disconnectDevice(); deviceToken = "" }
        Text("停止使用会清除本机令牌并隔离旧草稿与未决请求，不撤销电脑上的许可；请在电脑撤销设备。重新配对不自动迁移或重发旧操作。", fontSize = 13.sp, color = Muted)
        if (BuildConfig.DEBUG) {
            Text("开发者 USB 调试", fontWeight = FontWeight.SemiBold)
            Text("仅 debug 可用 http://127.0.0.1:18787；先执行 adb reverse tcp:18787 tcp:18787。HTTP 不携带配对令牌，不开放局域网。", fontSize = 13.sp, color = Muted)
            Secondary("使用本机调试地址", !model.state.busy && model.state.pending == null) { beforeEndpointChange(); model.endpoint(EndpointPolicy.DEFAULT); deviceToken = "" }
        }
        if (model.savedConnections.any { it.scope != model.activeConnectionScope }) {
            Text("留在本机的旧连接", fontWeight = FontWeight.SemiBold)
            Text("点恢复后才读取此身份的本机加密凭据，并在线核对原服务、对话和设备。凭据已移除时才需填写有效原码；失效时请在电脑核对，不会换身份重发。", fontSize = 13.sp, color = Muted)
            model.savedConnections.filter { it.scope != model.activeConnectionScope }.forEach { profile ->
                WhiteCard(profile.label) {
                    Text(profile.origin, fontSize = 13.sp); Text("设备 ${profile.deviceId.take(12)} · 原许可 ${profile.expiresAt}", fontSize = 13.sp, color = Muted)
                    Secondary("恢复此身份", !model.state.busy) { beforeEndpointChange(); recovery = profile; endpoint = profile.origin; deviceToken = ""; model.restoreSavedConnection(profile) }
                    Secondary("移除此身份的本机资料", !model.state.busy) { removingConnection = profile }
                }
            }
        }
        Text("资料由你确认接入；记忆可以修改或忘掉。", fontSize = 13.sp, color = Muted)
    }
    removingConnection?.let { profile -> ConfirmSheet("移除这份本机资料？", "将删除「${profile.label}」此身份在手机上保留的草稿与未决请求副本。不会撤销设备的服务端许可，也不会取消已发出的操作；请先在电脑核对记录。", onCancel = { removingConnection = null }) { model.removeSavedConnection(profile); if (recovery?.scope == profile.scope) recovery = null; removingConnection = null } }
}
/** State is local to this screen; it is discarded when the experiment closes. */
@Composable private fun MoodExperiment(onClose: () -> Unit) {
    var method by remember { mutableIntStateOf(0) }
    var x by remember { mutableFloatStateOf(0f) }
    var y by remember { mutableFloatStateOf(0f) }
    var selectedX by remember { mutableStateOf(false) }
    var selectedY by remember { mutableStateOf(false) }
    fun update(p: Offset, w: Int, h: Int) {
        if (w <= 0 || h <= 0) return
        x = (2f * p.x / w - 1f).coerceIn(-1f, 1f)
        y = (1f - 2f * p.y / h).coerceIn(-1f, 1f)
        selectedX = true; selectedY = true
    }
    Sheet("心情表达实验", onClose) {
        Text("给感受一个位置", style = MaterialTheme.typography.titleLarge)
        Text("试试哪一种方式更容易表达此刻。切换方式时保留这个试验位置，离开后清空。", color = Muted)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (method == 0) Button(onClick = { method = 0 }) { Text("拖动位置") } else OutlinedButton(onClick = { method = 0 }) { Text("拖动位置") }
            if (method == 1) Button(onClick = { method = 1 }) { Text("两条滑杆") } else OutlinedButton(onClick = { method = 1 }) { Text("两条滑杆") }
        }
        if (method == 0) {
            Text("点击或拖动，找到更接近的位置。需要无障碍操作时可切换到两条滑杆。", fontSize = 13.sp, color = Muted)
            Canvas(Modifier.fillMaxWidth().height(220.dp)
                .pointerInput(Unit) { detectTapGestures { update(it, size.width, size.height) } }
                .pointerInput(Unit) { detectDragGestures(onDragStart = { update(it, size.width, size.height) }) { change, _ -> update(change.position, size.width, size.height); change.consume() } }
                .semantics { contentDescription = "心情地图：左侧不舒服，右侧舒服，上方能量高，下方能量低；可切换到两条滑杆操作" }) {
                val halfW = size.width / 2; val halfH = size.height / 2
                drawRect(Color(0xFFFFE2D1), size = Size(halfW, halfH))
                drawRect(Color(0xFFDCEEFF), topLeft = Offset(halfW, 0f), size = Size(halfW, halfH))
                drawRect(Color(0xFFEAF0F8), topLeft = Offset(0f, halfH), size = Size(halfW, halfH))
                drawRect(Color(0xFFFFF0E8), topLeft = Offset(halfW, halfH), size = Size(halfW, halfH))
                if (selectedX && selectedY) {
                    val center = Offset(((x + 1) * halfW).coerceIn(10f, size.width - 10f), ((1 - y) * halfH).coerceIn(10f, size.height - 10f))
                    drawCircle(Color.White, radius = 11f, center = center); drawCircle(Ink, radius = 7f, center = center)
                }
            }
            Text("← 不舒服　　舒服 →\n↑ 能量高　　能量低 ↓", fontSize = 13.sp, color = Muted)
        } else {
            Text("舒服程度：${if (selectedX) moodAxis(x, "不舒服", "舒服") else "还没选择"}")
            Slider(value = x, onValueChange = { x = it; selectedX = true }, valueRange = -1f..1f, modifier = Modifier.semantics { contentDescription = "舒服程度，从不舒服到舒服" })
            if (!selectedX) TextButton(onClick = { x = 0f; selectedX = true }) { Text("舒服程度选中间") }
            Text("能量水平：${if (selectedY) moodAxis(y, "低", "高") else "还没选择"}")
            Slider(value = y, onValueChange = { y = it; selectedY = true }, valueRange = -1f..1f, modifier = Modifier.semantics { contentDescription = "能量水平，从低到高" })
            if (!selectedY) TextButton(onClick = { y = 0f; selectedY = true }) { Text("能量水平选中间") }
        }
        Text(if (selectedX && selectedY) "舒服程度：${moodAxis(x, "不舒服", "舒服")} · 能量：${moodAxis(y, "低", "高")}" else "还没有选定位置。", fontWeight = FontWeight.SemiBold)
        Secondary("重新试试") { x = 0f; y = 0f; selectedX = false; selectedY = false }
        Text("这是交互实验，不是心理诊断。不会保存或上传，也不会读取对话、手表、眼镜或脑电数据。", fontSize = 13.sp, color = Muted)
    }
}
private fun moodAxis(value: Float, low: String, high: String): String =
    if (kotlin.math.abs(value) < .05f) "中间" else "${if (value < 0) low else high} ${(kotlin.math.abs(value) * 100).toInt()}%"
@Composable private fun SettingSwitch(title: String, checked: Boolean, change: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().heightIn(min = Shared.DIMENSION_TOUCH_ANDROID.dp).clickable { change(!checked) }, horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) { Text(title, modifier = Modifier.weight(1f)); Switch(checked = checked, onCheckedChange = change) }
}
