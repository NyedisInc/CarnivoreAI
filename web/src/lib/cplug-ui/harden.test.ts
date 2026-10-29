/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve as resolvePath } from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import Renderer from './Renderer.svelte';
import StatusChip from './StatusChip.svelte';
import { jsonSize, validateDocument, type Declared } from './validate';

const feed = vi.hoisted(() => ({
    rows: [] as Record<string, unknown>[],
    fetches: 0,
    started: [] as { cplugId: string; installKey: string | null }[],
    stopped: [] as { cplugId: string; installKey: string | null }[],
    live: new Set<object>(),
    document: null as unknown,
}));

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
    ...(await original<Record<string, unknown>>()),
    authFetch: vi.fn(async () => { feed.fetches += 1; return { cplugs: feed.rows }; }),
}));
vi.mock('../resource-push/boot', () => ({ resourcePush: () => ({ onChange: vi.fn(), pushOrPoll: vi.fn() }) }));
vi.mock('./surface.svelte', () => ({
    watchSurface: vi.fn((spec: { cplugId: string; installKey: string | null }, set: (s: unknown) => void) => {
        feed.started.push(spec);
        feed.live.add(spec);
        set({ kind: 'ready', document: feed.document, stale: false });
        return () => { feed.stopped.push(spec); feed.live.delete(spec); };
    }),
}));

const t = (key: string): string => key;
const HOSTILE = '<img src=x onerror=alert(1)>';
const DECLARED: Declared = { routes: ['refresh'], tools: [] };
const GLANCE = { schema: 1, root: { type: 'badge', text: 'disk almost full', tone: 'warn' } };

let mounted: Record<string, unknown> | null = null;
afterEach(() => { if (mounted) unmount(mounted); mounted = null; document.body.innerHTML = ''; });

async function settle(): Promise<void> { await tick(); await tick(); flushSync(); }

describe('plugin text is inert in every node', () => {
    const NODES: [string, Record<string, unknown>][] = [
        ['text', { type: 'text', value: HOSTILE }],
        ['text bound to data', { type: 'text', value: { bind: '/x' } }],
        ['badge', { type: 'badge', text: HOSTILE }],
        ['stat label', { type: 'stat', label: HOSTILE, value: 1 }],
        ['stat value', { type: 'stat', label: 'n', value: HOSTILE, unit: HOSTILE, delta: HOSTILE }],
        ['list item', { type: 'list', items: [{ type: 'text', value: HOSTILE }] }],
        ['list empty line', { type: 'list', items: [], empty: HOSTILE }],
        ['table head and cell', { type: 'table', columns: [HOSTILE], rows: [[HOSTILE]] }],
        ['button label', { type: 'button', label: HOSTILE, action: { call: 'route', route: 'refresh' } }],
        ['meter label', { type: 'meter', label: HOSTILE, value: 1, max: 2 }],
        ['section title', { type: 'section', title: HOSTILE, children: [] }],
    ];

    test.each(NODES)('%s shows markup as literal text and creates no element', async (_name, node) => {
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(Renderer, { target, props: { cplugId: 'acme-clock', name: 'Acme Clock', document: { schema: 1, root: node, data: { x: HOSTILE } }, declared: DECLARED, t } });
        await settle();
        const box = target.querySelector('[data-cplug-box]')!;
        expect(box, 'the document drew').not.toBeNull();
        expect(box.textContent).toContain(HOSTILE);
        expect(box.querySelector('img'), 'no element was created from the text').toBeNull();
        expect([...box.querySelectorAll('*')].some((el) => el.getAttributeNames().some((a) => a.startsWith('on'))), 'no event attribute').toBe(false);
    });
});

describe('the third-party mark beside plugin text', () => {
    test('the status chip carries the host mark outside the badge; a sideload reads unverified', async () => {
        feed.document = GLANCE;
        for (const [unverified, word] of [[false, 'cplug_ui.mark.third_party'], [true, 'cplug_ui.mark.unverified']] as const) {
            const target = document.createElement('div');
            document.body.append(target);
            mounted = mount(StatusChip, { target, props: { cplugId: 'acme-clock', installKey: 'k1', declared: DECLARED, unverified, t } });
            await settle();
            const chip = target.querySelector('[data-cplug-chip]')!;
            const mark = target.querySelector('[data-cplug-mark]')!;
            expect(chip.textContent).toBe('disk almost full');
            expect(mark.textContent).toBe(word);
            expect(chip.contains(mark), 'the mark is not inside the plugin badge').toBe(false);
            expect(mark.className).toContain('cu-frame__mark');
            expect(mark.hasAttribute('data-unverified')).toBe(unverified);
            unmount(mounted); mounted = null; target.remove();
        }
    });

    test('the gear badge on the plugins card is the status chip, handed the sideload flag', () => {
        const src = readFileSync(resolvePath(__dirname, '../plugins-page/PluginsScreen.svelte'), 'utf8');
        expect(src).toMatch(/<StatusChip[^>]*unverified=\{plugin\.unverified\}/);
    });
});

