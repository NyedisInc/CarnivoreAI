/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve as resolvePath } from 'node:path';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import Renderer from './Renderer.svelte';
import * as V from './validate';

const t = (key: string): string => key;
const ANTHROPIC_KEY = ['sk', 'ant', 'api03', 'aB3dE5fG7h'.repeat(4)].join('-');
const GITHUB_KEY = ['ghp', 'aB3dE5fG7h'.repeat(4)].join('_');
const DECLARED: V.Declared = { routes: ['refresh'], tools: ['clock_now'] };
const text = (value: unknown): Record<string, unknown> => ({ type: 'text', value });
const doc = (root: unknown): Record<string, unknown> => ({ schema: 1, root });

function nested(n: number): Record<string, unknown> {
    let node: Record<string, unknown> = text('deep');
    for (let i = 0; i < n; i += 1) node = { type: 'column', children: [node] };
    return node;
}

const NEGATIVE: [string, unknown, string][] = [
    ['an action naming an undeclared route', doc({ type: 'button', label: 'go', action: { call: 'route', route: 'wipe' } }), 'action_not_declared'],
    ['a tool the plugin did not declare', doc({ type: 'button', label: 'go', action: { call: 'tool', name: 'rm_rf' } }), 'action_not_declared'],
    ['an action kind outside route and tool', doc({ type: 'button', label: 'go', action: { call: 'link', url: 'x' } }), 'action_not_supported'],
    ['depth past the limit', doc(nested(14)), 'too_deep'],
    ['a key-shaped value', doc(text(`token ${ANTHROPIC_KEY}`)), 'secret_shape'],
    ['a github token', doc(text(GITHUB_KEY)), 'secret_shape'],
    ['an unknown node', doc({ type: 'iframe', src: 'x' }), 'unknown_node'],
    ['a javascript: link in a text', doc(text('javascript:alert(1)')), 'link_not_allowed'],
    ['an https link in a label', doc({ type: 'section', title: 'see https://evil.example', children: [] }), 'link_not_allowed'],
    ['a class on a node', doc({ type: 'text', value: 'hi', class: 'cu-frame__bar' }), 'unknown_field'],
    ['a style on a node', doc({ type: 'text', value: 'hi', style: 'position:fixed;inset:0' }), 'unknown_field'],
    ['a text over the length limit', doc(text('x'.repeat(2001))), 'bad_string'],
    ['an invisible character', doc(text('a‮b')), 'invisible_character'],
    ['a bad schema', { schema: 2, root: text('hi') }, 'bad_schema'],
    ['a field outside the document', { schema: 1, root: text('hi'), html: '<b>' }, 'bad_document'],
    ['too many rows', doc({ type: 'table', columns: ['a'], rows: Array.from({ length: 101 }, () => ['x']) }), 'too_many_rows'],
    ['a bad badge status', doc({ type: 'badge', status: 'on-fire' }), 'bad_status'],
];

let mounted: Record<string, unknown> | null = null;
afterEach(() => { if (mounted) unmount(mounted); mounted = null; document.body.innerHTML = ''; });

async function draw(document_: unknown, extra: Record<string, unknown> = {}): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(Renderer, { target, props: { cplugId: 'acme-clock', name: 'Acme Clock', document: document_, declared: DECLARED, t, ...extra } });
    await tick(); await tick();
    flushSync();
    return target;
}

const SERVER = readFileSync(resolvePath(__dirname, '../../../../src/cplugs/host/ui_doc.py'), 'utf8');

