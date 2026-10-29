/* and the three */
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, test } from 'vitest';

const ROOT = resolve(__dirname, '../../../..');
const THEMES = resolve(ROOT, 'client/css/themes');
const MIN_CONTRAST = 3;
const MK2_WELLS = [0.09, 0.14, 0.18];

type Rgb = [number, number, number];

function rgb(hex: string): Rgb {
    const h = hex.replace('#', '');
    const channel = (i: number): number => parseInt(h.slice(i, i + 2), 16);
    return [channel(0), channel(2), channel(4)];
}

function mix(a: Rgb, b: Rgb, p: number): Rgb {
    return [a[0] * (1 - p) + b[0] * p, a[1] * (1 - p) + b[1] * p, a[2] * (1 - p) + b[2] * p];
}

function luminance(c: Rgb): number {
    const lin = (v: number): number => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    };
    const [r, g, b] = [lin(c[0]), lin(c[1]), lin(c[2])] as const;
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: Rgb, b: Rgb): number {
    const la = luminance(a);
    const lb = luminance(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

function tokenInkShare(name: string): number | null {
    const css = readFileSync(resolve(ROOT, 'web/src/opscenter/tokens.css'), 'utf8');
    const m = new RegExp(`${name}:\\s*color-mix\\(in srgb,\\s*var\\(--oc-ground-panel\\),\\s*var\\(--oc-text-primary\\)\\s*(\\d+)%\\)`).exec(css);
    return m ? Number(m[1]) / 100 : null;
}

const themeIds = readdirSync(THEMES, { withFileTypes: true })
    .filter((d) => d.isDirectory() && !d.name.startsWith('_'))
    .map((d) => d.name);

describe('the base button outline', () => {
    test('the base button and the chip draw their edge from the button line, not the hairline', () => {
        const base = readFileSync(resolve(__dirname, 'elements.css'), 'utf8');
        expect(base).toMatch(/--_btn-edge: var\(--oc-line-button\);/);
        expect(base).toMatch(/--_btn-edge-hover: var\(--oc-line-button-hover\);/);
        const chip = readFileSync(resolve(ROOT, 'web/src/opscenter/fields.css'), 'utf8');
        expect(chip).toMatch(/\.oc-chip \{[^}]*border: 1px solid var\(--oc-line-button\)/);
    });

    test('the button line is a mix of the panel ground toward the ink, and the hover line is brighter', () => {
        const rest = tokenInkShare('--oc-line-button');
        const hover = tokenInkShare('--oc-line-button-hover');
        expect(rest, '--oc-line-button must be a panel to ink color-mix').not.toBeNull();
        expect(hover, '--oc-line-button-hover must be a panel to ink color-mix').not.toBeNull();
        if (rest === null || hover === null) throw new Error('the button line tokens are not panel to ink color-mixes');
        expect(hover).toBeGreaterThan(rest);
    });

    test('there are shipped themes to measure', () => {
        expect(themeIds.length).toBeGreaterThanOrEqual(12);
    });

    describe.each(themeIds)('theme %s', (id) => {
        const vars = JSON.parse(readFileSync(resolve(THEMES, id, 'theme.json'), 'utf8')).cssVars as Record<string, string>;
        const themeColor = (key: string): Rgb => {
            const hex = vars[key];
            if (hex === undefined) throw new Error(`theme ${id} defines no ${key}`);
            return rgb(hex);
        };
        const panel = themeColor('--color-bg');
        const ink = themeColor('--color-fg');
        const grounds: Record<string, Rgb> = {
            panel,
            page: themeColor('--color-bg-page'),
            card: themeColor('--color-bg-card'),
            ...Object.fromEntries(MK2_WELLS.map((p) => [`mk2 well ${p}`, mix(panel, ink, p)])),
        };

        test.each(Object.keys(grounds))(`the button line reaches ${MIN_CONTRAST}:1 on the %s ground`, (name) => {
            const share = tokenInkShare('--oc-line-button');
            if (share === null) throw new Error('--oc-line-button must be a panel to ink color-mix');
            const ground = grounds[name];
            if (ground === undefined) throw new Error(`no ground named ${name}`);
            const edge = mix(panel, ink, share);
            expect(contrast(edge, ground)).toBeGreaterThanOrEqual(MIN_CONTRAST);
        });
    });
});