describe('the bar indicators', () => {
    const row = (extra: Record<string, unknown> = {}): Record<string, unknown> => ({
        id: 'acme-clock', name: 'Acme Clock', runtime: 'sidecar', enabled: true, state: 'active', version: '1.0.0',
        install_key: 'key-1', routes: ['refresh'], declared_tools: ['clock_now'], ...extra,
    });

    async function load(): Promise<typeof import('./bar-indicators.svelte')> {
        vi.resetModules();
        const { auth } = await import('../../opscenter/api/auth.svelte');
        auth.state = 'signed-in';
        return import('./bar-indicators.svelte');
    }

    beforeEach(() => { feed.rows = [row()]; feed.fetches = 0; feed.started = []; feed.stopped = []; feed.live.clear(); feed.document = GLANCE; });

    test('the tooltip leads with the host mark, then the literal name and the plugin words', async () => {
        const bar = await load();
        bar.thirdPartyBarIndicators();
        await vi.waitFor(() => expect(bar.thirdPartyBarIndicators()).toHaveLength(1));
        const label = bar.thirdPartyBarIndicators()[0]!.label!();
        expect(label.startsWith('third-party: Acme Clock: ')).toBe(true);
        expect(label).toContain('disk almost full');
        feed.rows = [row({ unverified: true })];
        await bar.syncBarIndicators();
        expect(bar.thirdPartyBarIndicators()[0]!.label!().startsWith('unverified: Acme Clock')).toBe(true);
    });

    test.each([
        ['install key', { install_key: 'key-2' }],
        ['version', { version: '1.1.0' }],
        ['routes', { routes: ['refresh', 'extra'] }],
        ['tools', { declared_tools: [] }],
        ['name', { name: 'Acme Clock Pro' }],
    ])('a changed %s re-keys the watcher: the old subscription stops, one new one runs', async (_what, change) => {
        const bar = await load();
        bar.thirdPartyBarIndicators();
        await vi.waitFor(() => expect(feed.started).toHaveLength(1));
        await bar.syncBarIndicators();
        expect(feed.started, 'an unchanged row is not restarted').toHaveLength(1);
        feed.rows = [row(change)];
        await bar.syncBarIndicators();
        expect(feed.started).toHaveLength(2);
        expect(feed.stopped).toHaveLength(1);
        expect(feed.live.size, 'never two subscriptions at once').toBe(1);
        if ('install_key' in change) expect(feed.started[1]!.installKey).toBe('key-2');
    });

    test('a re-sideload with a new name shows the new name with no reload', async () => {
        const bar = await load();
        bar.thirdPartyBarIndicators();
        await vi.waitFor(() => expect(bar.thirdPartyBarIndicators()[0]?.label!()).toContain('Acme Clock'));
        feed.rows = [row({ name: 'Renamed Clock', install_key: 'key-9' })];
        await bar.syncBarIndicators();
        expect(bar.thirdPartyBarIndicators()[0]!.label!()).toContain('Renamed Clock');
    });

    test('signed out, it asks for nothing', async () => {
        vi.resetModules();
        const { auth } = await import('../../opscenter/api/auth.svelte');
        auth.state = 'signed-out';
        const bar = await import('./bar-indicators.svelte');
        expect(bar.thirdPartyBarIndicators()).toEqual([]);
        await bar.syncBarIndicators();
        expect(feed.fetches).toBe(0);
    });
});

describe('jsonSize counts what the server counts', () => {
    const fixture = JSON.parse(readFileSync(resolvePath(__dirname, 'size-parity.fixture.json'), 'utf8')) as { sizes: Record<string, number>; documents: Record<string, unknown> };

    test.each(Object.keys(fixture.documents))('%s', (name) => {
        expect(jsonSize(fixture.documents[name])).toBe(fixture.sizes[name]);
    });

    test('the fixture covers ASCII, accented Latin, CJK, an astral emoji and an escaped quote, and the server still counts json.dumps', () => {
        expect(Object.keys(fixture.documents)).toEqual(expect.arrayContaining(['ascii', 'accented_latin', 'cjk', 'astral_emoji', 'escaped_quote']));
        const server = readFileSync(resolvePath(__dirname, '../../../../src/cplugs/host/ui_doc.py'), 'utf8');
        expect(server).toContain('size = len(json.dumps(document, allow_nan=False))');
        expect(JSON.stringify(fixture.documents['cjk']!).length).not.toBe(fixture.sizes['cjk']);
    });
});

describe('a URL scheme in bound data is refused like one in literal text', () => {
    const doc = (data: Record<string, unknown>) => ({ schema: 1, root: { type: 'text', value: { bind: '/a' } }, data });
    test.each(['javascript:alert(1)', 'data:text/html,x', 'vbscript:msgbox', 'https://evil.example/x', 'see https://evil.example'])('%s', (hostile) => {
        expect(validateDocument(doc({ a: hostile }), DECLARED)).toMatchObject({ ok: false, code: 'link_not_allowed' });
        expect(validateDocument(doc({ [hostile]: 1 }), DECLARED)).toMatchObject({ ok: false, code: 'link_not_allowed' });
    });
    test('whole id-shaped strings still ride in data', () => {
        expect(validateDocument(doc({ 'adopted:tm': { n: 'plugin:x:y', r: 'remote:peer-1' } }), DECLARED).ok).toBe(true);
    });
});
