package cn.xinji.echo

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import cn.xinji.echo.shared.EchoSharedReference as Shared
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

@Composable fun MoodEntryCard(model: EchoViewModel) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(Shared.COPY_MOOD_TITLE, style = MaterialTheme.typography.titleLarge)
            Text("给想记录的感受留一个位置，没有标准答案。")
            Text(Shared.COPY_MOOD_CONTEXT, style = MaterialTheme.typography.bodySmall)
            Button(onClick = model::openMoods, enabled = !model.state.busy) { Text(Shared.COPY_MOOD_OPEN) }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun MoodEditor(model: EchoViewModel, onToChat: (String) -> Unit) {
    val state = model.state
    val draft = state.moodDraft
    var chooseDate by remember { mutableStateOf(false) }
    var deleteConfirm by remember(draft?.date, draft?.expectedUpdatedAt) { mutableStateOf(false) }
    var discardConfirm by remember { mutableStateOf(false) }
    var cancelConfirm by remember { mutableStateOf(false) }
    var historyLimit by remember { mutableIntStateOf(10) }
    Dialog(onDismissRequest = model::closeMoods, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(shape = MaterialTheme.shapes.extraLarge, modifier = Modifier.fillMaxWidth(.94f).widthIn(max = 560.dp).fillMaxHeight(.9f)) {
            Column(Modifier.verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Text(Shared.COPY_MOOD_TITLE, style = MaterialTheme.typography.titleLarge)
                Text(Shared.COPY_MOOD_CONTEXT)
                Text("一条记录只表示你愿意为这一天留下的感受，不是测量结果。")
                if (!state.moodLocalSaved) {
                    Text("本机存储未成功，请先复制文字；当前草稿仅在运行中的页面里。", color = MaterialTheme.colorScheme.error)
                    OutlinedButton(onClick = model::retryLocalMoodDraft, enabled = !state.busy) { Text("再次保存本机草稿，不提交") }
                }
                if (!state.moodsLoaded) Text("记录尚未读取或需要重新核对；不会把空列表当作没有记录。", color = MaterialTheme.colorScheme.error)
                OutlinedButton(onClick = model::reconcileMood, enabled = !state.busy) { Text(if (draft?.operationId != null) Shared.COPY_MOOD_RECOVERY_CHECK else "读取并核对最新记录") }
                if (draft != null) {
                    Text("记录日期：${draft.date}", style = MaterialTheme.typography.titleMedium)
                    OutlinedButton(onClick = { chooseDate = true }, enabled = !state.busy && state.moodsLoaded && !draft.dirty && !draft.locked) { Text("选择日期") }
                    Text(Shared.COPY_MOOD_VALENCE)
                    Text(if (draft.xChosen) "已选择：${"%.2f".format(java.util.Locale.ROOT, draft.x)}" else "还没有选择感受位置")
                    Slider(value = draft.x.toFloat(), onValueChange = { model.editMood(x = it.toDouble()) }, valueRange = -1f..1f,
                        enabled = !state.busy && state.moodsLoaded && !draft.locked, modifier = Modifier.semantics { contentDescription = Shared.COPY_MOOD_VALENCE })
                    TextButton(onClick = { model.editMood(x = 0.0) }, enabled = !state.busy && state.moodsLoaded && !draft.locked) { Text("感受选择中间位置") }
                    Text(Shared.COPY_MOOD_ENERGY)
                    Text(if (draft.yChosen) "已选择：${"%.2f".format(java.util.Locale.ROOT, draft.y)}" else "还没有选择精力位置")
                    Slider(value = draft.y.toFloat(), onValueChange = { model.editMood(y = it.toDouble()) }, valueRange = -1f..1f,
                        enabled = !state.busy && state.moodsLoaded && !draft.locked, modifier = Modifier.semantics { contentDescription = Shared.COPY_MOOD_ENERGY })
                    TextButton(onClick = { model.editMood(y = 0.0) }, enabled = !state.busy && state.moodsLoaded && !draft.locked) { Text("精力选择中间位置") }
                    OutlinedTextField(value = draft.note, onValueChange = { model.editMood(note = it) }, label = { Text(Shared.COPY_MOOD_NOTE) },
                        modifier = Modifier.fillMaxWidth(), minLines = 3, readOnly = state.busy || draft.locked || !state.moodsLoaded)
                    if (draft.locked) {
                        Text(if (draft.cancelRequested) "取消选择已保留。这份请求不会再提交；请核对或再次取消。"
                            else "草稿和原提交已保留。未知请求可能仍在途，不会自动重发。", color = MaterialTheme.colorScheme.error)
                        if (draft.operationId != null && state.moodLedgerAvailable) {
                            if (!draft.cancelRequested) OutlinedButton(onClick = model::retryMoodOperation, enabled = !state.busy && state.moodLocalSaved) { Text(Shared.COPY_MOOD_RECOVERY_RETRY) }
                            OutlinedButton(onClick = { cancelConfirm = true }, enabled = !state.busy && state.moodLocalSaved) { Text(Shared.COPY_MOOD_RECOVERY_CANCEL) }
                            Text("取消只阻止这次尚未执行的请求，不会撤回已经保存或删除的记录。", style = MaterialTheme.typography.bodySmall)
                        }
                        if (draft.conflict && state.moodsLoaded) {
                            val current = state.moodEntries.find { it.date == draft.date }
                            Text(if (current == null) "刚读取的当前状态：这一天没有记录。"
                                else "刚读取的当前记录：\n${current.note.ifBlank { "感受位置 ${current.x}，精力位置 ${current.y}" }}")
                            OutlinedButton(onClick = model::rebaseMoodDraft, enabled = !state.busy) { Text("保留草稿，按刚读取的版本继续编辑") }
                        }
                    }
                    Button(onClick = model::saveMood, enabled = !state.busy && state.moodsLoaded && !draft.locked && draft.xChosen && draft.yChosen) { Text(Shared.COPY_MOOD_SAVE) }
                    if (draft.dirty && draft.operation == null) OutlinedButton(onClick = { discardConfirm = true }, enabled = !state.busy) { Text("放弃这份未提交草稿") }
                    if (draft.expectedUpdatedAt != null) {
                        OutlinedButton(onClick = { model.moodToChat()?.let(onToChat) }, enabled = !state.busy && state.moodsLoaded && !draft.locked && !draft.dirty) { Text(Shared.COPY_MOOD_TO_CHAT) }
                        Text(Shared.COPY_CHAT_DRAFT_DISCLOSURE, style = MaterialTheme.typography.bodySmall)
                        TextButton(onClick = { deleteConfirm = true }, enabled = !state.busy && state.moodsLoaded && !draft.locked && !draft.dirty) { Text("删除这一天的记录") }
                    }
                }
                Text("已留下的日子", style = MaterialTheme.typography.titleMedium)
                if (state.moodsLoaded && state.moodEntries.isEmpty()) Text("还没有心情记录。")
                state.moodEntries.take(historyLimit).forEach { record ->
                    OutlinedButton(onClick = { model.chooseMoodDate(record.date) }, modifier = Modifier.fillMaxWidth(), enabled = !state.busy && draft?.dirty != true && draft?.locked != true) {
                        Text(record.date + if (record.note.isBlank()) " · 自己选择的位置" else " · " + record.note)
                    }
                }
                if (state.moodEntries.size > historyLimit) TextButton(onClick = { historyLimit += 10 }) { Text("再看更早的记录") }
                OutlinedButton(onClick = model::closeMoods) { Text("关闭，草稿留在本机") }
            }
        }
    }
    if (chooseDate && draft != null) {
        val picker = rememberDatePickerState(initialSelectedDateMillis = LocalDate.parse(draft.date).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli())
        DatePickerDialog(onDismissRequest = { chooseDate = false }, confirmButton = {
            TextButton(onClick = { picker.selectedDateMillis?.let { model.chooseMoodDate(Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().toString()) }; chooseDate = false }) { Text("选择这一天") }
        }, dismissButton = { TextButton(onClick = { chooseDate = false }) { Text("取消") } }) { DatePicker(picker) }
    }
    if (cancelConfirm) AlertDialog(onDismissRequest = { cancelConfirm = false }, title = { Text(Shared.COPY_MOOD_RECOVERY_CANCEL + "？") },
        text = { Text("取消只阻止这次尚未执行的请求，不回滚已有记录。草稿保留，确认后不会再重试这个请求。") }, confirmButton = {
            TextButton(onClick = { cancelConfirm = false; model.cancelMoodOperation() }) { Text("确认取消这次提交") }
        }, dismissButton = { TextButton(onClick = { cancelConfirm = false }) { Text("保留原请求") } })
    if (deleteConfirm) AlertDialog(onDismissRequest = { deleteConfirm = false }, title = { Text("删除这一天的心情记录？") }, text = { Text("只删除这一天的记录。你手动带到聊天并发送过的文字仍在对话里。") }, confirmButton = {
        TextButton(onClick = { deleteConfirm = false; model.deleteMood() }) { Text("确认删除") }
    }, dismissButton = { TextButton(onClick = { deleteConfirm = false }) { Text("保留") } })
    if (discardConfirm) AlertDialog(onDismissRequest = { discardConfirm = false }, title = { Text("放弃未提交的草稿？") }, text = { Text("已经保存的服务端记录不受影响。") }, confirmButton = {
        TextButton(onClick = { discardConfirm = false; model.discardMoodDraft() }) { Text("放弃草稿") }
    }, dismissButton = { TextButton(onClick = { discardConfirm = false }) { Text("继续编辑") } })
}
