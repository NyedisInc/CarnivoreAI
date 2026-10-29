// could not

'use strict';

const crypto = require('crypto');
const strings = require('../tray-menu/strings');

const VISIBLE_ACTION_CAP = null;
const MAX_REPLY = 2000;
const MAX_BODY = 200;
const MAX_NAME = 60;
const SESSION_ID_PATTERN = /^[A-Za-z0-9_:.-]{0,200}$/;
const HEX64 = /^[0-9a-f]{64}$/;
const ID_SEPARATOR = '|';

const KIND_PLANS = Object.freeze({
  permission: { title: 'desktop.banner.title_permission', body: 'command' },
  codex_approval: { title: 'desktop.banner.title_permission', body: 'command' },
  plan_approval: { title: 'desktop.banner.title_plan', body: 'question' },
  folder_trust: { title: 'desktop.banner.title_trust', body: 'question' },
  ask_user_question: { title: 'desktop.banner.title_question', body: 'question' },
  other: { title: 'desktop.banner.title_other', body: 'question' },
  unreadable: { title: 'desktop.banner.title_other', body: 'question' },
});
const UNKNOWN_KIND = Object.freeze({ title: 'desktop.banner.title_other', body: 'question' });

function bannersDeliverable({ prefOn, permission, apiPresent }) {
  if (!apiPresent) return { ok: false, reason: 'server_unreachable' };
  if (prefOn !== true) return { ok: false, reason: 'off' };
  if (permission === 'denied') return { ok: false, reason: 'permission_denied' };
  if (permission === 'not_asked') return { ok: false, reason: 'permission_not_asked' };
  if (permission !== 'unknown' && permission !== 'allowed') return { ok: false, reason: 'permission_unreadable' };
  return { ok: true, reason: 'ok' };
}

function encodeActionId(sessionId, fingerprint, step, index) {
  if (typeof sessionId !== 'string' || !SESSION_ID_PATTERN.test(sessionId)) return null;
  if (typeof fingerprint !== 'string' || !HEX64.test(fingerprint)) return null;
  if (!Number.isInteger(step) || step < 0 || !Number.isInteger(index) || index < 0) return null;
  return [sessionId, fingerprint, step, index].join(ID_SEPARATOR);
}

function decodeActionId(id) {
  if (typeof id !== 'string') return null;
  const parts = id.split(ID_SEPARATOR);
  if (parts.length !== 4) return null;
  const [sessionId, fingerprint, step, index] = parts;
  if (!SESSION_ID_PATTERN.test(sessionId) || !HEX64.test(fingerprint) || !/^\d{1,3}$/.test(step) || !/^\d{1,3}$/.test(index)) return null;
  return { sessionId, fingerprint, step: Number(step), index: Number(index) };
}

function isMatchedMultiAsk(item) {
  return item.kind === 'ask_user_question' && item.questions_state === 'matched' && Array.isArray(item.questions)
    && item.questions.length > 1 && HEX64.test(String(item.questions_fingerprint || ''));
}

function keyFingerprint(item) {
  if (isMatchedMultiAsk(item)) return item.questions_fingerprint;
  if (HEX64.test(String(item.fingerprint || ''))) return item.fingerprint;
  return crypto.createHash('sha256').update(String(item.id || '')).digest('hex');
}

function itemKey(item) {
  return `${item.session_id}${ID_SEPARATOR}${keyFingerprint(item)}`;
}

function classify(item, step) {
  if (item.source !== 'dialog') return { mode: 'open_only', reason: 'not_a_dialog', labels: [] };
  if (item.kind === 'unreadable') return { mode: 'open_only', reason: 'unreadable', labels: [] };
  if (item.kind === 'ask_user_question' && !isMatchedMultiAsk(item) && Number(item.question_total) > 1) {
    return { mode: 'open_only', reason: 'questions_unmatched', labels: [] };
  }
  if (isMatchedMultiAsk(item)) {
    if (item.questions.some((q) => !q || q.multi_select === true)) return { mode: 'open_only', reason: 'multi_select', labels: [] };
    const question = item.questions[step];
    const labels = question && Array.isArray(question.options) ? question.options.map((o) => (o && o.label)) : [];
    return labels.length ? { mode: 'ask', reason: 'ok', labels } : { mode: 'open_only', reason: 'no_options', labels: [] };
  }
  if (item.multi_select === true) return { mode: 'open_only', reason: 'multi_select', labels: [] };
  const labels = Array.isArray(item.options) ? item.options : [];
  if (labels.length) return { mode: 'single', reason: 'ok', labels };
  if (item.has_other === true) return { mode: 'reply', reason: 'ok', labels: [] };
  return { mode: 'open_only', reason: 'no_options', labels: [] };
}

