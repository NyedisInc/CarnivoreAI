import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const WEB_SRC = path.resolve(__dirname, '..', '..');
const CLIENT_JS = path.resolve(WEB_SRC, '..', '..', 'client', 'js');

const OWNER = 'lib/sidebar-shell/Band.svelte';

const KNOWN: Record<string, string> = {
    'lib/sidebar-shell/SidebarRow.svelte': 'layout members body',
};

const HAND_DRAWN = /\bsession-sidebar-group(?![-\w])|\bsession-sidebar-group__body\b/;

const HEADING_OWNER = 'lib/sidebar-shell/Heading.svelte';

const HEADING_KNOWN: Record<string, string> = {
    'opscenter/layout-editor/DrawerList.svelte': 'layout editor type fold (moved by the split, bc20325e5)',
    'lib/settings-page/mcp-panel/McpToolSwitchesPanel.svelte': 'settings fold',
};

const HEADING_DRAWN = /\bsession-sidebar-group__(?:headerrow|menu)\b/;
const HEADING_BUILT = /class=\\?["'][^"']*\bsession-sidebar-group__(?:headerrow|menu)\b/;

function filesUnder(dir: string, base: string, exts: string[]): string[] {
    const out: string[] = [];
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) out.push(...filesUnder(full, base, exts));
        else if (exts.some((e) => entry.name.endsWith(e)) && !/\.test\.|\.spec\./.test(entry.name)) {
            out.push(path.relative(base, full).split(path.sep).join('/'));
        }
    }
    return out;
}

function svelteFiles(dir: string): string[] {
    return filesUnder(dir, WEB_SRC, ['.svelte']);
}

function markupOf(source: string): string {
    return source
        .replace(/<!--[\s\S]*?-->/g, '')
        .replace(/<script[\s\S]*?<\/script>/g, '')
        .replace(/<style[\s\S]*?<\/style>/g, '');
}

export function drawsHeading(file: string, source: string): boolean {
    return file.endsWith('.svelte')
        ? HEADING_DRAWN.test(markupOf(source)) || HEADING_BUILT.test(source)
        : HEADING_BUILT.test(source);
}

export function drawsBand(source: string): boolean {
    return HAND_DRAWN.test(markupOf(source));
}

describe('band conformance', () => {
    const offenders = svelteFiles(WEB_SRC)
        .filter((f) => f !== OWNER)
        .filter((f) => drawsBand(fs.readFileSync(path.join(WEB_SRC, f), 'utf8')));

    it('no file but Band.svelte draws a band wrapper or body by hand', () => {
        expect(offenders.filter((f) => !(f in KNOWN))).toEqual([]);
    });
    it('every KNOWN row still applies (the list only shrinks)', () => {
        expect(Object.keys(KNOWN).filter((f) => !offenders.includes(f))).toEqual([]);
    });
    it('can go red: a hand-drawn wrapper and body are seen, a heading class and a comment are not', () => {
        expect(drawsBand('<div class="session-sidebar-group session-sidebar-pack" role="group"></div>')).toBe(true);
        expect(drawsBand('<div class="session-sidebar-group__body"></div>')).toBe(true);
        expect(drawsBand('<div class={x ? \'session-sidebar-group\' : \'y\'}></div>')).toBe(true);
        expect(drawsBand('<button class="session-sidebar-group__header"></button>')).toBe(false);
        expect(drawsBand('<!-- the session-sidebar-group wrapper --><Band />')).toBe(false);
        expect(drawsBand('<Band kind="session-sidebar-group--nested" />')).toBe(false);
    });
});

describe('heading conformance', () => {
    const web = filesUnder(WEB_SRC, WEB_SRC, ['.svelte', '.ts', '.js'])
        .filter((f) => f !== HEADING_OWNER && drawsHeading(f, fs.readFileSync(path.join(WEB_SRC, f), 'utf8')));
    const legacy = filesUnder(CLIENT_JS, CLIENT_JS, ['.js'])
        .filter((f) => drawsHeading(f, fs.readFileSync(path.join(CLIENT_JS, f), 'utf8')))
        .map((f) => `client/js/${f}`);
    const offenders = [...web, ...legacy];

    it('no file but Heading.svelte draws a heading row or a heading kebab', () => {
        expect(offenders.filter((f) => !(f in HEADING_KNOWN))).toEqual([]);
    });
    it('every HEADING_KNOWN row still applies (the list only shrinks)', () => {
        expect(Object.keys(HEADING_KNOWN).filter((f) => !offenders.includes(f))).toEqual([]);
    });
    it('can go red: a retired builder\'s string and a hand-drawn row are seen, a selector lookup is not', () => {
        expect(drawsHeading('x.js', `'<button type="button" class="oc-ibtn oc-ibtn--bare session-sidebar-group__menu" '`)).toBe(true);
        expect(drawsHeading('x.svelte', '<div class="session-sidebar-group__headerrow"></div>')).toBe(true);
        expect(drawsHeading('x.js', "row.closest('.session-sidebar-group__headerrow')")).toBe(false);
        expect(drawsHeading('x.svelte', '<!-- a session-sidebar-group__menu --><Heading h={h} />')).toBe(false);
    });
});

