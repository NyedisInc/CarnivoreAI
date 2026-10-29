/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';


(HTMLElement.prototype as { showPopover?: () => void }).showPopover ??= () => {};
(HTMLElement.prototype as { hidePopover?: () => void }).hidePopover ??= () => {};

const wire = vi.hoisted(() => ({
    window: null as unknown,
    branched: [] as number[],
    opened: [] as unknown[],
    switched: [] as string[],
}));

vi.mock('./context-api', async (importOriginal) => {
    const actual = await importOriginal<typeof import('./context-api')>();
    return {
        ...actual,
        fetchContext: async () => actual.readWindow(wire.window),
        branchBookmark: async (id: number) => {
            wire.branched.push(id);
            return { sessionId: 'ses_clone', tmuxName: 'carnivore_clone' };
        },
    };
});

vi.mock('../conversation-open/open', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../conversation-open/open')>()),
    openConversation: async (target: unknown) => {
        wire.opened.push(target);
        return 'switched';
    },
}));

vi.mock('../../cplugs/sdk/sessions.svelte', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../../cplugs/sdk/sessions.svelte')>()),
    openSession: async (id: string) => {
        wire.switched.push(id);
        return true;
    },
}));

const { default: DeepSearchResults } = await import('./DeepSearchResults.svelte');
const { default: ContextModal } = await import('./ContextModal.svelte');
const { DeepSearchController } = await import('./deepsearch.svelte');
const { readAnswer } = await import('./deepsearch-api');

const settle = async (): Promise<void> => {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    flushSync();
};

const hit = (line: number, at: string, extra: Record<string, unknown> = {}) => ({
    line, kind: line % 2 ? 'assistant' : 'user', snippet: `we hit \u0002flux\u0003 ${line}`, file_kind: 'conversation', at, ...extra,
});

const answer = () => readAnswer({
    query: 'flux', total_conversations: 2, total_matches: 3,
    groups: [
        { conversation_id: 'c-ada', matches: 2, session: 'ada agent', hits: [
            hit(2, '2026-10-13T14:03:00', { bookmark: { id: 7, label: 'before refactor', at: '2026-10-13T14:30:00' } }),
            hit(5, '2026-10-12T09:05:00') ] },
        { conversation_id: 'c-bob', matches: 1, session: null, first_prompt: null, working_dir: '/work/bobs-folder', hits: [hit(1, '2026-10-12T10:00:00')] },
    ],
    ingest: { state: 'running' },
});

let host: HTMLElement;
let mounted: Record<string, unknown> | null = null;

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-13T20:00:00'));
    host = document.createElement('div');
    document.body.appendChild(host);
    wire.branched = [];
    wire.opened = [];
    wire.switched = [];
});

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    host.remove();
    vi.useRealTimers();
});

async function paint() {
    const shown: unknown[] = [];
    const opened: unknown[] = [];
    const controller = new DeepSearchController({ search: async () => answer() }, async (target) => { opened.push(target); return 'switched'; }, undefined, (s) => { shown.push(s); });
    controller.showActions = true;
    await controller.run('flux', 0);
    controller.move(1);
    mounted = mount(DeepSearchResults, { target: host, props: { controller } });
    await settle();
    return { controller, shown, opened };
}

test('hits group under their agent, each with its own date and its buttons at rest, offering only what applies', async () => {
    await paint();
    expect(host.querySelector('.dps__cap')).toBeNull();
    const names = [...new Set([...host.querySelectorAll('.dps__hit .sd-hit__name')].map((n) => n.textContent?.trim()))];
    expect(names).toEqual(['ada agent', 'bobs-folder']);
    const times = [...host.querySelectorAll('.dps__hit .sd-r__meta')].map((n) => (n.textContent ?? '').trim().replace(/^\S+\s/, ''));
    expect(times).toEqual(['14:03', 'oct 12', 'oct 12']);
    const strip = [...host.querySelectorAll('[data-testid="deepsearch-actions"]')[0]!.querySelectorAll('[data-action]')].map((b) => b.getAttribute('data-action'));
    expect(strip).toEqual(['read', 'link', 'more']);
    expect(host.querySelectorAll('[data-testid="deepsearch-actions"]')).toHaveLength(3);
    expect(host.querySelectorAll('[data-testid="deepsearch-open-agent"]')).toHaveLength(0);
});