describe('client validation mirrors the server', () => {
    test('every limit and the node vocabulary are the same numbers and fields as ui_doc.py', () => {
        const limit = (name: string): number => {
            const m = new RegExp(`^${name} = (\\d+)( \\* (\\d+))?$`, 'm').exec(SERVER);
            expect(m, `${name} not found in ui_doc.py`).not.toBeNull();
            return Number(m![1]) * (m![3] ? Number(m![3]) : 1);
        };
        for (const name of ['MAX_NODES', 'MAX_DEPTH', 'MAX_BYTES', 'MAX_ROWS', 'MAX_COLUMNS', 'MAX_TEXT', 'MAX_LABEL', 'MAX_PAYLOAD_BYTES']) {
            expect((V as unknown as Record<string, number>)[name], name).toBe(limit(name));
        }
        const block = /_FIELDS: Dict\[str, frozenset\] = \{([\s\S]*?)\n\}/.exec(SERVER)![1]!;
        const server: Record<string, string[]> = {};
        for (const m of block.matchAll(/"(\w+)": frozenset\(\{([^}]*)\}\)/g)) server[m[1]!] = [...m[2]!.matchAll(/"(\w+)"/g)].map((x) => x[1]!).sort();
        const client = Object.fromEntries(Object.entries(V.NODE_FIELDS).map(([k, v]) => [k, [...v].sort()]));
        expect(client).toEqual(server);
        const setOf = (name: string): string[] => [...new RegExp(`^${name} = frozenset\\(\\{([^}]*)\\}\\)`, 'm').exec(SERVER)![1]!.matchAll(/"(\w+)"/g)].map((x) => x[1]!).sort();
        expect([...V.TONES].sort()).toEqual(setOf('TONES'));
        expect([...V.STATUSES].sort()).toEqual(setOf('STATUSES'));
    });

    test.each(NEGATIVE)('refuses %s with the server code', (_name, document_, code) => {
        const verdict = V.validateDocument(document_, DECLARED);
        expect(verdict.ok).toBe(false);
        if (!verdict.ok) expect(verdict.code).toBe(code);
    });

    test('a valid document passes, rebuilt with only known fields', () => {
        const valid = {
            schema: 1,
            root: { type: 'section', title: 'clock', children: [
                { type: 'row', gap: 2, children: [{ type: 'badge', status: 'working' }, text({ bind: '/now' })] },
                { type: 'meter', label: 'load', value: 3, max: 10, thresholds: [5, 8] },
                { type: 'button', label: 'refresh', action: { call: 'route', route: 'refresh', payload: { full: true } } },
            ] },
            data: { now: '12:00' },
        };
        const verdict = V.validateDocument(valid, DECLARED);
        expect(verdict.ok).toBe(true);
        expect(V.resolve({ bind: '/now' }, (verdict as { doc: V.UiDocument }).doc.data)).toBe('12:00');
    });
});

describe('Renderer and HostFrame', () => {
    test('a valid document draws its nodes inside the plugin box', async () => {
        const root = await draw({ schema: 1, root: { type: 'column', children: [text('hello'), { type: 'stat', label: 'n', value: 7 }] } });
        const box = root.querySelector('[data-cplug-box]')!;
        expect(box.textContent).toContain('hello');
        expect(box.querySelector('[data-cu="stat"]')).not.toBeNull();
    });

    test('the literal name and the third-party mark sit OUTSIDE the box, before it, and a hostile document cannot remove them', async () => {
        for (const hostile of [doc(text('x'.repeat(2000))), doc(nested(3)), doc({ type: 'text', value: 'hi', class: 'cu-frame__bar', style: 'display:none' }), doc({ type: 'iframe' })]) {
            const root = await draw(hostile);
            const name = root.querySelector('[data-cplug-name]')!;
            const mark = root.querySelector('[data-cplug-mark]')!;
            const box = root.querySelector('[data-cplug-box]');
            expect(name.textContent).toBe('Acme Clock');
            expect(mark.textContent).toBe('cplug_ui.mark.third_party');
            expect(box?.contains(mark) ?? false).toBe(false);
            expect(box?.contains(name) ?? false).toBe(false);
            if (box) expect(mark.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
            unmount(mounted!); mounted = null; document.body.innerHTML = '';
        }
    });

    test('a refused document draws NOTHING of the plugin and shows the host line; a sideload reads unverified', async () => {
        const root = await draw(doc({ type: 'iframe' }), { unverified: true });
        expect(root.querySelector('[data-cu-root]')).toBeNull();
        expect(root.querySelector('[data-cplug-note]')?.textContent).toBe('cplug_ui.could_not_draw');
        expect(root.querySelector('[data-cplug-mark]')?.textContent).toBe('cplug_ui.mark.unverified');
    });

    test('a button runs only its declared route; a 409 not running shows the quiet host line', async () => {
        const { ApiError } = await import('../../opscenter/api/auth.svelte');
        const run = vi.fn(async () => { throw new ApiError('x', 409, 'cplug_not_running'); });
        const root = await draw(doc({ type: 'button', label: 'refresh', action: { call: 'route', route: 'refresh' } }), { run });
        root.querySelector<HTMLElement>('[data-cu="button"] button')!.click();
        await tick(); await tick(); flushSync();
        expect(run).toHaveBeenCalledExactlyOnceWith({ call: 'route', route: 'refresh' });
        expect(root.querySelector('.cu-action__line')?.textContent).toBe('cplug_ui.not_running');
    });
});