const CHIP_OWNER = 'lib/sidebar-shell/RowChip.svelte';
const CHIP_SCOPE = 'lib/sidebar-shell';
const CHIP_SPREAD = /<(?:span|button)\s+\{\.\.\.[\w.?]+\}\s*>/;
const CHIP_CLASS = /class=\\?["'][^"'{]*\bsession-sidebar-row-(?:provider|share|keep-awake|agents-icon|shells-icon|timers-icon|automations-icon|wake-icon|workflow-icon|archived-icon|pin)\b/;

const CHIP_KNOWN: Record<string, string> = {
    'lib/sidebar-shell/AgentTabMarks.svelte': 'tab strip marks',
    'client/js/session-sidebar-row-controls.js': 'legacy pin builder',
    'client/js/session-sidebar-layouts.js': 'layout row glyph',
    'client/js/sidebar-help.js': 'help specimen',
};

export function drawsChip(file: string, source: string): boolean {
    if (!file.endsWith('.svelte')) return CHIP_CLASS.test(source);
    const markup = markupOf(source);
    return (file.startsWith(CHIP_SCOPE) && CHIP_SPREAD.test(markup)) || CHIP_CLASS.test(markup);
}

describe('row chip conformance', () => {
    const web = filesUnder(WEB_SRC, WEB_SRC, ['.svelte', '.ts', '.js'])
        .filter((f) => f !== CHIP_OWNER && drawsChip(f, fs.readFileSync(path.join(WEB_SRC, f), 'utf8')));
    const legacy = filesUnder(CLIENT_JS, CLIENT_JS, ['.js'])
        .filter((f) => drawsChip(f, fs.readFileSync(path.join(CLIENT_JS, f), 'utf8')))
        .map((f) => `client/js/${f}`);
    const offenders = [...web, ...legacy];

    it('no file but RowChip.svelte draws a row chip', () => {
        expect(offenders.filter((f) => !(f in CHIP_KNOWN))).toEqual([]);
    });
    it('every CHIP_KNOWN row still applies (the list only shrinks)', () => {
        expect(Object.keys(CHIP_KNOWN).filter((f) => !offenders.includes(f))).toEqual([]);
    });
    it('can go red: a spread chip and a hand-written chip class are seen, a comparison and a lookup are not', () => {
        expect(drawsChip('lib/sidebar-shell/X.svelte', '<span {...p.wake.attrs}>{@html p.wake.svg}</span>')).toBe(true);
        expect(drawsChip('lib/sidebar-shell/X.svelte', '<button {...p.popOut}><svg></svg></button>')).toBe(true);
        expect(drawsChip('lib/x/Y.svelte', '<span class="session-sidebar-row-share" role="img"></span>')).toBe(true);
        expect(drawsChip('x.js', `'<button type="button" class="session-sidebar-row-pin" '`)).toBe(true);
        expect(drawsChip('lib/x/Y.svelte', "<span class=\"sp {m === 'session-sidebar-row-agents-icon' ? 'a' : 'b'}\"></span>")).toBe(false);
        expect(drawsChip('x.ts', "row.querySelector('.session-sidebar-row-pin')")).toBe(false);
        expect(drawsChip('lib/sidebar-shell/X.svelte', '<RowChip chip={p.wake} />')).toBe(false);
    });
});

const CONTROL_OWNERS = ['lib/item-menu/row-context.ts', 'client/js/session-row-actions.js'];
const CONTROL_CLASS = /class=\\?["'][^"'{]*\bsession-row-(?:menu-trigger|action)\b/;
const CONTROL_STRING = /\btriggerHtml\(|\bactions\.html\(|\{@html [\w.?]*(?:menuHtml|actionHtml)\}/;

const CONTROL_KNOWN: Record<string, string> = {
    'lib/sidebar-shell/SessionRow.svelte': 'ghost leader kebab',
};

export function drawsControl(file: string, source: string): boolean {
    const body = file.endsWith('.svelte') ? markupOf(source) : source;
    return CONTROL_CLASS.test(body) || (file.startsWith(CHIP_SCOPE) && CONTROL_STRING.test(source));
}

describe('row action and menu trigger conformance', () => {
    const web = filesUnder(WEB_SRC, WEB_SRC, ['.svelte', '.ts', '.js'])
        .filter((f) => !CONTROL_OWNERS.includes(f))
        .filter((f) => drawsControl(f, fs.readFileSync(path.join(WEB_SRC, f), 'utf8')));
    const legacy = filesUnder(CLIENT_JS, CLIENT_JS, ['.js'])
        .map((f) => `client/js/${f}`)
        .filter((f) => !CONTROL_OWNERS.includes(f))
        .filter((f) => drawsControl(f, fs.readFileSync(path.join(CLIENT_JS, f.slice('client/js/'.length)), 'utf8')));
    const offenders = [...web, ...legacy];

    it('no file but the two shared builders draws a row menu trigger or an inline action', () => {
        expect(offenders.filter((f) => !(f in CONTROL_KNOWN))).toEqual([]);
    });
    it('every CONTROL_KNOWN row still applies (the list only shrinks)', () => {
        expect(Object.keys(CONTROL_KNOWN).filter((f) => !offenders.includes(f))).toEqual([]);
    });
    it('can go red: a hand-drawn trigger, a built action and a string trigger in the list are seen, a lookup is not', () => {
        expect(drawsControl('lib/x/Y.svelte', '<button type="button" class="session-row-menu-trigger" data-row-menu="a"></button>')).toBe(true);
        expect(drawsControl('x.js', "'<button type=\"button\" class=\"session-row-action ' + cls")).toBe(true);
        expect(drawsControl('lib/sidebar-shell/X.svelte', '{@html p.menuHtml}')).toBe(true);
        expect(drawsControl('lib/sidebar-shell/row-plan.ts', 'host.menu.triggerHtml(ctx)')).toBe(true);
        expect(drawsControl('x.ts', "el.closest('.session-row-menu-trigger')")).toBe(false);
        expect(drawsControl('lib/sidebar-shell/X.svelte', '<RowMenuTrigger spec={p.menu} />')).toBe(false);
    });
});
