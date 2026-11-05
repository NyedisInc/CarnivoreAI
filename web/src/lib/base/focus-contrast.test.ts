import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from 'vitest';

type Rgb = [number, number, number];

const read = (rel: string): string => readFileSync(new URL(rel, import.meta.url), 'utf8');
const TOKENS = read('../../opscenter/tokens.css');
const ELEMENTS = read('./elements.css');
const FOCUS = read('../../opscenter/focus.css');
const THEMES_DIR = new URL('../../../../client/css/themes/', import.meta.url);

const MIN_RATIO = 3;
const GROUNDS = ['--oc-ground-page', '--oc-ground-panel', '--oc-ground-raised', '--oc-ground-card', '--oc-ground-hover', '--oc-ground-titlerow', '--oc-ground-field'];
const BORDERED_BASES: Record<string, string> = {
    secondary: '--oc-line-button', field: '--oc-line-control', confirm: '--oc-orange', danger: '--oc-coral',
};
const LIFT_EXPR = 'oklch(from var(--oc-ground-page) clamp(0, (var(--oc-light-line-l) - l) * 1000, 1) 0 0)';

function splitArgs(s: string): string[] {
    const out: string[] = [];
    let depth = 0;
    let cur = '';
    for (const ch of s) {
        if (ch === '(') depth++;
        if (ch === ')') depth--;
        if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = ''; } else cur += ch;
    }
    out.push(cur.trim());
    return out;
}

function hex(s: string): Rgb {
    const h = s.slice(1);
    if (h.length !== 3 && h.length !== 6) throw new Error(`unsupported color ${s}`);
    const full = h.length === 3 ? [...h].map((c) => c + c).join('') : h;
    if (!/^[0-9a-fA-F]{6}$/.test(full)) throw new Error(`unsupported color ${s}`);
    return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255) as Rgb;
}

const toLinear = (c: number): number => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const fromLinear = (c: number): number => Math.min(1, Math.max(0, c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055));

function toOklab(rgb: Rgb): Rgb {
    const [r, g, b] = rgb.map(toLinear);
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}

function fromOklab([L, a, b]: Rgb): Rgb {
    const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
    const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
    const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
    return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s].map(fromLinear) as Rgb;
}

function luminance(rgb: Rgb): number {
    const [r, g, b] = rgb.map(toLinear);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: Rgb, b: Rgb): number {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
}

function mix(space: string, a: Rgb, b: Rgb, pa: number): Rgb {
    const [x, y] = space === 'oklab' ? [toOklab(a), toOklab(b)] : [a, b];
    const m = x.map((v, i) => v * pa + y[i] * (1 - pa)) as Rgb;
    return space === 'oklab' ? fromOklab(m) : m;
}

