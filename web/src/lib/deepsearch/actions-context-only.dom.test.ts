/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

(HTMLElement.prototype as { showPopover?: () => void }).showPopover ??= () => {};
(HTMLElement.prototype as { hidePopover?: () => void }).hidePopover ??= () => {};

const { default: DeepSearchResults } = await import('./DeepSearchResults.svelte');
const { DeepSearchController } = await import('./deepsearch.svelte');
const { readAnswer } = await import('./deepsearch-api');

const settle = async (): Promise<void> => {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    flushSync();
};

const hit = (line: number) => ({ line, kind: 'user', snippet: `we hit \u0002flux\u0003 ${line}`, file_kind: 'conversation', at: '2026-10-12T09:05:00' });
const answer = () => readAnswer({
    query: 'flux', total_conversations: 1, total_matches: 2,
    groups: [{ conversation_id: 'c-ada', matches: 2, session: 'ada agent', hits: [hit(2), hit(5)] }],
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

test('only the context mode draws action buttons: a controller that is not the context one paints bare rows that still open on a click', async () => {
    const opened: number[] = [];
    const bare = new DeepSearchController({ search: async () => answer() }, async () => 'switched', 'deepsearch.no_matches',
        (props) => { opened.push((props.request as { line?: number }).line ?? -1); });
    expect(bare.showActions).toBe(false);
    await bare.run('flux', 0);
    mounted = mount(DeepSearchResults, { target: host, props: { controller: bare } });
    await settle();
    expect(host.querySelectorAll('.dps__hit')).toHaveLength(2);
    expect(host.querySelectorAll('[data-testid="deepsearch-actions"]')).toHaveLength(0);
    expect(host.querySelectorAll('.dps__hit button')).toHaveLength(0);
    (host.querySelector('.dps__hit') as HTMLElement).click();
    await settle();
    expect(opened).toHaveLength(1);
});

test('the providers decide: context draws the buttons, prompts does not', async () => {
    const { contextProvider } = await import('./providers');
    const { PROMPTS_SEARCH_PATH } = await import('../drawer-tabs/search-modes');
    const { groupedProvider } = await import('./providers');
    expect(contextProvider().create().showActions).toBe(true);
    expect(groupedProvider({ path: PROMPTS_SEARCH_PATH, placeholderKey: 'a', labelKey: 'b', noMatchesKey: 'c' }).create().showActions).toBe(false);
});

test('in the context mode the action row sits UNDER the excerpt, never on the name line; every other mode has none', async () => {
    const ctx = new DeepSearchController({ search: async () => answer() }, async () => 'switched', 'deepsearch.no_matches', () => {});
    ctx.showActions = true;
    await ctx.run('flux', 0);
    mounted = mount(DeepSearchResults, { target: host, props: { controller: ctx } });
    await settle();
    const row = host.querySelector('.dps__hit') as HTMLElement;
    const head = row.querySelector('.sd-hit__top') as HTMLElement;
    const snip = row.querySelector('.sd-hit__snip') as HTMLElement;
    expect(head.querySelector('button'), 'nothing on the name line').toBeNull();
    const acts = row.querySelector(':scope > [data-testid="deepsearch-actions"]') as HTMLElement;
    expect(acts, 'the action row is in the hit, under the excerpt').not.toBeNull();
    expect(snip.compareDocumentPosition(acts) & Node.DOCUMENT_POSITION_FOLLOWING, 'after the excerpt').toBeTruthy();
    const kinds = [...acts.querySelectorAll('[data-action]')].map((b) => `${b.getAttribute('data-action')}:${b.getAttribute('data-btn') ?? 'icon'}`);
    expect(kinds).toEqual(['read:confirm', 'link:icon']);
});
