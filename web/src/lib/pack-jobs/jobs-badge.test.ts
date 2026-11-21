/** @vitest-environment jsdom */
import { describe, expect, it, vi } from 'vitest';
import { BADGE_ORDER, badgeSlotPlan } from '../session-badges';
import type { JobView } from './jobs-api';
import { durationWords, isLive, whenWords } from './jobs-format';
import { jobsBadges } from './jobs-badge';
import { JobsStore } from './jobs-store.svelte';

function job(id: string, extra: Partial<JobView> = {}): JobView {
  return {
    id, side: 'caller', state: 'running', body: 'command', project_uid: 'p1', project_name: 'proj', folder: null, command: `cmd ${id}`, kind: null,
    task_head: null, agent_type: null, computer: 'tower', reason: null, exit_code: null, output_tail: null, applied: [], deleted: [], clashes: [], ref: null,
    error_code: null, error_detail: null, question: null, question_kind: null, result_text: null, account_label: null, usage: null,
    created_at: 1000, started_at: 1000, ended_at: null, caller_session: 'u1', worker_session_uuid: null, peer_install_id: null, worker_listing_uuid: null, ...extra,
  };
}

function storeWith(...rows: JobView[]): JobsStore {
  const store = new JobsStore({ api: { list: async () => ({ jobs: [], next_before: null }), stop: async () => ({}) }, subscribe: () => null, poll: () => () => {}, repaint: () => {} });
  rows.forEach((r, i) => store.apply({ seq: i + 1, job: r }));
  return store;
}

describe('the jobs badge', () => {
  it('counts the live jobs of the row whose wrapper session_uuid matches, one or many', () => {
    const one = jobsBadges({ session_uuid: 'u1', host_key: 'local' }, storeWith(job('a')));
    expect(one).toHaveLength(1);
    expect(one[0]).toMatchObject({ kind: 'jobs', text: '1 job' });
    expect(one[0]!.title).toContain('tower: cmd a (running)');
    const three = jobsBadges({ session_uuid: 'u1' }, storeWith(job('a'), job('b'), job('c')));
    expect(three[0]!.text).toBe('3 jobs');
    expect(three[0]!.title.split('\n')).toHaveLength(3);
  });

  it('reads the wrapper level only: a fixture with the uuid only at .session gets no badge', () => {
    const store = storeWith(job('a'));
    expect(jobsBadges({ session: { session_uuid: 'u1', id: 'ses_1' } }, store)).toEqual([]);
    expect(jobsBadges({ session_uuid: 'u1' }, store)).toHaveLength(1);
  });

  it('draws nothing on a paired computer\u2019s row, for a host row, a finished job or another session', () => {
    const store = storeWith(job('a'), job('h', { side: 'host', caller_session: null, state: 'running' }), job('d', { state: 'done', ended_at: 1100 }));
    expect(jobsBadges({ session_uuid: 'u1', host_key: 'peer-studio' }, store)).toEqual([]);
    expect(jobsBadges({ session_uuid: 'u2' }, store)).toEqual([]);
    expect(jobsBadges({ session_uuid: 'u1' }, store)[0]!.text).toBe('1 job');
    expect(jobsBadges({ session_uuid: 'u1' }, storeWith(job('d', { state: 'done', ended_at: 1100 })))).toEqual([]);
    expect(jobsBadges({}, store)).toEqual([]);
  });

  it('is warn while any job waits on a question, and a click narrows the tab to this session', () => {
    const store = storeWith(job('a'), job('b', { state: 'question', question: 'which?' }));
    const badge = jobsBadges({ session_uuid: 'u1' }, store)[0]!;
    expect(badge.tone).toBe('warn');
    expect(jobsBadges({ session_uuid: 'u1' }, storeWith(job('a')))[0]!.tone).toBeUndefined();
    const setCaller = vi.spyOn(store, 'setCaller');
    badge.activate?.(new MouseEvent('click'));
    expect(setCaller).toHaveBeenCalledWith('u1');
    expect(store.caller).toBe('u1');
  });

  it('is the last kind of the slot, registered with a cap of one', () => {
    expect(BADGE_ORDER[BADGE_ORDER.length - 1]).toBe('jobs');
    expect(badgeSlotPlan({ session_uuid: 'nobody' })?.items.filter((i) => i.kind === 'jobs') ?? []).toEqual([]);
  });
});

describe('the time words', () => {
  it('say ran 4m 12s for an ended job and running since for a live one, and know the refused state', () => {
    expect(durationWords(252)).toBe('4m 12s');
    expect(durationWords(12)).toBe('12s');
    expect(durationWords(3780)).toBe('1h 3m');
    expect(whenWords(job('a', { state: 'done', started_at: 1000, ended_at: 1252 }))).toBe('ran 4m 12s');
    expect(whenWords(job('a'))).toMatch(/^running since \d\d:\d\d$/);
    expect(isLive(job('r', { state: 'refused' }))).toBe(false);
    expect(isLive(job('h', { side: 'host', state: 'parked' }))).toBe(true);
    expect(isLive(job('h', { side: 'host', state: 'exited' }))).toBe(false);
  });
});
