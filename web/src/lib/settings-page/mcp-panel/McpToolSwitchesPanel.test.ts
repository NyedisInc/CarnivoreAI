/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import McpToolSwitchesPanel from './McpToolSwitchesPanel.svelte';
import { setLocale } from '../../i18n/index.svelte';

setLocale('en');

const DAYS = ['d1', 'd2', 'd3', 'd4', 'd5', 'd6', 'd7'];
const row = (name: string, enabled = true, family_hidden = false, calls = 0) =>
    ({ name, description: `${name} does a thing.`, write: false, enabled, default_enabled: true, family_hidden, hidden_because: family_hidden ? 'its family is off' : '', calls,
        daily: [0, 0, 0, 0, 0, 0, calls] });

function harness(failPut = false, unreadable = false) {
    let since: string | null = null;
    const tools = [row('a_one', true, false, 4), row('a_two'), row('b_one', true, true)];
    const puts: Record<string, boolean>[] = [];
    const posts: string[] = [];
    const shown = () => tools.map((x) => (unreadable ? { ...x, calls: null, daily: null } : x));
    const answer = () => ({ usage: unreadable ? null : { since, days: DAYS }, groups: [
        { group: 'a', tools: shown().filter((x) => x.name.startsWith('a_')) },
        { group: 'b', tools: shown().filter((x) => x.name.startsWith('b_')) },
    ] });
    const fetcher = (async (_path: string, init?: RequestInit) => {
        if (init?.method === 'POST') {
            posts.push(_path);
            since = '2026-10-15T12:00:00+00:00';
            for (const x of tools) { (x as { calls: number }).calls = 0; (x as { daily: number[] }).daily = [0, 0, 0, 0, 0, 0, 0]; }
        }
        if (init?.method === 'PUT') {
            if (failPut) throw new Error('boom');
            const set = JSON.parse(String(init.body)).set as Record<string, boolean>;
            puts.push(set);
            for (const [name, on] of Object.entries(set)) {
                const found = tools.find((x) => x.name === name);
                if (found) (found as { enabled: boolean }).enabled = on;
            }
        }
        return structuredClone(answer());
    }) as never;
    return { fetcher, puts, posts };
}

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
});
async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

async function render(h: ReturnType<typeof harness>): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(McpToolSwitchesPanel, { target, props: { fetcher: h.fetcher } }));
    await settle();
    return target;
}

