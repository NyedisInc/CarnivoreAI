/** @vitest-environment jsdom */
import * as Search from '../drawer/search';
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import DrawerSearch from './DrawerSearch.svelte';
import { DRAWER_DEEP_ACTIVE_CLASS, DRAWER_SEARCH_ID, DRAWER_SEARCH_MODE_KEY } from './drawer-tabs';
import { CONTEXT_MODE_ID, CORE_MODES, MODE_NAMES, type SearchModeDef } from './search-modes';
import '../plugins/builtin';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import DeepSearchResults, { HIT_ID_PREFIX, RESULTS_ID } from '../deepsearch/DeepSearchResults.svelte';
import { contextProvider } from '../deepsearch/providers';
import { DEBOUNCE_MS, DeepSearchController } from '../deepsearch/deepsearch.svelte';
import { readAnswer, type DeepAnswer, type DeepSearchApi } from '../deepsearch/deepsearch-api';
import type { ConversationTarget, OpenOutcome } from '../conversation-open/open';
import type { DrawerSearchProvider } from '../deepsearch/provider-types';

const resumed = vi.hoisted(() => [] as string[]);
vi.mock('../deepsearch/result-actions', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../deepsearch/result-actions')>()),
    resumeSession: async (uuid: string) => { resumed.push(uuid); },
}));

const REPO = path.resolve(process.cwd(), '..');

/** The drawer's <aside>, exactly as shipped. */
function drawerMarkup(): string {
    const source = fs.readFileSync(path.join(REPO, 'client', 'index.html'), 'utf8');
    const start = source.indexOf('<aside id="session-sidebar-panel"');
    const end = source.indexOf('</aside>', start);
    if (start < 0 || end < 0) throw new Error('the drawer markup is missing from client/index.html');
    return source.slice(start, end + '</aside>'.length);
}

const ANSWER = (ingest: Record<string, unknown> = { state: 'running', reason: null, coverage: { backlog_files: 0 } }): DeepAnswer =>
    readAnswer({
        query: 'zebra', total_conversations: 2, total_matches: 4, offset: 0, ingest,
        groups: [
            {
                conversation_id: 'conv-a', matches: 3, session_uuid: 'uuid-a', session: 'Alpha work', project_id: 7,
                project: 'Carnivore', last_active: '2026-10-04T12:00:00+00:00', by_file_kind: { conversation: 3 },
                hits: [
                    { line: 4, kind: 'user', snippet: 'find the \u0002zebra\u0003 now', file_kind: 'conversation' },
                    { line: 9, kind: 'assistant', snippet: '<img src=x> \u0002ZEBRA\u0003', file_kind: 'conversation' },
                ],
            },
            {
                conversation_id: 'conv-b', matches: 1, session_uuid: null, session: null, first_prompt: 'old work',
                by_file_kind: { subagent: 1 },
                hits: [{ line: 0, kind: 'tool', snippet: 'grep \u0002zebra\u0003', file_kind: 'subagent' }],
            },
        ],
    });

interface Log {
    searches: string[];
    opened: ConversationTarget[];
    contexts: Array<{ request: { conversationId: string; line?: number }; focus: string }>;
}

function provider(log: Log, answer: () => Promise<DeepAnswer>, outcome: OpenOutcome = 'switched'): SearchModeDef {
    const api: DeepSearchApi = {
        search: async (q) => {
            log.searches.push(q);
            return answer();
        },
    };
    const open = async (target: ConversationTarget): Promise<OpenOutcome> => {
        log.opened.push(target);
        return outcome;
    };
    const made: DrawerSearchProvider = { ...contextProvider(), create: () => { const c = new DeepSearchController(api, open, undefined, (show) => { log.contexts.push(show); }); c.showActions = true; return c; }, Results: DeepSearchResults as DrawerSearchProvider['Results'] };
    return { id: CONTEXT_MODE_ID, icon: 'database', nameKey: 'drawer.search.mode.context', placeholderKey: made.placeholderKey, labelKey: made.labelKey, provider: made };
}

const mounted: ReturnType<typeof mount>[] = [];
let log: Log;

beforeEach(() => {
    installPopoverPolyfill();
    vi.useFakeTimers();
    log = { searches: [], opened: [], contexts: [] };
    document.body.innerHTML = drawerMarkup();
    localStorage.clear();
    Search.setQuery('');
    (globalThis as Record<string, unknown>).SessionSidebarSearch = {
        getQuery: Search.getQuery, setQuery: Search.setQuery, matchesRow: Search.matchesRow,
        matchesLabel: Search.matchesLabel, noMatchesHtml: Search.noMatchesHtml, normalize: Search.normalize,
    };
});

afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    vi.useRealTimers();
    vi.restoreAllMocks();
    document.body.replaceChildren();
    localStorage.clear();
    delete (globalThis as Record<string, unknown>).SessionSidebarSearch;
});

