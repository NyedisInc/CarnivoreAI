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

test('every row has its buttons at rest; hover changes nothing; an arrow key moves the highlight; one click opens the context', async () => {
    const opened: number[] = [];
    const controller = new DeepSearchController({ search: async () => answer() }, async () => 'switched', 'deepsearch.no_matches',
        (props) => { opened.push((props.request as { line?: number }).line ?? -1); });
    controller.showActions = true; // the context mode draws the buttons
    await controller.run('flux', 0);
    mounted = mount(DeepSearchResults, { target: host, props: { controller } });
    await settle();
    const rows = () => [...host.querySelectorAll('.dps__hit')] as HTMLElement[];
    const selected = () => host.querySelectorAll('[aria-selected="true"]');

    expect(rows()).toHaveLength(2);
    for (const row of rows()) {
        const actions = [...row.querySelectorAll('[data-testid="deepsearch-actions"] button')].map((b) => b.getAttribute('data-action'));
        expect(actions).toEqual(expect.arrayContaining(['read', 'link']));
        expect(row.querySelector('[data-action="more"]') === null || actions.includes('more')).toBe(true);
    }
    expect(host.querySelectorAll('[data-testid="deepsearch-actions"]')).toHaveLength(2);
    const before = host.innerHTML;

    expect(selected()).toHaveLength(0);
    rows()[1]!.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
    rows()[1]!.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    await settle();
    expect(selected()).toHaveLength(0);
    expect(controller.active).toBe(-1);
    expect(host.innerHTML).toBe(before);  // nothing at all

    controller.move(1);
    await settle();
    expect(rows()[0]!.getAttribute('aria-selected')).toBe('true');
    expect(rows()[1]!.getAttribute('aria-selected')).toBe('false');
    expect(host.querySelectorAll('[data-testid="deepsearch-actions"]')).toHaveLength(2);

    expect(opened).toEqual([]);
    rows()[1]!.click();
    await settle();
    expect(rows()[1]!.getAttribute('aria-selected')).toBe('true');
    expect(rows()[0]!.getAttribute('aria-selected')).toBe('false');
    expect(opened).toHaveLength(1);
});
