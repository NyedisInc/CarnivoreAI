/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ApprovalHead from './ApprovalHead.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { ApprovalDisplay } from './approvals-model';

setLocale('en');

const BASE: ApprovalDisplay = { verb: 'restart', object: 'session', name: 'build bot', tone: 'danger', consequences: [], detail: [] };
let handle: ReturnType<typeof mount> | null = null;

function draw(display: ApprovalDisplay): HTMLElement {
  document.body.innerHTML = '<div id="t"></div>';
  handle = mount(ApprovalHead, { target: document.getElementById('t')!, props: { id: 'act_1', display } });
  flushSync();
  return document.body;
}

afterEach(() => {
  if (handle) unmount(handle);
  handle = null;
});

describe('ApprovalHead in-use line', () => {
  test('in flight names every signal in the alert tone', () => {
    const body = draw({ ...BASE, in_use: { tone: 'alert', parts: [
      { key: 'agents', params: { count: '2' } }, { key: 'working', params: { source: 'registry' } }, { key: 'viewers', params: { count: '1' } } ] } });
    const line = body.querySelector('[data-approval-in-use]')!;
    expect(line.textContent).toBe('in use: 2 background agents running, working, registry reports a turn running, open in 1 window');
    expect(line.getAttribute('data-in-use-tone')).toBe('alert');
  });

  test('a stale working claim is a quiet note with its date', () => {
    const body = draw({ ...BASE, in_use: { tone: 'quiet', parts: [{ key: 'stale_working', params: { since: '2026-09-29', source: 'transcript' } }] } });
    const line = body.querySelector('[data-approval-in-use]')!;
    expect(line.textContent).toBe('note: claims working, only the transcript says so, no activity since 2026-09-29');
    expect(line.getAttribute('data-in-use-tone')).toBe('quiet');
  });

  test('no in-use block draws no line', () => {
    expect(draw(BASE).querySelector('[data-approval-in-use]')).toBeNull();
  });
});