const legacyQuery = (): string => Search.getQuery();
const panel = (): HTMLElement => document.getElementById('session-sidebar-panel')!;
const hits = (target: HTMLElement): HTMLElement[] => Array.from(target.querySelectorAll<HTMLElement>('.dps__hit'));

function render(mode: SearchModeDef | null | undefined, deep = true) {
    if (deep && mode) localStorage.setItem(DRAWER_SEARCH_MODE_KEY, mode.id);
    const target = document.getElementById(DRAWER_SEARCH_ID)!;
    const props = mode === undefined ? {} : { modes: mode ? [CORE_MODES[0]!, mode] : [CORE_MODES[0]!] };
    mounted.push(mount(DrawerSearch, { target, props }));
    flushSync();
    const input = target.querySelector<HTMLInputElement>('.oc-search > input')!;
    const button = () => target.querySelector<HTMLButtonElement>('[data-ds-mode]')!;
    const choose = (id: string) => {
        button().click();
        flushSync();
        document.querySelector<HTMLElement>(`[role="menuitemradio"][data-node="${id}"]`)!.click();
        flushSync();
    };
    return { target, input, button, choose };
}

async function type(input: HTMLInputElement, value: string): Promise<void> {
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS + 1);
    flushSync();
}

function key(input: HTMLInputElement, k: string, init: KeyboardEventInit = {}): void {
    input.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...init }));
    flushSync();
}

test('with only the name filter listed, the box filters session names only, even with the database remembered', async () => {
    const { input, button, target } = render(null, false);
    localStorage.setItem(DRAWER_SEARCH_MODE_KEY, CONTEXT_MODE_ID);
    expect(button().dataset.mode).toBe(MODE_NAMES);
    expect(input.getAttribute('aria-label')).toBe('search agents by name, project or folder');
    await type(input, 'zebra');
    expect(legacyQuery()).toBe('zebra');
    expect(log.searches).toEqual([]);
    expect(target.querySelector('.dps')).toBeNull();
    expect(panel().classList.contains(DRAWER_DEEP_ACTIVE_CLASS)).toBe(false);
});

test('core lists all four modes with no plugin in play, and a remembered database choice stays the database', () => {
    localStorage.setItem(DRAWER_SEARCH_MODE_KEY, CONTEXT_MODE_ID);
    const { button, target } = render(undefined, false);
    expect(button().dataset.mode, 'the remembered database choice is core now: it holds').toBe(CONTEXT_MODE_ID);
    button().click();
    flushSync();
    const ids = () => Array.from(document.querySelectorAll<HTMLElement>('[role="menuitemradio"]')).map((el) => el.dataset.node);
    expect(ids()).toEqual(['names', 'prompts', CONTEXT_MODE_ID, 'all']);
    expect(target.querySelector('.oc-search > input')).not.toBeNull();
});

test('database mode: the dropdown row searches conversation text, grouped by conversation, in place of the list', async () => {
    const { input, button, choose, target } = render(provider(log, async () => ANSWER()), false);
    await type(input, 'zebra');
    expect(log.searches, 'on names, the box is the name filter').toEqual([]);
    choose(CONTEXT_MODE_ID);
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS + 1);
    flushSync();
    expect(button().dataset.mode).toBe(CONTEXT_MODE_ID);
    expect(localStorage.getItem(DRAWER_SEARCH_MODE_KEY)).toBe(CONTEXT_MODE_ID);
    expect(log.searches).toEqual(['zebra']);
    expect(legacyQuery(), 'the list is unfiltered while database results stand in for it').toBe('');
    expect(panel().classList.contains(DRAWER_DEEP_ACTIVE_CLASS)).toBe(true);
    expect(input.getAttribute('aria-controls')).toBe(RESULTS_ID);
    expect(target.querySelector('.dps__cap'), 'variant D: no caption row per conversation').toBeNull();
    const names = [...new Set(Array.from(target.querySelectorAll('.dps__hit .sd-hit__name')).map((n) => n.textContent?.trim()))];
    expect(names).toEqual(['Alpha work', 'old work']);
    expect(target.querySelector('.dps__status')!.textContent).toBe('4 hits in 2 conversations');
    expect(hits(target).length).toBe(3);
    expect(hits(target)[2]!.querySelector('.dps__tag')!.textContent).toBe('subagent');
    expect(hits(target)[1]!.querySelector('img')).toBeNull();
    expect(hits(target)[1]!.querySelector('.sd-mark')!.textContent).toBe('ZEBRA');
});

