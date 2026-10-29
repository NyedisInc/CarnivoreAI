/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async () => ({}),
}));

import ComputerRow from './ComputerRow.svelte';
import FirstRunJoin from '../first-run/FirstRunJoin.svelte';
import { HELPER_LINE } from '../first-run/join-api';
import { setLocale, t } from '../i18n/index.svelte';
import type { ComputerEntry } from './computers-api';

setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];
afterEach(() => {
  mounted.splice(0).forEach((m) => unmount(m));
  document.body.innerHTML = '';
});

function entry(dial: ComputerEntry['dial'], over: Partial<ComputerEntry> = {}): ComputerEntry {
  return { install_id: 'hosta1', label: 'hosta', host_key: null, transport: 'tls', role: 'member', state: 'connected', direction: 'both', fid: 'f',
    fid_short: 'abc123', cert_sha256: null, joined_at: null, last_link_at: null, possible_duplicate_of: null, dial, ...over };
}

function row(computer: ComputerEntry): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(ComputerRow, { target, props: { computer, nowMs: Date.now(), busy: false } }));
  flushSync();
  return target;
}

describe('a computers row shows main\'s dial state', () => {
  test('linked shows no dial note', () => {
    expect(row(entry({ state: 'linked', since: null })).querySelector('[data-cmp="dial"]')).toBeNull();
  });
  test('no dial (ssh pair) shows no dial note', () => {
    expect(row(entry(null, { transport: 'ssh' })).querySelector('[data-cmp="dial"]')).toBeNull();
  });
  test.each([
    ['dialing', 'computers.dial.dialing'],
    ['local_network_blocked', 'computers.dial.local_network_blocked'],
    ['refused', 'computers.dial.refused'],
    ['cert_mismatch', 'computers.dial.cert_mismatch'],
  ] as const)('%s renders its catalog sentence', (state, key) => {
    const note = row(entry({ state, since: null })).querySelector('[data-cmp="dial"]') as HTMLElement;
    expect(note.textContent).toBe(t(key, { label: 'hosta' }));
    expect(note.textContent).not.toBe(key);
  });
  test('unreachable names the time, and the firewall only when its join reported it', () => {
    const since = '2026-10-11T10:05:00Z';
    const plain = row(entry({ state: 'unreachable', since })).querySelector('[data-cmp="dial"]') as HTMLElement;
    expect(plain.textContent).toContain("can't reach hosta since ");
    expect(plain.textContent).not.toContain('firewall');
    document.body.innerHTML = '';
    const walled = row(entry({ state: 'unreachable', since }, { firewall_on: true })).querySelector('[data-cmp="dial"]') as HTMLElement;
    expect(walled.textContent).toContain(t('computers.dial.firewall', { label: 'hosta' }));
  });
  test('unreachable with no time says no "since"', () => {
    const note = row(entry({ state: 'unreachable', since: null })).querySelector('[data-cmp="dial"]') as HTMLElement;
    expect(note.textContent).toBe(t('computers.dial.unreachable_untimed', { label: 'hosta' }));
    expect(note.textContent).not.toContain('since');
  });
});

describe('the first-run joining phase', () => {
  function join(state: string, error: string | null): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(FirstRunJoin, { target, props: { start: 'resume', onBack: () => undefined,
      resume: { state, error, main_label: null, candidates: [] } as never } }));
    flushSync();
    return target;
  }
  test('waiting_relay renders the Terminal copy', () => {
    const view = join('waiting_relay', null);
    expect(view.querySelector('[data-first-run="joining"]')?.textContent).toBe(t('first_run.join.step.waiting_relay'));
    expect(t('first_run.join.step.waiting_relay')).toContain('terminal');
  });
  test('a helper that did not start shows the paste line', () => {
    const view = join('failed', 'helper_not_started');
    expect(view.querySelector('[data-first-run-error="helper_not_started"]')?.textContent).toBe(t('first_run.join.error.helper_not_started'));
    expect(view.textContent).toContain(HELPER_LINE);
  });
});