function themedTokenBlock(): Map<string, string> {
    const start = TOKENS.indexOf('[data-session-theme] {');
    const end = TOKENS.indexOf('\n}', start);
    const map = new Map<string, string>();
    const body = TOKENS.slice(start, end).replace(/\/\*[\s\S]*?\*\//g, '');
    for (const m of body.matchAll(/^\s*(--[\w-]+):\s*([^;]+);/gm)) map.set(m[1], m[2].trim().replace(/\s+/g, ' '));
    return map;
}

const BLOCK = themedTokenBlock();

function evaluate(expr: string, theme: Record<string, string>): Rgb {
    const e = expr.trim();
    if (e.startsWith('#')) return hex(e);
    const call = /^(var|color-mix)\((.*)\)$/.exec(e);
    if (!call) throw new Error(`cannot evaluate: ${e}`);
    const args = splitArgs(call[2]);
    if (call[1] === 'var') {
        const [name, fallback] = args;
        const value = theme[name] ?? BLOCK.get(name) ?? fallback;
        if (value === undefined) throw new Error(`unresolved ${name}`);
        if (name === '--oc-focus-lift' || value === LIFT_EXPR) return lift(theme);
        return evaluate(value, theme);
    }
    const space = args[0].replace(/^in\s+/, '');
    const share = (arg: string): [string, number | null] => {
        const m = /^(.*?)\s+(\d+(?:\.\d+)?)%$/.exec(arg);
        return m && !m[1].endsWith('(') ? [m[1], Number(m[2]) / 100] : [arg, null];
    };
    const [ea, pa] = share(args[1]);
    const [eb, pb] = share(args[2]);
    const shareA = pa ?? (pb === null ? 0.5 : 1 - pb);
    return mix(space, evaluate(ea, theme), evaluate(eb, theme), shareA);
}

function lightLine(): number {
    const found = /--oc-light-line-l:\s*([\d.]+);/.exec(TOKENS);
    if (!found) throw new Error('tokens.css declares no --oc-light-line-l');
    return Number(found[1]);
}

function lift(theme: Record<string, string>): Rgb {
    const l = toOklab(evaluate('var(--oc-ground-page)', theme))[0];
    return fromOklab([Math.min(1, Math.max(0, (lightLine() - l) * 1000)), 0, 0]);
}

function btnFocusOf(selector: string): string {
    const m = new RegExp(`:where\\(${selector.replace(/[[\]()']/g, '\\$&')}\\) \\{[^}]*?--_btn-focus:\\s*([^;]+);`).exec(ELEMENTS);
    if (!m) throw new Error(`no --_btn-focus in the ${selector} block`);
    return m[1].trim();
}

function themes(): Array<[string, Record<string, string>]> {
    return readdirSync(THEMES_DIR)
        .filter((d) => existsSync(new URL(`${d}/theme.json`, THEMES_DIR)))
        .map((d) => [d, JSON.parse(readFileSync(new URL(`${d}/theme.json`, THEMES_DIR), 'utf8')).cssVars ?? {}]);
}

function focusBases(): Record<string, string> {
    const bases: Record<string, string> = {
        quiet: btnFocusOf("[data-btn='quiet']"), row: btnFocusOf("[data-btn='row']"),
    };
    for (const [name, token] of Object.entries(BORDERED_BASES)) bases[name] = `var(${token})`;
    return bases;
}

function worstRatio(base: string, theme: Record<string, string>, keep = sharedKeep(), grounds = GROUNDS): number {
    const edge = mix('oklab', evaluate(base, theme), lift(theme), keep);
    return Math.min(...grounds.map((g) => contrast(edge, evaluate(`var(${g})`, theme))));
}

function sharedKeep(): number {
    return Number(/--oc-focus-keep:\s*(\d+)%/.exec(TOKENS)?.[1]) / 100;
}

const OVERRIDES: Array<[string, string, string]> = [
    ['page-tabs', '../../opscenter/ui/tabs.css', '.oc-ptab {'],
    ['command-bar', '../../opscenter/layouts/LayoutCommandBar.svelte', 'The focus edge lifts FROM'],
    ['review-prompt', '../../cplugs/reviewboard/tray.css', '.rb-prompt {'],
];

function overrideOf(file: string, anchor: string): { base: string; keep: number } {
    return overrideIn(read(file), anchor, file);
}

function overrideIn(src: string, anchor: string, label: string): { base: string; keep: number } {
    const at = src.indexOf(anchor);
    if (at < 0) throw new Error(`anchor ${anchor} not found in ${label}`);
    const end = src.indexOf('}', at);
    const block = src.slice(at, end < 0 ? undefined : end);
    const bd = /--_bd:\s*([^;]+);/.exec(block);
    if (!bd) throw new Error(`no --_bd after ${anchor} in ${label}`);
    const keep = /--oc-focus-keep:\s*(\d+)%/.exec(block);
    return { base: bd[1].trim(), keep: keep ? Number(keep[1]) / 100 : sharedKeep() };
}

test('the evaluator reproduces the hairline numbers measured before the fix (carnivore, page ground 2.69:1, worst ground 2.48:1)', () => {
    const carnivore = Object.fromEntries(themes()).carnivore;
    expect(worstRatio('var(--oc-line-rule)', carnivore, sharedKeep(), ['--oc-ground-page'])).toBeCloseTo(2.69, 1);
    expect(worstRatio('var(--oc-line-rule)', carnivore)).toBeCloseTo(2.48, 1);
});

test('negative control: a keep written before --_bd is still found', () => {
    expect(overrideIn('.x { --oc-focus-keep: 90%; --_bd: red; }', '.x {', 'x')).toEqual({ base: 'red', keep: 0.9 });
    expect(overrideIn('.x { --_bd: red; --oc-focus-keep: 90%; }', '.x {', 'x').keep).toBe(0.9);
    expect(overrideIn('.x { --_bd: red; } .y { --oc-focus-keep: 90%; }', '.x {', 'x').keep).toBe(sharedKeep());
});

test('negative control: an alpha hex or a transparent base is refused, never measured as opaque', () => {
    expect(() => evaluate('#11223344', {})).toThrow(/unsupported color/);
    expect(() => evaluate('#1122', {})).toThrow(/unsupported color/);
    expect(evaluate('#112233', {})).toEqual(evaluate('#123', {}));
    expect(() => evaluate('transparent', {})).toThrow(/cannot evaluate/);
});

test('the one focus rule still mixes the border hue toward the lift by the keep share', () => {
    expect(FOCUS).toContain('color-mix(in oklab, var(--_bd, currentColor) var(--oc-focus-keep, 75%), var(--oc-focus-lift, currentColor))');
    expect(TOKENS).toContain(`--oc-focus-lift: ${LIFT_EXPR};`);
});

test('every variant keeps a 3:1 focus edge on every shipped theme', () => {
    const all = themes();
    expect(all.length).toBeGreaterThanOrEqual(12);
    const bases = focusBases();
    const overrides = OVERRIDES.map(([label, file, anchor]) => [label, overrideOf(file, anchor)] as const);
    const table: string[] = [`theme            ${[...Object.keys(bases), ...overrides.map(([l]) => l)].map((v) => v.padEnd(14)).join('')}`];
    const failures: string[] = [];
    for (const [id, vars] of all) {
        const cells = Object.entries(bases).map(([variant, base]) => {
            const ratio = worstRatio(base, vars);
            if (ratio < MIN_RATIO) failures.push(`${id} ${variant} ${ratio.toFixed(2)}:1`);
            return ratio.toFixed(2).padEnd(14);
        });
        for (const [label, { base, keep }] of overrides) {
            const ratio = worstRatio(base, vars, keep);
            if (ratio < MIN_RATIO) failures.push(`${id} ${label} ${ratio.toFixed(2)}:1`);
            cells.push(ratio.toFixed(2).padEnd(14));
        }
        table.push(`${id.padEnd(17)}${cells.join('')}`);
    }
    if (process.env.FOCUS_TABLE) process.stdout.write(`${table.join('\n')}\n`);
    expect(failures).toEqual([]);
});

const SRC = new URL('../../', import.meta.url);

const TEXT_INK = 'currentColor';
const NO_BASE = 'a transparent base leaves only the 25% lift as the lit edge; not measured here, a finding for the owning lane';

const EXEMPT: Record<string, string> = {
    'lib/base/elements.css|var(--_btn-focus, var(--_btn-edge))': 'the base button\'s own dispatch; every variant it resolves to is in the table above',
    'lib/manager-frame/manager-card.css|var(--pl-line-panel)': 'a page palette token (--pl-*) set at run time, not in tokens.css or a theme',
    'lib/manager-frame/manager-card.css|var(--pl-line)': 'a page palette token (--pl-*) set at run time, not in tokens.css or a theme',
    'lib/markdown-editor/MarkdownEditor.svelte|var(--oc-control-line)': 'a token with no definition in tokens.css; finding for the editor\'s lane',
    'cplugs/save/RestorePoints.svelte|color-mix(in srgb, var(--oc-cyan) 65%, transparent)': NO_BASE,
    'lib/swarm-board/SwarmBoard.svelte|transparent': NO_BASE,
    'cplugs/huddle/swarm/SwarmOrg.svelte|transparent': NO_BASE,
    'cplugs/huddle/HuddleViewSwitch.svelte|transparent': NO_BASE,
    'cplugs/huddle/chat/ChatAskForm.svelte|transparent': NO_BASE,
    'cplugs/huddle/TaskManagerMarkerFilter.svelte|transparent': NO_BASE,
};

const KNOWN_BELOW: Record<string, string> = {
    'lib/swarm-board/SwarmBoard.svelte|var(--oc-line-rule)': 'swarm board, the owner\'s lane: 1.90:1 on dracula',
    'lib/swarm-board/views/CalendarView.svelte|var(--oc-line-rule)': 'swarm board, the owner\'s lane: 1.90:1 on dracula',
    'lib/swarm-board/views/SwimlanesView.svelte|var(--oc-line-rule)': 'swarm board, the owner\'s lane: 1.90:1 on dracula',
    'lib/swarm-board/views/swimlanes/SwimLane.svelte|var(--oc-line-rule)': 'swarm board, the owner\'s lane: 1.90:1 on dracula',
    'lib/swarm-board/views/TimelineView.svelte|var(--oc-line-rule)': 'swarm board, the owner\'s lane: 1.90:1 on dracula',
    'cplugs/huddle/HuddleBody.svelte|var(--oc-line-rule)': 'task manager lead\'s lane: 1.90:1 on dracula',
};

function declaredBd(): Map<string, number> {
    const found = new Map<string, number>();
    const files = readdirSync(SRC, { recursive: true, encoding: 'utf8' }).filter((f) => /\.(css|svelte|ts)$/.test(f) && !/\.test\.ts$/.test(f));
    for (const f of files) {
        const text = readFileSync(new URL(f, SRC), 'utf8').replace(/\/\*[\s\S]*?\*\/|<!--[\s\S]*?-->/g, '');
        for (const m of text.matchAll(/--_bd:\s*([^;}]+)[;}]/g)) {
            const key = `${relative(fileURLToPath(SRC), fileURLToPath(new URL(f, SRC)))}|${m[1].trim().replace(/\s+/g, ' ')}`;
            found.set(key, (found.get(key) ?? 0) + 1);
        }
    }
    return found;
}

