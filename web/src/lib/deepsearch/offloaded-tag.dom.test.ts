/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const promptRestore = vi.fn(async (_target: unknown) => true);
vi.mock('../offload-prompt/offload-prompt', () => ({ promptRestore: (target: unknown) => promptRestore(target) }));

const { default: ConvTags } = await import('./ConvTags.svelte');
const { default: RestoreAction } = await import('./RestoreAction.svelte');
const { readAnswer } = await import('./deepsearch-api');

let host: HTMLElement;
let mounted: { tags: unknown; action: unknown } | null = null;
beforeEach(() => { host = document.createElement('div'); document.body.append(host); promptRestore.mockClear(); });
afterEach(() => { if (mounted) { unmount(mounted.tags as Record<string, unknown>); unmount(mounted.action as Record<string, unknown>); } mounted = null; host.remove(); document.body.replaceChildren(); });

function groupOf(extra: Record<string, unknown>) {
    return readAnswer({ groups: [{ conversation_id: 'c-1', matches: 2, session: 'nightly', session_uuid: 's-1', hits: [], ...extra }] }).groups[0]!;
}

function paint(group: ReturnType<typeof groupOf>, onrestored: () => void = () => {}): void {
    const tags = mount(ConvTags, { target: host, props: { group, conv: 'asleep' } });
    const action = mount(RestoreAction, { target: host, props: { group, onrestored } });
    mounted = { tags, action };
    flushSync();
}

test('an offloaded result shows the offloaded tag and an always-visible restore button', () => {
    paint(groupOf({ offloaded: true }));
    expect(host.querySelector('[data-tag="offloaded"]')?.textContent?.trim()).toBe('offloaded');
    const button = host.querySelector<HTMLElement>('[data-action="restore"]');
    expect(button, 'the restore button').not.toBeNull();
    expect(button!.hidden).toBe(false);
});

test('the restore button opens the one offload prompt for the conversation, then tells the screen', async () => {
    const restored = vi.fn();
    paint(groupOf({ offloaded: true }), restored);
    host.querySelector<HTMLElement>('[data-action="restore"]')!.click();
    await Promise.resolve();
    await Promise.resolve();
    expect(promptRestore).toHaveBeenCalledWith({ conversationId: 'c-1', label: 'nightly' });
    expect(restored).toHaveBeenCalledTimes(1);
});

test('a declined prompt does not tell the screen', async () => {
    promptRestore.mockResolvedValueOnce(false);
    const restored = vi.fn();
    paint(groupOf({ offloaded: true }), restored);
    host.querySelector<HTMLElement>('[data-action="restore"]')!.click();
    await Promise.resolve();
    await Promise.resolve();
    expect(restored).not.toHaveBeenCalled();
});

test('a conversation that is not offloaded draws no tag and no restore', () => {
    paint(groupOf({}));
    expect(host.querySelector('[data-tag="offloaded"]')).toBeNull();
    expect(host.querySelector('[data-action="restore"]')).toBeNull();
});
