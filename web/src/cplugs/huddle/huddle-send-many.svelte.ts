import { ApiError, authFetch, t } from '../sdk';
import { huddle, refreshLists } from './huddle.svelte';
import {
  AGGREGATE, refusalCode, serverKey, type HuddleItem, type TaskManagerListRow, type TaskManagerSession, type SendChoice,
} from './huddle-model';
import { START_NEW, startSessionFor, STOP, waitUntilReady, type StartFailure } from './task-manager-send-start';
import { applyQueue, type SendQueueState } from './task-manager-send-queue.svelte';

export interface SendResult {
  list: string;
  status: 'sent' | 'queued' | 'nothing' | 'no_session' | 'refused' | 'held';
  target?: string;
  label?: string | null;
  code?: string;
  reason?: string;
  sessions?: TaskManagerSession[];
}

export interface SendAsk {
  list: string;
  name: string;
  sessions: TaskManagerSession[];
  items: { id: number; text: string }[];
}

export const sendPicks = $state<{
  picks: Record<string, string>;
  /* could not */
  asking: SendAsk[] | null;
  choices: Record<string, SendChoice>;
  reopen: SendAsk[] | null;
}>({ picks: {}, asking: null, choices: {}, reopen: null });

export function listsToSend(selected: string, lists: readonly Pick<TaskManagerListRow, 'key' | 'untold'>[]): string[] {
  if (selected !== AGGREGATE) return [serverKey(selected)];
  return lists.filter((row) => row.untold).map((row) => row.key);
}

export function waitingToSend(selected: string, lists: readonly Pick<TaskManagerListRow, 'key' | 'waiting_to_send'>[]): number {
  const covered = selected === AGGREGATE ? lists : lists.filter((row) => row.key === serverKey(selected));
  return covered.reduce((sum, row) => sum + (row.waiting_to_send ?? 0), 0);
}

export function listName(key: string, lists: readonly Pick<TaskManagerListRow, 'key' | 'name'>[]): string {
  return lists.find((row) => row.key === key)?.name || t('cplug.huddle.list.shared');
}

function refusedWords(result: SendResult): string {
  const key = `cplug.huddle.refused.${result.code ?? ''}`;
  const text = t(key);
  return text === key ? (result.reason || result.code || t('cplug.huddle.refused.failed')) : text;
}

export function sendNotice(results: readonly SendResult[], lists: readonly Pick<TaskManagerListRow, 'key' | 'name'>[]): string {
  const parts: string[] = [];
  const asked = results.filter((r) => r.status === 'no_session').map((r) => listName(r.list, lists));
  if (asked.length) parts.push(t('cplug.huddle.send.ask_names', { names: asked.join(', ') }));
  const asleep = results.filter((r) => r.status === 'refused' && r.code === WAKE_FAILED).map((r) => listName(r.list, lists));
  if (asleep.length) parts.push(t('cplug.huddle.send.wake_failed', { names: asleep.join(', ') }));
  return parts.join(' ');
}

const WAKE_FAILED = 'wake_failed';

function itemsOf(list: string): HuddleItem[] {
  if (huddle.body?.list === list) return huddle.body.items;
  return huddle.groups?.find((g) => g.list === list)?.items ?? [];
}

export function askFor(result: SendResult, items: readonly HuddleItem[], name: string): SendAsk {
  const open = items.filter((i) => !i.deleted && i.state !== 'done');
  const waiting = open.filter((i) => (i.status as string | undefined) === 'waiting_to_send');
  return { list: result.list, name, sessions: result.sessions ?? [], items: (waiting.length ? waiting : open).map((i) => ({ id: i.id, text: i.text })) };
}

export async function sendLists(all: readonly string[], options: { queue?: boolean } = {}): Promise<boolean> {
  huddle.notice = '';
  sendPicks.reopen = null;
  if (!all.length) {
    huddle.notice = t('cplug.huddle.send.nothing');
    return false;
  }
  const stopped = all.filter((k) => sendPicks.picks[k] === STOP);
  const starting = all.filter((k) => sendPicks.picks[k] === START_NEW);
  const keys = all.filter((k) => !stopped.includes(k) && !starting.includes(k));
  for (const k of stopped) pickFor(k, null);
  const started = await Promise.all(starting.map((k) => startAndSend(k)));
  if (!keys.length) {
    huddle.notice = [stopNotice(stopped), ...started.map((r) => r.notice)].filter(Boolean).join(' ');
    return started.length > 0 && started.every((r) => r.ok);
  }
  const targets = Object.fromEntries(keys.filter((k) => sendPicks.picks[k]).map((k) => [k, sendPicks.picks[k] as string]));
  const queue = options.queue === true && !Object.keys(targets).length;
  let results: SendResult[];
  try {
    const body = await authFetch<{ results?: SendResult[]; queue?: SendQueueState } | null>('/cplugs/huddle/send', {
      method: 'POST', body: JSON.stringify(queue ? { lists: keys, queue: true } : { lists: keys, targets }),
    });
    results = Array.isArray(body?.results) ? body.results : [];
    if (body?.queue) applyQueue(body.queue);
  } catch (error) {
    const code = error instanceof ApiError ? refusalCode(error.payload) : null;
    huddle.notice = t('cplug.huddle.send.not_sent', {
      name: keys.map((k) => listName(k, huddle.lists)).join(', '),
      reason: refusedWords({ list: '', status: 'refused', code: code ?? undefined, reason: error instanceof Error ? error.message : '' }),
    });
    return false;
  }
  huddle.notice = [sendNotice(results, huddle.lists), stopNotice(stopped), ...started.map((r) => r.notice)].filter(Boolean).join(' ');
  await settle(results);
  return results.length === keys.length && results.every((r) => r.status === 'sent' || r.status === 'queued') && started.every((r) => r.ok);
}