function worstOverThemes(value: string): number | null {
    try {
        return Math.min(...themes().map(([, vars]) => worstRatio(value, vars)));
    } catch (e) {
        if (e instanceof Error && /cannot evaluate|unresolved|unsupported/.test(e.message)) return null;
        throw e;
    }
}

test('every --_bd declaration in web/src is measured, covered by OVERRIDES, or named with a reason', () => {
    const covered = new Set(OVERRIDES.map(([, file]) => file.replace('../../', '')));
    const problems: string[] = [];
    const named = new Set<string>();
    for (const key of declaredBd().keys()) {
        const [file, value] = key.split('|');
        if (covered.has(file) || value === TEXT_INK) continue;
        const ratio = worstOverThemes(value);
        if (ratio === null || ratio < MIN_RATIO) {
            named.add(key);
            if (!EXEMPT[key] && !KNOWN_BELOW[key]) problems.push(`${ratio === null ? 'unmeasurable' : `${ratio.toFixed(2)}:1`} and not named: ${key}`);
        }
    }
    for (const key of [...Object.keys(EXEMPT), ...Object.keys(KNOWN_BELOW)]) {
        if (!named.has(key)) problems.push(`stale list entry (measured fine or gone, remove it): ${key}`);
    }
    expect(problems).toEqual([]);
});

test('the declaration scan sees the sites the review named (it cannot pass by looking at nothing)', () => {
    const keys = [...declaredBd().keys()];
    for (const needle of [
        'opscenter/cells/files/Cell.svelte|var(--oc-yellow)', 'opscenter/shell/PopoutBarActions.svelte|var(--oc-cyan)',
        'cplugs/devwidgetlab/lab-frame.css|var(--oc-orange)', 'cplugs/huddle/HuddleReply.svelte|var(--oc-orange)',
        'cplugs/huddle/TaskManagerRowPosts.svelte|currentColor',
    ]) {
        expect(keys).toContain(needle);
    }
});
