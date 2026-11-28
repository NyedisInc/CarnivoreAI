/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

(HTMLElement.prototype as { showPopover?: () => void }).showPopover ??= () => {};
(HTMLElement.prototype as { hidePopover?: () => void }).hidePopover ??= () => {};

const promptRestore = vi.fn(async (_target: unknown) => true);
vi.mock('../offload-prompt/offload-prompt', () => ({ promptRestore: (target: unknown) => promptRestore(target) }));

const { default: DeepSearchResults } = await import('./DeepSearchResults.svelte');
const { DeepSearchController } = await import('./deepsearch.svelte');
const { readAnswer } = await import('./deepsearch-api');

const settle = async (): Promise<void> => {
  for (let i = 0; i < 6; i += 1) await Promise.resolve();
  flushSync();
};
const hit = (line: number) => ({ line, kind: 'user', snippet: `why does the \u0002flux\u0003 drift ${line}`, file_kind: 'conversation', at: '2026-10-12T09:05:00' });
const answer = (offloaded: boolean) => readAnswer({
  query: 'flux', total_conversations: 1, total_matches: 2,
  groups: [{ conversation_id: 'c-ada', matches: 2, session: 'ada agent', offloaded, hits: [hit(2), hit(5)] }],
  ingest: { state: 'running' },
});

let host: HTMLElement;
let mounted: Record<string, unknown> | null = null;
beforeEach(() => { host = document.createElement('div'); document.body.appendChild(host); promptRestore.mockClear(); });
afterEach(() => { if (mounted) unmount(mounted); mounted = null; host.remove(); });

async function paint(offloaded: boolean): Promise<void> {
  const controller = new DeepSearchController({ search: async () => answer(offloaded) });
  controller.promptStyle = true;
  await controller.run('flux', 0);
  mounted = mount(DeepSearchResults, { target: host, props: { controller } });
  await settle();
}

test('an offloaded conversation\'s prompt hit shows the offloaded tag and one restore button that opens the one restore prompt', async () => {
  await paint(true);
  expect(host.querySelectorAll('.dps__prompt').length).toBeGreaterThan(0);
  expect(host.querySelector('.dps__prompt [data-tag="offloaded"]')?.textContent?.trim()).toBe('offloaded');
  const buttons = host.querySelectorAll<HTMLElement>('[data-action="restore"]');
  expect(buttons).toHaveLength(1);
  buttons[0]!.click();
  await settle();
  expect(promptRestore).toHaveBeenCalledWith({ conversationId: 'c-ada', label: 'ada agent' });
});

test('a conversation that is on disk draws no tag and no restore button in prompts mode', async () => {
  await paint(false);
  expect(host.querySelector('[data-tag="offloaded"]')).toBeNull();
  expect(host.querySelector('[data-action="restore"]')).toBeNull();
});
