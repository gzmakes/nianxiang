const STATES = new Set(['quiet','listening','thinking','responding','failed']);
const COMMANDS = new Set(['chat','today','memory','apps','new-memory','settings','tasks','draft']);
function normalizeState(value) { return STATES.has(value) ? value : 'quiet'; }
function validCommand(value) {
  if (!value || !COMMANDS.has(value.action)) return null;
  if (value.action === 'draft') {
    if (typeof value.text !== 'string' || !value.text.trim() || value.text.length > 4000) return null;
    return {action:'draft',text:value.text.trim()};
  }
  return {action:value.action};
}
function tomorrowAtNine(now = new Date()) {
  const date = new Date(now); date.setDate(date.getDate()+1);date.setHours(9,0,0,0);return date.toISOString();
}
function effectiveState(state, pausedUntil, now = Date.now()) {
  return Date.parse(pausedUntil || '') > now ? 'quiet' : normalizeState(state);
}
function stateLabel(state, pausedUntil, now = Date.now()) {
  if (Date.parse(pausedUntil || '') > now) return '先不打扰 · 已暂停桌面提示';
  return {quiet:'安静陪着',listening:'在听你说',thinking:'正在想一想',responding:'正在回应',failed:'需要核对一件事'}[normalizeState(state)];
}
module.exports={normalizeState,validCommand,tomorrowAtNine,effectiveState,stateLabel};