test('arrows walk the hits across conversations, Enter opens the context modal on the highlighted hit', async () => {
    const { input, target } = render(provider(log, async () => ANSWER()));
    await type(input, 'zebra');
    key(input, 'ArrowDown');
    key(input, 'ArrowDown');
    key(input, 'ArrowDown');
    expect(input.getAttribute('aria-activedescendant')).toBe(`${HIT_ID_PREFIX}2`);
    expect(hits(target)[2]!.getAttribute('aria-selected') === 'true').toBe(true);
    expect(hits(target).every((h) => h.querySelector('[data-testid="deepsearch-actions"] [data-action="read"]') !== null)).toBe(true);
    key(input, 'Enter');
    await vi.advanceTimersByTimeAsync(0);
    expect(log.contexts).toMatchObject([{ focus: 'hit', request: { conversationId: 'conv-b', line: 0 } }]);
    hits(target)[0]!.click();
    await vi.advanceTimersByTimeAsync(0);
    expect(log.contexts, 'one click opens the context').toHaveLength(2);
    expect(hits(target)[0]!.getAttribute('aria-selected') === 'true').toBe(true);
    expect(log.contexts[1]).toMatchObject({ request: { conversationId: 'conv-a', line: 4 } });
    expect(log.opened, 'a hit opens the modal, never the agent').toEqual([]);
    key(input, 'Enter', { metaKey: true });
    await vi.advanceTimersByTimeAsync(0);
    expect(resumed).toEqual(['uuid-a']);
    expect(log.opened).toEqual([{ conversationId: 'conv-a', sessionUuid: 'uuid-a', projectId: 7 }]);
});

test('a hit that cannot anchor a context window falls back to opening the conversation, and a conversation with no session says so', async () => {
    const lineless = () => Promise.resolve(readAnswer({
        query: 'zebra', total_conversations: 1, total_matches: 1, ingest: { state: 'running' },
        groups: [{ conversation_id: 'conv-b', matches: 1, session_uuid: null, first_prompt: 'old work', hits: [{ kind: 'user', snippet: 'a \u0002zebra\u0003', file_kind: 'conversation' }] }],
    }));
    const { input, target } = render(provider(log, lineless, 'none'));
    await type(input, 'zebra');
    hits(target)[0]!.click();
    hits(target)[0]!.click();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();
    expect(target.querySelectorAll('.dps__note').length).toBe(1);
    expect(target.querySelector('.dps__note')!.textContent).toContain('cannot be reopened');
});

test('no index support: the results still show and the index says it is paused', async () => {
    const stalled = ANSWER({ state: 'stalled', reason: 'fts_unavailable', coverage: { backlog_files: 0 } });
    const { input, target } = render(provider(log, async () => stalled));
    await type(input, 'zebra');
    const note = target.querySelector('[data-testid="deepsearch-ingest"]')!;
    expect(note.textContent).toBe('index paused: this computer cannot build the search index');
    expect(note.classList.contains('dps__ingest--stalled')).toBe(true);
    expect(hits(target).length).toBe(3);
});

test('running with a backlog says how much is still to read, and a current index says nothing', async () => {
    let answer = ANSWER({ state: 'running', reason: null, coverage: { backlog_files: 12 } });
    const { input, target } = render(provider(log, async () => answer));
    await type(input, 'zebra');
    expect(target.querySelector('[data-testid="deepsearch-ingest"]')!.textContent).toBe('still indexing: 12 files to read');
    answer = ANSWER();
    await type(input, 'zebras');
    expect(target.querySelector('[data-testid="deepsearch-ingest"]')).toBeNull();
});

test('a scope that leaves subagent transcripts out is said by name, and everything says nothing', async () => {
    let answer = ANSWER({ state: 'running', reason: null, scope: 'human', coverage: { backlog_files: 0 } });
    const { input, target } = render(provider(log, async () => answer));
    await type(input, 'zebra');
    expect(target.querySelector('[data-testid="deepsearch-ingest"]')!.textContent).toBe('subagent transcripts are not indexed by choice (people only)');
    answer = ANSWER({ state: 'running', reason: null, scope: 'all', coverage: { backlog_files: 0 } });
    await type(input, 'zebras');
    expect(target.querySelector('[data-testid="deepsearch-ingest"]')).toBeNull();
});

test('choosing names brings the name filter back with the same text', async () => {
    const { input, button, choose, target } = render(provider(log, async () => ANSWER()));
    await type(input, 'zebra');
    choose(MODE_NAMES);
    expect(button().dataset.mode).toBe(MODE_NAMES);
    expect(localStorage.getItem(DRAWER_SEARCH_MODE_KEY)).toBe(MODE_NAMES);
    expect(legacyQuery()).toBe('zebra');
    expect(target.querySelector('.dps')).toBeNull();
    expect(panel().classList.contains(DRAWER_DEEP_ACTIVE_CLASS)).toBe(false);
});

test('a short query never leaves the page, and a failed search says so', async () => {
    let fail = false;
    const { input, target } = render(provider(log, async () => {
        if (fail) throw new Error('boom');
        return ANSWER();
    }));
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    await type(input, 'z');
    expect(log.searches).toEqual([]);
    expect(target.querySelector('.dps__status')!.textContent).toBe('type at least 2 characters');
    fail = true;
    await type(input, 'zebra');
    expect(target.querySelector('.dps__status')!.textContent).toBe('search failed. try again.');
});
