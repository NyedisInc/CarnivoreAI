
'use strict';

const path = require('path');

const KINDS = Object.freeze(['yesno', 'choice', 'permission', 'file', 'link', 'image', 'video', 'finished', 'died', 'update', 'appupdate', 'swarm', 'crosstalk', 'signin', 'notice']);
const SOUNDS = Object.freeze(['ask', 'done', 'alarm', 'soft']);
const ASK_KINDS = Object.freeze(['yesno', 'choice', 'permission', 'swarm']);
const CORNER_SET = Object.freeze(['permission', 'choice', 'image', 'video', 'finished', 'died', 'swarm']);
const CORNER_HIDE_MS = 15000;
const MAX_REPLY = 2000;
const ACTION_CAP = null;
const OPEN_ACTIONS = Object.freeze(['open', 'open_file', 'save_file', 'play', 'save', 'sign_in']);
const LINK_ACTIONS = Object.freeze(['open_link', 'copy_link']);
const ROUTE_ACTIONS = Object.freeze(['reopen', 'install', 'restart_agents']);
const PICK_ACTION = /^pick\.[1-9]$/;
const TEXT_ACTIONS = Object.freeze(['reply', 'answer']);
const DIALOG_KINDS = Object.freeze(['yesno', 'choice', 'permission']);

function iconPath(kind) {
  return path.join(__dirname, 'icons', `${KINDS.includes(kind) ? kind : 'notice'}.png`);
}

function soundOptions(snd, lv) {
  if (lv === 'p' || snd === 'none') return { silent: true };
  if (SOUNDS.includes(snd)) return { silent: false, sound: `carnivore-${snd}` };
  return { silent: false };
}

function cornerWanted({ kind, lv, corner }) {
  if (lv === 'p' || corner === false) return false;
  return lv === 't' || CORNER_SET.includes(kind);
}

function sortActions(acts) {
  const buttons = [];
  const offered = [];
  let replyLabel = null;
  let replyAction = null;
  for (const pair of Array.isArray(acts) ? acts : []) {
    if (!Array.isArray(pair) || typeof pair[0] !== 'string') continue;
    const id = pair[0];
    const label = typeof pair[1] === 'string' && pair[1] ? pair[1].slice(0, 40) : id;
    if (TEXT_ACTIONS.includes(id)) {
      replyLabel = label;
      replyAction = id;
      offered.push([id, label]);
    } else if (id === 'later' || ROUTE_ACTIONS.includes(id) || PICK_ACTION.test(id) || OPEN_ACTIONS.includes(id) || LINK_ACTIONS.includes(id)) {
      buttons.push({ id, label });
      offered.push([id, label]);
    }
  }
  return { buttons: ACTION_CAP === null ? buttons : buttons.slice(0, ACTION_CAP), replyLabel, replyAction, offered };
}

function planFromCard({ response, desktopOn, corner, silent }) {
  const kind = KINDS.includes(response.kind) ? response.kind : 'notice';
  const lv = ['p', 'a', 't'].includes(response.lv) ? response.lv : 'a';
  const sound = soundOptions(response.snd, lv);
  const { buttons, replyLabel, replyAction, offered } = sortActions(response.acts);
  const wantCorner = cornerWanted({ kind, lv, corner });
  const asks = ASK_KINDS.includes(kind);
  return {
    post: desktopOn !== false, kind, type: String(response.type || ''), title: String(response.title || ''), subtitle: String(response.sub || ''),
    body: String(response.body || ''), icon: iconPath(kind), silent: sound.silent || silent === true, sound: sound.sound,
    item: /^\d+$/.test(String(response.item || '')) ? String(response.item) : '', // from the owner
    buttons, reply: replyLabel, replyAction, corner: wantCorner, autoHideMs: asks ? 0 : CORNER_HIDE_MS,
    shown: { kind, card: response.card || null, acts: DIALOG_KINDS.includes(kind) ? (Array.isArray(response.acts) ? response.acts : []) : offered, body: String(response.body || '') },
  };
}

function bannerOptions(plan, extra) {
  const options = { title: plan.title.slice(0, 200), body: plan.body.slice(0, 1000), icon: extra.image(plan.icon), silent: true };
  if (plan.subtitle) options.subtitle = plan.subtitle.slice(0, 200);
  if (extra.id) options.id = extra.id;
  if (extra.groupId) options.groupId = extra.groupId;
  if (plan.buttons.length) options.actions = plan.buttons.map((b) => ({ type: 'button', text: b.label }));
  if (plan.reply) { options.hasReply = true; options.replyPlaceholder = plan.reply; }
  return options;
}

module.exports = { KINDS, SOUNDS, ASK_KINDS, DIALOG_KINDS, ROUTE_ACTIONS, PICK_ACTION, CORNER_SET, CORNER_HIDE_MS, MAX_REPLY, ACTION_CAP, iconPath, soundOptions, cornerWanted, sortActions, planFromCard, bannerOptions };