async function settle(results: readonly SendResult[]): Promise<void> {
  const unplaced = results.filter((r) => r.status === 'no_session');
  sendPicks.asking = unplaced.length ? unplaced.map((r) => askFor(r, itemsOf(r.list), listName(r.list, huddle.lists))) : null;
  sendPicks.reopen = sendPicks.asking;
  if (results.some((r) => r.status === 'sent')) await refreshLists();
}

export async function flushQueued(keys: readonly string[]): Promise<boolean> {
  huddle.notice = '';
  sendPicks.reopen = null;
  try {
    const body = await authFetch<{ results?: SendResult[]; queue?: SendQueueState } | null>('/cplugs/huddle/send-queue/flush', {
      method: 'POST', body: JSON.stringify({ lists: keys }),
    });
    const results = Array.isArray(body?.results) ? body.results : [];
    if (body?.queue) applyQueue(body.queue);
    huddle.notice = sendNotice(results, huddle.lists);
    await settle(results);
    return results.every((r) => r.status === 'sent' || r.status === 'nothing');
  } catch (error) {
    const code = error instanceof ApiError ? refusalCode(error.payload) : null;
    huddle.notice = t('cplug.huddle.send.not_sent', {
      name: keys.map((k) => listName(k, huddle.lists)).join(', '),
      reason: refusedWords({ list: '', status: 'refused', code: code ?? undefined, reason: error instanceof Error ? error.message : '' }),
    });
    return false;
  }
}

function stopNotice(stopped: readonly string[]): string {
  return stopped.length ? t('cplug.huddle.send.stopped', { name: stopped.map((k) => listName(k, huddle.lists)).join(', ') }) : '';
}

function startWords(failure: StartFailure): string {
  return t(`cplug.huddle.send.start_${failure}`);
}

export async function startAndSend(list: string): Promise<{ ok: boolean; notice: string }> {
  const name = listName(list, huddle.lists);
  const start = await startSessionFor(list);
  if (!start.session) return { ok: false, notice: t('cplug.huddle.send.start_failed', { name, reason: startWords(start.failure ?? 'create_failed') }) };
  pickFor(list, start.session);
  if (!(await waitUntilReady(list, start.session))) {
    return { ok: false, notice: t('cplug.huddle.send.start_failed', { name, reason: startWords('not_ready') }) };
  }
  try {
    const body = await authFetch<{ results?: SendResult[] } | null>('/cplugs/huddle/send', {
      method: 'POST', body: JSON.stringify({ lists: [list], targets: { [list]: start.session } }),
    });
    const result = body?.results?.[0];
    if (result?.status === 'sent' && result.target === start.session) {
      await refreshLists();
      return { ok: true, notice: t('cplug.huddle.send.started', { name }) };
    }
    return { ok: false, notice: sendNotice(result ? [result] : [], huddle.lists) };
  } catch (error) {
    console.warn('huddle: could not tell the new session', error);
    return { ok: false, notice: t('cplug.huddle.send.start_failed', { name, reason: startWords('not_ready') }) };
  }
}

export function reopenPick(): void {
  if (sendPicks.reopen?.length) sendPicks.asking = sendPicks.reopen;
}

export function pickFor(list: string, id: string | null): void {
  const rest = Object.fromEntries(Object.entries(sendPicks.picks).filter(([k]) => k !== list));
  sendPicks.picks = id ? { ...rest, [list]: id } : rest;
}

export async function readChoice(list: string): Promise<SendChoice> {
  try {
    const found = await authFetch<Partial<SendChoice> | null>(`/cplugs/huddle/lists/${encodeURIComponent(list)}/sessions`);
    return keepChoice(list, found);
  } catch (error) {
    console.warn('huddle: could not read who tell claude may message', error);
    return { sessions: [], default: null, reason: 'pick' };
  }
}

export function keepChoice(list: string, found: Partial<SendChoice> | null): SendChoice {
  const choice: SendChoice = { sessions: Array.isArray(found?.sessions) ? found.sessions : [], default: found?.default ?? null, reason: found?.reason ?? 'pick' };
  sendPicks.choices = { ...sendPicks.choices, [list]: choice };
  return choice;
}

const choiceReads = new Map<string, Promise<SendChoice>>();

export function ensureChoice(list: string): Promise<SendChoice> {
  const known = sendPicks.choices[list];
  if (known) return Promise.resolve(known);
  let pending = choiceReads.get(list);
  if (!pending) {
    pending = readChoice(list).finally(() => choiceReads.delete(list));
    choiceReads.set(list, pending);
  }
  return pending;
}

export function needsPicker(choice: SendChoice | undefined): boolean {
  return !!choice && choice.default === null;
}

export function resetSendPicks(): void {
  sendPicks.picks = {};
  sendPicks.asking = null;
  sendPicks.reopen = null;
  sendPicks.choices = {};
  choiceReads.clear();
}
