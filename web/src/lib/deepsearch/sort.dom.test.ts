/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

(HTMLElement.prototype as { showPopover?: () => void }).showPopover ??= () => {};
(HTMLElement.prototype as { hidePopover?: () => void }).hidePopover ??= () => {};

const { default: DeepSearchResults } = await import('./DeepSearchResults.svelte');
const { DeepSearchController, DEBOUNCE_MS } = await import('./deepsearch.svelte');
const { readAnswer } = await import('./deepsearch-api');
const { mergePeerAnswer } = await import('./peer-merge');
const { readSort, writeSort, SORT_KEY } = await import('./result-model');

const g = (id: string, extra: Record<string, unknown> = {}) => ({
  conversation_id: id, matches: 1, hits: [{ line: 1, kind: 'user', snippet: `\u0002flux\u0003 ${id}`, file_kind: 'conversation' }], ...extra,
});

beforeEach(() => { vi.useFakeTimers(); localStorage.clear(); });
afterEach(() => { vi.useRealTimers(); document.body.innerHTML = ''; });

test('the sort is remembered per device and a bad stored value falls back to relevance', () => {
  expect(readSort()).toBe('relevance');
  writeSort('date');
  expect(localStorage.getItem(SORT_KEY)).toBe('date');
  expect(readSort()).toBe('date');
  localStorage.setItem(SORT_KEY, 'bogus');
  expect(readSort()).toBe('relevance');
});

test('picking newest searches again with sort=date and the toggle marks it', async () => {
  const calls: Array<string | undefined> = [];
  const api = { search: async (_q: string, _o: number, _s: AbortSignal, scope?: { sort?: string }) => { calls.push(scope?.sort); return readAnswer({ query: 'flux', total_conversations: 1, groups: [g('c1')] }); } };
  const controller = new DeepSearchController(api, async () => 'none');
  controller.query = 'flux';
  controller.onType();
  await vi.advanceTimersByTimeAsync(DEBOUNCE_MS + 1);
  const host = document.createElement('div');
  document.body.append(host);
  const app = mount(DeepSearchResults, { target: host, props: { controller } });
  flushSync();
  const newest = host.querySelector('[data-testid="deepsearch-sort"] [data-sort="date"]') as HTMLElement;
  expect(newest).toBeTruthy();
  newest.click();
  await vi.advanceTimersByTimeAsync(0);
  flushSync();
  expect(calls).toEqual(['relevance', 'date']);
  expect(localStorage.getItem(SORT_KEY)).toBe('date');
  expect(newest.getAttribute('aria-checked')).toBe('true');
  unmount(app);
});

test('the merge keeps exact matches first, and under date sorts each tier newest first', () => {
  const mine = readAnswer({ groups: [g('l-exact', { exact: true, last_active: '2026-01-01' }), g('l-fuzzy', { exact: false, last_active: '2026-09-01' })] }).groups;
  const peers = readAnswer({ groups: [g('p-exact', { exact: true, last_active: '2026-05-01', host_key: 'peer-a', host_label: 'a' }), g('p-fuzzy', { exact: false, last_active: '2026-10-01', host_key: 'peer-a', host_label: 'a' })] });
  expect(mergePeerAnswer(mine, peers, 'relevance').groups.map((x) => x.conversationId)).toEqual(['l-exact', 'p-exact', 'l-fuzzy', 'p-fuzzy']);
  expect(mergePeerAnswer(mine, peers, 'date').groups.map((x) => x.conversationId)).toEqual(['p-exact', 'l-exact', 'p-fuzzy', 'l-fuzzy']);
  const plain = readAnswer({ groups: [g('p1', { host_key: 'peer-a', host_label: 'a' })] });
  expect(mergePeerAnswer(readAnswer({ groups: [g('l1')] }).groups, plain, 'date').groups.map((x) => x.conversationId)).toEqual(['l1', 'p1']);
});
