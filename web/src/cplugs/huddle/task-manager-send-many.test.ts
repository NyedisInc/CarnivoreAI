/** @vitest-environment jsdom */
import { describe, expect, test } from 'vitest';
import { askFor, listsToSend, reopenPick, resetSendPicks, sendNotice, sendPicks } from './huddle-send-many.svelte';
import type { HuddleItem } from './huddle-model';

const rows = [
  { key: 'all', name: null, untold: false, waiting_to_send: 0 },
  { key: '12', name: 'carnivore', untold: true, waiting_to_send: 0 },
  { key: '18', name: 'CloudeCode', untold: false, waiting_to_send: 2 },
  { key: '20', name: 'quiet' },
];

const item = (id: number, over: Partial<HuddleItem> = {}): HuddleItem => ({
  id, list: '18', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '', revision: 1,
  created_seq: id, seq: id, deleted: false, thread: [], ...over,
});

describe('which lists a press tells', () => {
  test('a list on screen is told alone; all projects tells only lists with untold changes, never one that merely has told items waiting to be read', () => {
    expect(listsToSend('12', rows)).toEqual(['12']);
    expect(listsToSend('20', rows)).toEqual(['20']);
    expect(listsToSend('aggregate', rows)).toEqual(['12']);
    expect(listsToSend('aggregate', [{ key: '12' }])).toEqual([]);
  });
});

describe('the notice', () => {
  test('a sent tell says nothing; only the lists waiting on a pick are counted', () => {
    expect(sendNotice([{ list: '12', status: 'sent', label: 'agent a' }, { list: '18', status: 'sent', label: 'agent b' }], rows))
      .toBe('');
    expect(sendNotice([{ list: '12', status: 'refused', label: 'agent a', code: 'x_unknown', reason: 'a dialog is open' }], rows))
      .toBe('');
    expect(sendNotice([{ list: '12', status: 'held', label: 'agent a', code: 'pane_dialog_open' }], rows)).toBe('');
    expect(sendNotice([{ list: '12', status: 'no_session', sessions: [] }, { list: '18', status: 'no_session', sessions: [] }], rows))
      .toBe('pick a session for carnivore, CloudeCode.');
    expect(sendNotice([{ list: '12', status: 'refused', code: 'wake_failed' }], rows))
      .toBe('carnivore is asleep and did not wake; its changes are still waiting to send.');
    expect(sendNotice([], rows)).toBe('');
  });
});

describe('the pop-up', () => {
  test('a list with no session shows its items waiting to send (else its unchecked items) and its candidates', () => {
    const items = [item(1, { status: 'waiting_to_send' }), item(2, { status: 'working' }), item(3, { state: 'done' })];
    const sessions = [{ id: 's', label: 'a', tmux_session: null, project: null, activity_status: null }];
    expect(askFor({ list: '18', status: 'no_session', sessions }, items, 'CloudeCode'))
      .toEqual({ list: '18', name: 'CloudeCode', sessions, items: [{ id: 1, text: 'item 1' }] });
    expect(askFor({ list: '18', status: 'no_session' }, [item(2, { status: 'working' })], 'x').items).toEqual([{ id: 2, text: 'item 2' }]);
  });
});

describe('the notice reopens the pick pop-up', () => {
  test('a click puts back the same lists with their items; nothing to reopen does nothing', () => {
    resetSendPicks();
    reopenPick();
    expect(sendPicks.asking).toBeNull();
    const ask = { list: '12', name: 'carnivore', sessions: [], items: [{ id: 1, text: 'item 1' }] };
    sendPicks.reopen = [ask];
    reopenPick();
    expect(sendPicks.asking).toEqual([ask]);
    resetSendPicks();
  });
});
