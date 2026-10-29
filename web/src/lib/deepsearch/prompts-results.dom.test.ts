/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

(HTMLElement.prototype as { showPopover?: () => void }).showPopover ??= () => {};
(HTMLElement.prototype as { hidePopover?: () => void }).hidePopover ??= () => {};

const { default: DeepSearchResults } = await import('./DeepSearchResults.svelte');
const { DeepSearchController } = await import('./deepsearch.svelte');
const { readAnswer } = await import('./deepsearch-api');
const { groupedProvider } = await import('./providers');
const { MODE_PROMPTS, CORE_MODES } = await import('../drawer-tabs/search-modes');

const settle = async (): Promise<void> => {
  for (let i = 0; i < 6; i += 1) await Promise.resolve();
  flushSync();
};
const answer = () => readAnswer({
  query: 'flux', total_conversations: 1, total_matches: 1,
  groups: [{ conversation_id: 'c-ada', matches: 1, session: 'ada agent', hits: [{ line: 2, kind: 'user', snippet: 'why does the \u0002flux\u0003 capacitor drift after a restart', file_kind: 'conversation', at: '2026-10-12T09:05:00' }] }],
  ingest: { state: 'running' },
});

let host: HTMLElement;
let mounted: Record<string, unknown> | null = null;
beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
});
afterEach(() => {
  if (mounted) unmount(mounted);
  mounted = null;
  host.remove();
});

test('a prompt result is the prompt text first, with the prompt glyph, a muted session and when line, and no buttons or caption', async () => {
  const controller = new DeepSearchController({ search: async () => answer() });
  controller.promptStyle = true;
  await controller.run('flux', 0);
  mounted = mount(DeepSearchResults, { target: host, props: { controller } });
  await settle();
  expect(host.querySelectorAll('.dps__cap')).toHaveLength(0);
  const rows = host.querySelectorAll('.dps__prompt');
  expect(rows).toHaveLength(1);
  const row = rows[0]!;
  expect(row.querySelector('.dps__prompt-glyph')).not.toBeNull();
  const words = row.querySelector('.sd-hit__snip')!;
  expect(words.textContent).toBe('why does the flux capacitor drift after a restart');
  expect(words.querySelector('mark.sd-mark')!.textContent).toBe('flux');
  expect(row.querySelector('.sd-hit__name')!.textContent).toBe('ada agent');
  expect(row.querySelector('.sd-r__meta')!.textContent).not.toBe('');
  expect(row.querySelector('button')).toBeNull();
  expect(host.querySelectorAll('[data-testid="deepsearch-actions"]')).toHaveLength(0);
});

test('only the prompts mode paints prompts: its provider turns the style on, context and the plain grouped provider do not', () => {
  const prompts = CORE_MODES.find((m) => m.id === MODE_PROMPTS)!;
  expect((prompts.provider!.create() as InstanceType<typeof DeepSearchController>).promptStyle).toBe(true);
  expect((groupedProvider({ path: '/x', placeholderKey: 'a', labelKey: 'b', noMatchesKey: 'c' }).create() as InstanceType<typeof DeepSearchController>).promptStyle).toBe(false);
  expect(new DeepSearchController().promptStyle).toBe(false);
});