describe('mcp tool switches panel', () => {
    test('a fold closes its rows and opens them again', async () => {
        const root = await render(harness());
        expect(root.querySelectorAll('[data-mcp-tool]').length).toBe(3);
        const fold = root.querySelector<HTMLElement>('[data-mcp-tools-group="a"] .oc-fold__toggle')!;
        fold.click();
        await settle();
        expect(root.querySelectorAll('[data-mcp-tool]').length).toBe(1);
        fold.click();
        await settle();
        expect(root.querySelectorAll('[data-mcp-tool]').length).toBe(3);
        expect(root.querySelector('[data-mcp-tools-group="a"]')!.textContent).toContain('2 of 2 on');
    });

    test('a row switch writes that one tool and shows the answer', async () => {
        const h = harness();
        const root = await render(h);
        root.querySelector<HTMLElement>('[data-mcp-tool="a_one"]')!.click();
        await settle();
        expect(h.puts).toEqual([{ a_one: false }]);
        expect(root.querySelector('[data-mcp-tool="a_one"]')!.getAttribute('aria-checked')).toBe('false');
    });

    test('all off writes every name in the group and disables itself', async () => {
        const h = harness();
        const root = await render(h);
        root.querySelector<HTMLElement>('[data-mcp-tools-group="a"] [data-mcp-tools="all-off"]')!.click();
        await settle();
        expect(h.puts).toEqual([{ a_one: false, a_two: false }]);
        expect(root.querySelector<HTMLButtonElement>('[data-mcp-tools-group="a"] [data-mcp-tools="all-off"]')!.disabled).toBe(true);
    });

    test('a tool whose family is on carries no hidden note', async () => {
        const root = await render(harness());
        expect(root.querySelector('[data-mcp-tools-group="a"] [data-mcp-hidden]')).toBeNull();
        expect(root.querySelector('[data-mcp-tools-group="a"]')!.textContent).not.toContain('also hidden');
    });

    test('a tool a family also hides says so', async () => {
        const root = await render(harness());
        expect(root.querySelector('[data-mcp-tools-group="b"]')!.textContent).toContain('also hidden: its family is off');
    });

    test('a failed write is said, not swallowed', async () => {
        const root = await render(harness(true));
        root.querySelector<HTMLElement>('[data-mcp-tools-group="a"] [data-mcp-tools="all-off"]')!.click();
        await settle();
        expect(root.querySelector('[data-mcp-tools="problem"]')!.textContent).toContain('boom');
    });

    test('each row shows its calls and a bar per day, and the title strip says what the count covers', async () => {
        const root = await render(harness());
        expect(root.querySelector('[data-mcp-calls="a_one"]')!.textContent).toBe('4');
        expect(root.querySelectorAll('[data-mcp-trend="a_one"] .oc-spark-bar').length).toBe(7);
        expect(root.querySelector('[data-mcp-tools="summary"]')!.textContent).toContain('4 calls recorded, never reset');
    });

    test('reset counts posts once, zeroes what is drawn and says so with the since time', async () => {
        const h = harness();
        const root = await render(h);
        root.querySelector<HTMLElement>('[data-mcp-tools="reset"]')!.click();
        await settle();
        expect(h.posts).toEqual(['/mcp-admin/tools/usage/reset']);
        expect(root.querySelector('[data-mcp-calls="a_one"]')!.textContent).toBe('0');
        expect(root.querySelector('[data-mcp-tools="reset-done"]')).not.toBeNull();
        expect(root.querySelector('[data-mcp-tools="summary"]')!.textContent).toContain('0 calls since');
    });

    test('with the usage file unreadable no count or graph is drawn and the switches still work', async () => {
        const root = await render(harness(false, true));
        expect(root.querySelector('[data-mcp-trend]')).toBeNull();
        expect(root.querySelector('[data-mcp-calls="a_one"]')!.textContent).toBe('-');
        expect(root.querySelector<HTMLButtonElement>('[data-mcp-tools="reset"]')!.disabled).toBe(true);
        expect(root.querySelector('[data-mcp-tool="a_one"]')).not.toBeNull();
    });

    test('every family starts expanded', async () => {
        const root = await render(harness());
        expect(root.querySelectorAll('[data-mcp-tool]').length).toBe(3);
        expect(root.querySelector('.oc-fold__toggle')!.getAttribute('aria-expanded')).toBe('true');
    });

    test('fold all and expand all move every family', async () => {
        const root = await render(harness());
        root.querySelector<HTMLElement>('[data-mcp-tools="fold-all"]')!.click();
        await settle();
        expect(root.querySelectorAll('[data-mcp-tool]').length).toBe(0);
        root.querySelector<HTMLElement>('[data-mcp-tools="expand-all"]')!.click();
        await settle();
        expect(root.querySelectorAll('[data-mcp-tool]').length).toBe(3);
    });

    test('the filter narrows by name, family or description, hides empty families, expands matches and restores folds when cleared', async () => {
        const root = await render(harness());
        const type = async (text: string) => {
            const box = root.querySelector<HTMLInputElement>('[data-mcp-tools="filter"]')!;
            box.value = text;
            box.dispatchEvent(new Event('input', { bubbles: true }));
            await settle();
        };
        root.querySelector<HTMLElement>('[data-mcp-tools="fold-all"]')!.click();
        await settle();
        await type('A_TWO');
        expect([...root.querySelectorAll('[data-mcp-tool]')].map((n) => n.getAttribute('data-mcp-tool'))).toEqual(['a_two']);
        expect(root.querySelector('[data-mcp-tools-group="b"]')).toBeNull();
        await type('b_one does');
        expect([...root.querySelectorAll('[data-mcp-tool]')].map((n) => n.getAttribute('data-mcp-tool'))).toEqual(['b_one']);
        await type('b');
        expect(root.querySelectorAll('[data-mcp-tool]').length).toBe(1);
        await type('zzz');
        expect(root.querySelector('[data-mcp-tools="no-match"]')).not.toBeNull();
        await type('');
        expect(root.querySelectorAll('[data-mcp-tool]').length).toBe(0);
    });

    test('the tool name never truncates; only the description and the hidden note ellipsize, with a tooltip', async () => {
        const root = await render(harness());
        const name = root.querySelector<HTMLElement>('[data-mcp-name="a_one"]')!;
        expect(name.style.flex).toBe('0 0 auto');
        expect(name.style.whiteSpace).toBe('nowrap');
        expect(name.style.textOverflow).not.toBe('ellipsis');
        expect(name.style.overflow).toBe('visible');
        const desc = root.querySelector<HTMLElement>('[data-mcp-desc="a_one"]')!;
        expect(desc.style.textOverflow).toBe('ellipsis');
        expect(desc.style.overflow).toBe('hidden');
        expect(desc.style.minWidth).toBe('0');
        expect(desc.getAttribute('title')).toBe('a_one does a thing.');
        const note = root.querySelector<HTMLElement>('[data-mcp-hidden="b_one"]')!;
        expect(note.style.textOverflow).toBe('ellipsis');
        expect(note.getAttribute('title')).toContain('its family is off');
        expect(name.classList.contains('oc-rc-name-text')).toBe(true);
    });

    test('the deprecated family is last, folded until opened, switchable like any other group, and the filter opens it (#1842)', async () => {
        const dep = { ...row('old_one', false), default_enabled: false };
        const puts: Record<string, boolean>[] = [];
        const fetcher = (async (_path: string, init?: RequestInit) => {
            if (init?.method === 'PUT') {
                const set = JSON.parse(String(init.body)).set as Record<string, boolean>;
                puts.push(set);
                (dep as { enabled: boolean }).enabled = set.old_one === true;
            }
            return structuredClone({ usage: null, groups: [{ group: 'a', tools: [row('a_one')] }, { group: 'deprecated', tools: [dep] }] });
        }) as never;
        const target = document.createElement('div');
        document.body.append(target);
        mounted.push(mount(McpToolSwitchesPanel, { target, props: { fetcher } }));
        await settle();
        const groups = [...target.querySelectorAll('[data-mcp-tools-group]')].map((g) => g.getAttribute('data-mcp-tools-group'));
        expect(groups).toEqual(['a', 'deprecated']);
        const head = target.querySelector<HTMLElement>('[data-mcp-tools-group="deprecated"] .oc-fold__toggle')!;
        expect(head.getAttribute('aria-expanded')).toBe('false');
        expect(target.querySelector('[data-mcp-tool="old_one"]')).toBeNull();
        expect(target.querySelector('[data-mcp-tool="a_one"]')).not.toBeNull();
        head.click();
        await settle();
        expect(target.querySelector('[data-mcp-tools="deprecated-note"]')).not.toBeNull();
        target.querySelector<HTMLElement>('[data-mcp-tool="old_one"]')!.click();
        await settle();
        expect(puts).toEqual([{ old_one: true }]);
        head.click();
        await settle();
        expect(target.querySelector('[data-mcp-tool="old_one"]')).toBeNull();
        const filter = target.querySelector<HTMLInputElement>('[data-mcp-tools="filter"]')!;
        filter.value = 'old_one';
        filter.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        expect(target.querySelector('[data-mcp-tool="old_one"]')).not.toBeNull();
    });

    test('a two-part tool sits above the sub-heading blocks, and the filter matches a family label', async () => {
        const mixed = (name: string, sub: string, family = '') => ({ ...row(name), sub, family, alias_of: '' });
        const answer = { usage: null, groups: [{ group: 'sessions', tools: [mixed('s_create', ''), mixed('s_pin', 'pins', 'app settings tools')] }] };
        const target = document.createElement('div');
        document.body.append(target);
        mounted.push(mount(McpToolSwitchesPanel, { target, props: { fetcher: (async () => structuredClone(answer)) as never } }));
        await settle();
        const order = [...target.querySelectorAll('[data-mcp-sub], [data-mcp-name]')].map((n) => n.getAttribute('data-mcp-sub') ?? n.getAttribute('data-mcp-name'));
        expect(order).toEqual(['s_create', 'pins', 's_pin']);
        const filter = target.querySelector<HTMLInputElement>('[data-mcp-tools="filter"]')!;
        filter.value = 'app settings';
        filter.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        expect([...target.querySelectorAll('[data-mcp-name]')].map((n) => n.getAttribute('data-mcp-name'))).toEqual(['s_pin']);
    });
});