test('a click on the picked hit opens the context modal; the menu offers the closest bookmark', async () => {
    const { shown, opened } = await paint();
    (host.querySelectorAll('.dps__hit')[0] as HTMLElement).click();
    await settle();
    expect(shown).toHaveLength(1);
    expect(shown[0]).toMatchObject({ focus: 'hit', title: 'ada agent', request: { conversationId: 'c-ada', line: 2 }, bookmark: { id: 7 } });
    expect(opened).toHaveLength(0);

    (host.querySelectorAll('.dps__hit')[0] as HTMLElement).dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 40 }));
    flushSync();
    await settle();
    (document.querySelector('[role="menu"] [data-node="closest"]') as HTMLElement).click();
    await settle();
    expect(shown[1]).toMatchObject({ focus: 'bookmark', request: { conversationId: 'c-ada', at: '2026-10-13T14:30:00' } });
});

const windowOf = (extra: Record<string, unknown> = {}) => ({
    anchor: 2, has_before: false, has_after: false,
    messages: [
        { line: 1, kind: 'user', role: 'user', text: 'first ask', at: '2026-10-13T14:00:00' },
        { line: 2, kind: 'assistant', role: 'assistant', text: 'the flux answer', at: '2026-10-13T14:03:00' },
    ],
    bookmarks: [{ id: 7, label: 'before refactor', at: '2026-10-13T14:30:00', after_line: 2 }],
    ...extra,
});

function openModalFor(props: Record<string, unknown>) {
    const closed: unknown[] = [];
    mounted = mount(ContextModal, {
        target: host,
        props: {
            close: (v: unknown) => closed.push(v), title: 'ada agent',
            request: { conversationId: 'c-ada', fileKind: 'conversation', hostKey: null, line: 2 },
            target: { conversationId: 'c-ada', sessionUuid: 's1', projectId: 1 }, hostLabel: null,
            bookmark: { id: 7, label: 'before refactor', at: '2026-10-13T14:30:00' }, focus: 'hit', hitLine: 2, ...props,
        },
    });
    return closed;
}

test('the modal reads the conversation around the hit and restores the closest bookmark as a clone', async () => {
    wire.window = windowOf();
    const closed = openModalFor({});
    await settle();
    const lines = [...host.querySelectorAll('.dps-ctx__msg')];
    expect(lines.map((l) => l.getAttribute('data-line'))).toEqual(['1', '2']);
    expect(lines[1]!.classList.contains('is-hit')).toBe(true);
    expect(lines[1]!.textContent).toContain('agent');
    expect(host.querySelector('.dps-ctx__mark')?.textContent).toContain('before refactor');
    const restore = host.querySelector('[data-testid="context-restore"]') as HTMLButtonElement;
    expect(restore.textContent).toBe('restore as clone');
    restore.click();
    await settle();
    expect(wire.branched).toEqual([7]);
    expect(wire.switched).toEqual(['ses_clone']);
    expect(closed).toEqual([null]);
});

test('the footer buttons share one class family and a short label, a quiet line names the bookmark, and the hit stays lit from the bookmark icon', async () => {
    wire.window = windowOf();
    openModalFor({ focus: 'bookmark', request: { conversationId: 'c-ada', fileKind: 'conversation', hostKey: null, at: '2026-10-13T14:30:00' } });
    await settle();
    const buttons = [...host.querySelectorAll('.modal-footer .modal-btn')] as HTMLElement[];
    expect(buttons.map((b) => b.textContent)).toEqual(['close', 'restore as clone', 'open agent']);
    expect(buttons.every((b) => b.className.split(' ').filter((c) => c.startsWith('modal-btn-')).length === 1)).toBe(true);
    expect(buttons[1]!.className).toBe(buttons[2]!.className);
    expect(host.querySelector('[data-testid="context-restore-line"]')?.textContent).toContain('before refactor');
    expect(host.querySelector('.dps-ctx__msg[data-line="2"]')?.classList.contains('is-hit')).toBe(true);
    expect(host.querySelector('.dps-ctx__who')?.textContent).toContain(' · ');
});

test('no restore action without a bookmark, or for a conversation held by a paired computer; open agent still works', async () => {
    wire.window = windowOf({ bookmarks: [] });
    openModalFor({ bookmark: null });
    await settle();
    expect(host.querySelector('[data-testid="context-restore"]')).toBeNull();
    (host.querySelector('[data-testid="context-open-agent"]') as HTMLElement).click();
    await settle();
    expect(wire.opened).toMatchObject([{ conversationId: 'c-ada' }]);
    expect(wire.branched).toEqual([]);

    unmount(mounted!);
    host.innerHTML = '';
    wire.window = windowOf();
    openModalFor({ hostLabel: 'hosta', request: { conversationId: 'c-ada', fileKind: 'conversation', hostKey: 'peer-hosta', line: 2 } });
    await settle();
    expect(host.querySelector('[data-testid="context-restore"]')).toBeNull();
    expect(host.querySelector('[data-testid="context-host"]')?.textContent).toBe('hosta');
});
