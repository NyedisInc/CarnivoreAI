/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import AddSplit from './AddSplit.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import CatalogCard from './CatalogCard.svelte';
import CostBadge from './CostBadge.svelte';
import InstalledWhere from './InstalledWhere.svelte';
import UsageFacts from './UsageFacts.svelte';
import { createCatalogData } from './catalog-data.svelte';
import { cardViews } from './card';
import { installedDescTotal } from './cost';
import { quickAdd } from './quick-add';
import type { CatalogHost } from './catalog';
import type { CatalogItem, InstalledItem } from './types';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

const i18n = createI18n({ locale: 'en' }) as { t(k: string, p?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const GLOBAL_ROW: InstalledItem = {
    install_id: 'i-global', item_id: 'alex/deploy', name: 'deploy', scope: 'global',
    targets: [{ harness: 'claude', path: '/h/.claude/skills/deploy' }, { harness: 'codex', path: '/h/.agents/skills/deploy' }],
};
const PROJECT_ROW: InstalledItem = {
    install_id: 'i-proj', item_id: 'alex/deploy', name: 'deploy', scope: 'project',
    project_path: '/work/acme', targets: [{ harness: 'claude', path: '/work/acme/.claude/skills/deploy' }],
};
const ITEM = { id: 'alex/deploy', kind: 'skill', cost: { desc_tokens: 40, body_tokens: 900 } } as unknown as CatalogItem;

let mounted: Record<string, unknown> | null = null;
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

async function paint(component: never, props: Record<string, unknown>): Promise<void> {
    const target = document.createElement('div');
    document.body.appendChild(target);
    mounted = mount(component, { target, props: { t, ...props } as never }) as never;
    await flush();
}

afterEach(() => {
    if (mounted) unmount(mounted as never);
    mounted = null;
    document.body.innerHTML = '';
});

installPopoverPolyfill();

describe('store keeps every copy of an item', () => {
    test('an item installed globally and in a project keeps both rows', async () => {
        const host = {
            listItems: async () => ({ index: null, items: [ITEM], untrusted: [] }),
            listInstalled: async () => ({ items: [GLOBAL_ROW, PROJECT_ROW] }),
        } as unknown as CatalogHost;
        const data = createCatalogData(host, t);
        await data.refresh();
        expect(data.installed['alex/deploy']).toHaveLength(2);
        data.setInstalled('alex/deploy', null, 'i-proj');
        expect(data.installed['alex/deploy']?.map((r) => r.install_id)).toEqual(['i-global']);
        data.setInstalled('alex/deploy', { ...GLOBAL_ROW, version: '2' });
        expect(data.installed['alex/deploy']).toHaveLength(1);
        expect(data.installed['alex/deploy']?.[0]?.version).toBe('2');
    });
});

describe('card chips and the add split button', () => {
    const card = cardViews([ITEM], false)[0]!;
    const base = { card, state: { kind: 'installed' }, onInstall() {}, onUpdate() {}, onUninstall() {} };

    test('an installed card says so in one word; the split button offers this project when only another project holds a copy', async () => {
        // the reading pane
        await paint(CatalogCard as never, {
            ...base, rows: [PROJECT_ROW], projects: [{ path: '/work/other', name: 'Other' }], onAdd: () => {},
        });
        expect(document.querySelector('.cat-scope')).toBeNull();
        expect(document.querySelector('.catalog-card__state--on')?.textContent?.trim()).toBe('installed');
        document.body.innerHTML = '';
        const picked: string[] = [];
        await paint(AddSplit as never, {
            projects: [{ path: '/work/other', name: 'Other' }], installedAt: ['/work/acme'], haveGlobal: false, haveAnyProject: true,
            onAdd: (x: string, path?: string) => picked.push(`${x}:${path}`),
        });
        (document.querySelector('[data-act="add-menu"]') as HTMLElement).click();
        flushSync();
        expect(document.querySelector('.acm-menu.popup-focus')).not.toBeNull();
        expect(document.querySelector('.cat-add__menu')).toBeNull();
        const project = document.querySelector('[data-node="add-project"]') as HTMLElement;
        expect(project.textContent).toContain('add to project');
        expect(project.getAttribute('aria-disabled')).toBeNull();
        project.click();
        flushSync();
        (document.querySelector('[data-node="add-project:/work/other"]') as HTMLElement).click();
        expect(picked).toEqual(['project:/work/other']);
    });

    test('no chips and no split button without rows and an onAdd', async () => {
        await paint(CatalogCard as never, { ...base, state: { kind: 'idle' } });
        expect(document.querySelector('.cat-scope')).toBeNull();
        expect(document.querySelector('.cat-add')).toBeNull();
    });

    test('the project entry is blocked with no registered project', async () => {
        await paint(AddSplit as never, { projects: [], haveGlobal: false, onAdd() {} });
        (document.querySelector('[data-act="add-menu"]') as HTMLElement).click();
        flushSync();
        expect(document.querySelector('[data-node="add-project"]')?.getAttribute('aria-disabled')).toBe('true');
    });

    test('Escape closes the add menu and focus returns to the caret, not the body', async () => {
        await paint(AddSplit as never, { projects: [{ path: '/work/acme', name: 'Acme' }], haveGlobal: false, onAdd() {} });
        const caret = document.querySelector('[data-act="add-menu"]') as HTMLElement;
        caret.click();
        flushSync();
        (document.querySelector('[data-node="add-global"]') as HTMLElement).focus();
        document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
        flushSync();
        expect(document.querySelector('.acm-menu')).toBeNull();
        expect(document.activeElement).toBe(caret);
    });

    test('a project copy disables the global targets and a global copy disables the project entry (scope_shadowed)', async () => {
        await paint(AddSplit as never, { projects: [{ path: '/work/acme', name: 'Acme' }], installedAt: ['/work/acme'], haveGlobal: false, haveAnyProject: true, onAdd() {} });
        (document.querySelector('[data-act="add-menu"]') as HTMLElement).click();
        flushSync();
        const disabled = (act: string) =>
            act === 'add'
                ? (document.querySelector('[data-act="add"]') as HTMLButtonElement).disabled
                : document.querySelector(`[data-node="${act}"]`)?.getAttribute('aria-disabled') === 'true';
        expect(disabled('add')).toBe(true);
        expect(disabled('add-global')).toBe(true);
        document.body.innerHTML = '';
        await paint(AddSplit as never, { projects: [{ path: '/work/acme', name: 'Acme' }], haveGlobal: true, onAdd() {} });
        (document.querySelector('[data-act="add-menu"]') as HTMLElement).click();
        flushSync();
        expect(disabled('add-project')).toBe(true);
    });
});

describe('quick add', () => {
    test('sends one_click and never consent; a clean item installs', async () => {
        const sent: unknown[] = [];
        const host = { install: async (r: unknown) => { sent.push(r); return GLOBAL_ROW; } } as unknown as CatalogHost;
        const out = await quickAdd(host, 'alex/deploy', 'project', '/work/acme');
        expect(out.outcome).toBe('installed');
        expect(sent[0]).toEqual({ item_id: 'alex/deploy', scope: 'project', project_path: '/work/acme', one_click: true });
    });

    test('sheet_required opens the sheet with the same choice, other refusals stay refusals', async () => {
        const reject = (code: string) =>
            ({ install: async () => { throw { body: { code } }; } }) as unknown as CatalogHost;
        expect(await quickAdd(reject('sheet_required'), 'a/b', 'project', '/work/acme')).toEqual({
            outcome: 'sheet', prefill: { scope: 'project', projectPath: '/work/acme' },
        });
        expect(await quickAdd(reject('key_untrusted'), 'a/b', 'global', null)).toEqual({
            outcome: 'refused', code: 'key_untrusted',
        });
    });
});

describe('cost badge', () => {
    test('prints description and body tokens labelled est., and the installed total', async () => {
        await paint(CostBadge as never, { item: ITEM, total: 140 });
        const text = document.body.textContent ?? '';
        expect(text).toContain('~40 tokens every turn (est.)');
        expect(text).toContain('~900 tokens when used (est.)');
        expect(text).toContain('~140 tokens every turn');
    });

    test('absent cost prints nothing, never a zero', async () => {
        await paint(CostBadge as never, { item: { id: 'a/b' } });
        expect(document.querySelector('.cat-cost')).toBeNull();
    });

    test('the installed total counts each installed item once and skips unpriced ones', () => {
        const other = { id: 'x/y', cost: { desc_tokens: 10 } } as unknown as CatalogItem;
        const bare = { id: 'z/z' } as unknown as CatalogItem;
        const held = { 'alex/deploy': [GLOBAL_ROW, PROJECT_ROW], 'x/y': [GLOBAL_ROW], 'z/z': [GLOBAL_ROW] };
        expect(installedDescTotal([ITEM, other, bare], held)).toBe(50);
        expect(installedDescTotal([ITEM], {})).toBeNull();
    });
});

describe('installed where', () => {
    test('one row per copy with its scope and harnesses; picking reports the install id', async () => {
        const picks: string[] = [];
        await paint(InstalledWhere as never, { rows: [GLOBAL_ROW, PROJECT_ROW], onPick: (id: string) => picks.push(id) });
        const rows = [...document.querySelectorAll('.cat-where__row')].map((r) => r.textContent?.replace(/\s+/g, ' ').trim());
        expect(rows).toEqual(['global in claude, codex', 'project acme in claude']);
        (document.querySelectorAll('.cat-where__scope')[1] as HTMLElement).click();
        expect(picks).toEqual(['i-proj']);
    });

    test('says so when nothing holds it', async () => {
        await paint(InstalledWhere as never, { rows: [] });
        expect(document.body.textContent).toContain('not installed anywhere');
    });
});

describe('usage facts', () => {
    const hostWith = (answer: unknown) => ({ skillUsage: async () => answer }) as unknown as CatalogHost;

    test('a measured count is printed as fired N times in 30 days on this computer', async () => {
        await paint(UsageFacts as never, { skill: 'deploy', host: hostWith({ state: 'measured', fired_30d: 3 }) });
        expect(document.body.textContent).toContain('fired 3 times in 30 days on this computer');
    });

    test('not measured, a failed read and a missing host method never print a zero', async () => {
        await paint(UsageFacts as never, { skill: 'deploy', host: hostWith({ state: 'not_measured', fired_30d: null }) });
        expect(document.body.textContent).toContain('not measured on this computer yet');
        expect(document.body.textContent).not.toContain('fired 0');
    });
});