function optionLabel(item, step, optionIndex) {
  if (!item || typeof item !== 'object' || !Number.isInteger(optionIndex) || optionIndex < 0) return null;
  const label = classify(item, step).labels[optionIndex];
  return typeof label === 'string' && label !== '' ? label : null;
}

function notificationId(sessionId, fingerprint, step) {
  const full = encodeActionId(sessionId, fingerprint, step, 0);
  return full === null ? null : full.slice(0, full.lastIndexOf(ID_SEPARATOR));
}

function decodeNotificationId(id) {
  if (typeof id !== 'string') return null;
  const parts = decodeActionId(`${id}${ID_SEPARATOR}0`);
  return parts ? { sessionId: parts.sessionId, fingerprint: parts.fingerprint, step: parts.step } : null;
}

function threadFor(item) {
  if (isMatchedMultiAsk(item) || (item.kind === 'ask_user_question' && Number(item.question_total) > 1)) return null;
  return item.session_id;
}

/* label: ' */
function applyCap(buttons, cap, t) {
  if (!Number.isInteger(cap) || cap < 1 || buttons.length <= cap) return buttons;
  return [...buttons.slice(0, cap - 1), { label: t('desktop.banner.more'), kind: 'open_app', optionIndex: null }];
}

function commandBody(item, hide, t) {
  const summary = typeof item.summary === 'string' ? item.summary : '';
  if (!hide) return strings.clip(summary || item.question, MAX_BODY);
  const tool = strings.clip(summary.split(':')[0], MAX_NAME);
  return [tool, t('desktop.banner.body_hidden_command')].filter(Boolean).join('\n');
}

function planFor(item, opts) {
  const { t } = opts;
  const step = opts.step || 0;
  const cap = opts.cap === undefined ? VISIBLE_ACTION_CAP : opts.cap;
  const none = { post: false, mode: 'open_only', title: '', body: '', step, total: 1, buttons: [] };
  if (!item || typeof item !== 'object') return { ...none, reason: 'not_an_item' };
  if ((item.host || 'local') !== 'local') return { ...none, reason: 'peer' };
  if (typeof item.session_id !== 'string' || !SESSION_ID_PATTERN.test(item.session_id)) return { ...none, reason: 'bad_session_id' };
  const kindPlan = KIND_PLANS[item.kind] || UNKNOWN_KIND;
  const how = classify(item, step);
  const name = strings.clip(item.session_name || item.tmux_session || item.project || item.session_id || 'carnivore', MAX_NAME);
  const title = t(kindPlan.title, { name });
  if (how.mode === 'open_only') {
    const key = how.reason === 'multi_select' ? 'desktop.banner.body_multi_select' : 'desktop.banner.body_open_only';
    return { post: true, reason: how.reason, mode: 'open_only', title, body: t(key), step, total: 1,
      id: notificationId(item.session_id, keyFingerprint(item), step), groupId: threadFor(item),
      buttons: [{ label: t('desktop.banner.open_app'), kind: 'open_app', optionIndex: null }] };
  }
  let body;
  let total = 1;
  if (how.mode === 'ask') {
    total = item.questions.length;
    body = [t('desktop.banner.question_of', { n: step + 1, total }), strings.clip(item.questions[step].question, MAX_BODY)].join('\n');
  } else if (kindPlan.body === 'command') {
    body = commandBody(item, opts.hideCommand === true, t);
  } else {
    body = strings.clip(item.question, MAX_BODY);
  }
  const fingerprint = keyFingerprint(item);
  const id = notificationId(item.session_id, fingerprint, step);
  const groupId = threadFor(item);
  const answers = how.labels.map((label, i) => ({ label: strings.clip(label) || String(i + 1), kind: 'answer', optionIndex: i }));
  const plan = { post: true, reason: 'ok', mode: how.mode, title, body, step, total, buttons: applyCap(answers, cap, t), id, groupId };
  if (how.mode === 'reply') { plan.reply = true; plan.replyPlaceholder = t('desktop.banner.reply_placeholder'); }
  return plan;
}

module.exports = {
  VISIBLE_ACTION_CAP, MAX_REPLY, KIND_PLANS, notificationId, decodeNotificationId, threadFor, SESSION_ID_PATTERN, bannersDeliverable, encodeActionId, decodeActionId, itemKey, keyFingerprint,
  isMatchedMultiAsk, optionLabel, applyCap, planFor,
};
