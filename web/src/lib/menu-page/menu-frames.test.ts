import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';
import { MENU_PAGES, type MenuPage } from './menu-pages';
import { PAGE_FRAMES } from '../../opscenter/ui/page-frame';

const ROOTS: Record<string, string> = {
    dashboards: 'lib/dashboards/DashboardsScreen.svelte',
    hosts: 'lib/pack-page/PackScreen.svelte',
    sessions: 'lib/sessions-page/SessionsPage.svelte',
    plugins: 'lib/plugins-page/PluginsScreen.svelte',
    themes: 'lib/themes-page/ThemesScreen.svelte',
    warez: 'lib/catalog/CatalogScreen.svelte',
    elite: 'lib/elite/EliteScreen.svelte',
    settings: 'lib/settings-page/SettingsScreen.svelte',
    account: 'lib/carnivore-account/AccountPage.svelte',
    widgets: 'lib/widgets-page/WidgetsScreen.svelte',
    ledger: 'lib/ledger/LedgerScreen.svelte',
    blueprints: 'lib/blueprints/BlueprintsScreen.svelte',
    docs: 'lib/info-pages/InfoScreen.svelte',
    'huddle-agent': 'lib/huddle-agent/HuddleAgentScreen.svelte',
    'huddle-swarm': 'lib/huddle-swarm/SwarmPage.svelte',
    mods: 'lib/mods/ModsScreen.svelte',
    automations: 'lib/automations/AutomationsScreen.svelte',
    changelog: 'lib/info-pages/InfoScreen.svelte',
    logs: 'lib/logs-page/LogsScreen.svelte',
    warroom: 'lib/warroom/WarRoomScreen.svelte',
};

const SRC = fileURLToPath(new URL('../../', import.meta.url));
const MANAGER_FRAME = 'lib/manager-frame/ManagerFrame.svelte';

function read(rel: string): string {
    return readFileSync(`${SRC}${rel}`, 'utf8');
}

function stripComments(source: string): string {
    const blank = (m: string): string => m.replace(/[^\n]/g, ' ');
    return source.replace(/<!--[\s\S]*?-->/g, blank).replace(/\/\*[\s\S]*?\*\//g, blank).replace(/(?<!:)\/\/[^\n]*/g, blank);
}

function pageTags(raw: string): string[] {
    const source = stripComments(raw);
    const tags: string[] = [];
    for (const m of source.matchAll(/<Page(?=\s)/g)) {
        let depth = 0;
        let i = m.index + 5;
        for (; i < source.length; i++) {
            const ch = source[i];
            if (ch === '{') depth++;
            else if (ch === '}') depth--;
            else if (ch === '>' && depth === 0) break;
        }
        tags.push(source.slice(m.index, i + 1));
    }
    return tags;
}

function wearsFrame(source: string, frame: string, managerFrame: string): boolean {
    const direct = pageTags(source).some((tag) => new RegExp(`\\bframe=(?:"${frame}"|\\{['"]${frame}['"]\\})`).test(tag));
    if (direct) return true;
    const viaManager = /<ManagerFrame(?=[\s/>])/.test(source) && pageTags(managerFrame).some((tag) => new RegExp(`\\bframe=(?:"${frame}"|\\{['"]${frame}['"]\\})`).test(tag));
    return viaManager;
}

function rootOf(page: MenuPage): string {
    const root = ROOTS[page.id];
    if (!root) throw new Error(`menu page "${page.id}" has no root in ROOTS`);
    return root;
}

function unframed(pages: readonly MenuPage[]): string[] {
    const managerFrame = read(MANAGER_FRAME);
    return pages.filter((p) => !wearsFrame(read(rootOf(p)), p.frame, managerFrame)).map((p) => p.id);
}

function svelteFiles(dir = ''): string[] {
    const out: string[] = [];
    for (const entry of readdirSync(`${SRC}${dir}`, { withFileTypes: true })) {
        const rel = `${dir}${entry.name}`;
        if (entry.isDirectory()) out.push(...svelteFiles(`${rel}/`));
        else if (entry.name.endsWith('.svelte')) out.push(rel);
    }
    return out;
}

const frameless = (source: string): string[] => pageTags(source).filter((tag) => !/\bframe=/.test(tag));

describe('menu pages wear their frames', () => {
    test('the scan sees the pages (a check that looked at nothing proves nothing)', () => {
        expect(MENU_PAGES.length).toBeGreaterThanOrEqual(20);
        expect(MENU_PAGES.every((p) => (PAGE_FRAMES as readonly string[]).includes(p.frame))).toBe(true);
    });

    test('every menu page has a root here, and every root names a menu page', () => {
        expect(MENU_PAGES.filter((p) => !ROOTS[p.id]).map((p) => p.id)).toEqual([]);
        expect(Object.keys(ROOTS).filter((id) => !MENU_PAGES.some((p) => p.id === id))).toEqual([]);
    });

    test('every menu page wears its declared frame', () => {
        expect(unframed(MENU_PAGES), 'a page does not wear its declared frame').toEqual([]);
    });

    test('every <Page> under web/src passes a frame (the prop is required since slice S11)', () => {
        const files = svelteFiles();
        const withPage = files.filter((rel) => pageTags(read(rel)).length > 0);
        expect(withPage.length, 'the scan found no <Page> at all').toBeGreaterThanOrEqual(15);
        const missing = withPage.flatMap((rel) => frameless(read(rel)).map((tag) => `${rel}: ${tag.slice(0, 80)}`));
        expect(missing).toEqual([]);
    });

    test('negative control: a page with no frame, the wrong frame, or a missing root goes red', () => {
        expect(wearsFrame('<Page title="a" class="x">', 'column', '')).toBe(false);
        expect(wearsFrame('<Page title="a"\n  frame="nav">', 'column', '')).toBe(false);
        expect(wearsFrame('<Page title="a" onClose={() => go()} frame="column">', 'column', '')).toBe(true);
        expect(wearsFrame('<Page frame={\'canvas\'} title="a">', 'canvas', '')).toBe(true);
        expect(wearsFrame('<ManagerFrame title="a" />', 'column', '<Page title="b">')).toBe(false);
        expect(wearsFrame('<ManagerFrame title="a" />', 'column', '<Page title="b" frame="column">')).toBe(true);
        const noRoot: MenuPage = { ...MENU_PAGES[0]!, id: 'planted' };
        expect(() => unframed([noRoot])).toThrow(/no root/);
        ROOTS['planted'] = 'lib/menu-page/no-such-root.svelte';
        try {
            expect(() => unframed([noRoot])).toThrow();
        } finally {
            delete ROOTS['planted'];
        }
    });

    test('negative control: a <Page> with no frame is found, one with a frame is not', () => {
        expect(frameless('<Page title="a" embedded>x</Page>')).toHaveLength(1);
        expect(frameless('<Page title="a"\n  frame="column">x</Page>')).toEqual([]);
        expect(frameless('<Self {title} frame="nav" />')).toEqual([]);
    });

    test('negative control: a frameless <Page> is flagged, the same tag inside a comment is not', () => {
        expect(frameless('<div><Page bar>x</Page></div>')).toHaveLength(1);
        expect(frameless('<!-- fills the <Page bar> region -->')).toEqual([]);
        expect(frameless('// the <Page bar> region\nconst a = 1;')).toEqual([]);
        expect(frameless('/* the <Page bar>\n region */\nconst a = 1;')).toEqual([]);
        expect(frameless('const u = "https://x.test"; <Page bar>x</Page>')).toHaveLength(1);
    });
});
