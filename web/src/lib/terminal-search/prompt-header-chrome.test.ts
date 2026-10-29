import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, test } from 'vitest';

const repoRoot = fileURLToPath(new URL('../../../..', import.meta.url));

function read(rel: string): string {
    return fs.readFileSync(path.join(repoRoot, rel), 'utf8');
}

const component = read('web/src/lib/terminal-search/PromptHeader.svelte');
const tokens = read('web/src/opscenter/tokens.css');

const barRule = (() => {
    const start = component.indexOf('\n      .prompt-header {');
    expect(start, 'the .prompt-header rule moved or was renamed').toBeGreaterThan(-1);
    const end = component.indexOf('}', start);
    return component.slice(start, end);
})();

const previewRule = (() => {
    const start = component.indexOf('\n      .prompt-header__preview {');
    expect(start, 'the .prompt-header__preview rule moved or was renamed').toBeGreaterThan(-1);
    const end = component.indexOf('}', start);
    return component.slice(start, end);
})();

describe('the bar is painted in chrome tokens, not the terminal palette', () => {
    test('its ground is the card surface, never the page ground the terminal shares', () => {
        expect(barRule).toContain('background: var(--oc-ground-card)');
        expect(barRule).not.toContain('--oc-ground-page');
    });

    test('its hairline is the lit edge, mixed into the title row’s rule', () => {
        expect(barRule).toContain('border-bottom: 1px solid var(--oc-strip-edge)');
        expect(barRule).not.toContain('--oc-line-faint');
        expect(tokens).toContain(
            '--oc-strip-edge: color-mix(in oklab, var(--oc-orange) 55%, var(--oc-line-rule))',
        );
    });

    test('its type is the chrome label size and the chrome text tier', () => {
        expect(barRule).toContain('font-size: var(--oc-fs-label)');
        expect(barRule).toContain('color: var(--oc-text-secondary)');
        expect(previewRule).toContain('color: var(--oc-text-secondary)');
        expect(previewRule).not.toContain('--oc-text-primary');
    });

    test('THE SECOND WRITER NAMES THE SAME TWO TOKENS', () => {
        // on the terminal screen
        const legacy = read('client/css/terminal-carnivore.css');
        const start = legacy.indexOf('#terminal-screen .prompt-header {');
        expect(start, 'the legacy prompt-header override moved or was renamed').toBeGreaterThan(-1);
        const rule = legacy.slice(start, legacy.indexOf('}', start));
        expect(rule).toContain('background: var(--cv-ground-card)');
        expect(rule).toContain('border-color: var(--cv-strip-edge)');
        expect(legacy).toContain('--cv-ground-card: var(--oc-ground-card)');
        expect(legacy).toContain('--cv-strip-edge: var(--oc-strip-edge)');
    });

    test('NEGATIVE: the component still writes no colour literal of its own', () => {
        const style = component.slice(component.lastIndexOf('<style>'));
        const declarations = style.replace(/\/\*[\s\S]*?\*\//g, '');
        const literals = declarations.match(/#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab)\(/g);
        expect(literals, `colour literals in PromptHeader.svelte: ${literals}`).toBeNull();
    });

    test('--oc-ground-card resolves to the theme’s own card surface', () => {
        expect(tokens).toContain('--oc-ground-card: var(--color-bg-card,');
    });
});

describe('the ground stays opaque over a session background picture', () => {
    const manifests = fs
        .readdirSync(path.join(repoRoot, 'client/css/themes'), { withFileTypes: true })
        .filter((e) => e.isDirectory())
        .map((e) => path.join('client/css/themes', e.name, 'theme.json'))
        .filter((rel) => fs.existsSync(path.join(repoRoot, rel)))
        .map((rel) => ({
            id: path.basename(path.dirname(rel)),
            vars: (JSON.parse(read(rel)).cssVars ?? {}) as Record<string, string>,
        }));

    test('the population is the real fleet, not an empty glob', () => {
        expect(manifests.length).toBeGreaterThanOrEqual(12);
    });

    test('every theme declares --color-bg-card as a fully opaque colour', () => {
        const bad = manifests
            .map((m) => [m.id, m.vars['--color-bg-card']] as const)
            .filter(([, v]) => !(typeof v === 'string' && /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(v)));
        expect(bad, `themes whose card ground is missing or translucent: ${JSON.stringify(bad)}`)
            .toEqual([]);
    });
});


describe('the strip has a lit lower edge, and casts nothing onto the pane', () => {
    const shadow = (barRule.match(/box-shadow:([^;]*);/)?.[1] ?? '')
        .replace(/\s+/g, ' ')
        .trim();

    const layers = shadow.split(',').map((l) => l.trim()).filter(Boolean);

    function lengths(layer: string): number[] {
        return (layer.replace(/var\([^)]*\)/g, '').match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);
    }

    test('it is one layer, inset, drawn from the glow token', () => {
        expect(shadow, 'the bar declares no box-shadow at all').not.toBe('');
        expect(layers).toHaveLength(1);
        expect(layers[0]).toContain('inset');
        expect(layers[0]).toContain('var(--oc-strip-glow)');
    });

    test('NEGATIVE: nothing at all is cast outside the box', () => {
        expect(layers.length, 'no shadow layers to judge').toBeGreaterThan(0);
        const outer = layers.filter((l) => !l.includes('inset'));
        expect(outer, `outer shadow layers: ${JSON.stringify(outer)}`).toEqual([]);
    });

    test('the inset hugs the bottom edge and pulls in before it blurs', () => {
        const nums = lengths(layers[0] ?? '');
        expect(nums, `expected x/y/blur/spread: ${layers[0]}`).toHaveLength(4);
        const [x, y, blur, spread] = nums as [number, number, number, number];
        expect(x, 'no sideways offset').toBe(0);
        expect(y, 'the inset must rise from the BOTTOM edge').toBeLessThan(0);
        expect(blur, 'an unblurred inset is a band, not a glow').toBeGreaterThan(0);
        expect(spread, 'spread must pull in').toBeLessThan(0);
        expect(Math.abs(y) + blur / 2 + spread, `inset reach: ${layers[0]}`).toBeLessThanOrEqual(12);
    });

    test('both tokens are weak mixes of the accent, not colours of their own', () => {
        const glow = tokens.match(
            /--oc-strip-glow: color-mix\(in oklab, var\(--oc-orange\) (\d+)%, transparent\)/,
        );
        expect(glow, '--oc-strip-glow is not an accent mix into transparent').not.toBeNull();
        const pct = Number((glow as RegExpMatchArray)[1] ?? NaN);
        expect(pct).toBeGreaterThan(0);
        expect(pct).toBeLessThan(45);
        // nothing.
        expect(tokens).toContain('--oc-strip-edge: color-mix(in oklab, var(--oc-orange) 55%');
        expect(tokens).not.toContain('--oc-strip-edge: color-mix(in oklab, var(--oc-orange) 55%, transparent)');
        // of its own -
        expect(tokens.match(/--oc-strip-glow:/g) ?? []).toHaveLength(2);
        expect(tokens.match(/--oc-strip-edge:/g) ?? []).toHaveLength(2);
    });

    test('NEGATIVE: the edge is static, and the second writer does not own it', () => {
        expect(barRule).not.toMatch(/transition|animation/);
        const legacy = read('client/css/terminal-carnivore.css');
        const start = legacy.indexOf('#terminal-screen .prompt-header {');
        expect(start, 'the legacy override is gone, so this proves nothing')
            .toBeGreaterThan(-1);
        const rule = legacy.slice(start, legacy.indexOf('}', start));
        expect(rule).toContain('.prompt-header');
        expect(rule).not.toContain('box-shadow');
    });
});
