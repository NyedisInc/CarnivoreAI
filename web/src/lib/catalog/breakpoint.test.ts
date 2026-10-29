import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

/** The repo root, from this file. */
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');

const DIR = path.join(ROOT, 'web/src/lib/catalog');

/* the phone layout */
const PHONE_BREAKPOINT = '767px';

const COMPONENTS = fs
    .readdirSync(DIR)
    .filter((name) => name.endsWith('.svelte'))
    .sort();

function styleOf(component: string): string {
    const source = fs.readFileSync(path.join(DIR, component), 'utf8');
    const start = source.indexOf('<style>');
    return start === -1 ? '' : source.slice(start);
}

function phoneBlock(css: string, width: string = PHONE_BREAKPOINT): string {
    const head = `@media (max-width: ${width})`;
    const at = css.indexOf(head);
    if (at === -1) return '';
    const open = css.indexOf('{', at);
    if (open === -1) return '';
    let depth = 0;
    for (let i = open; i < css.length; i += 1) {
        if (css[i] === '{') depth += 1;
        else if (css[i] === '}') {
            depth -= 1;
            if (depth === 0) return css.slice(open + 1, i);
        }
    }
    return '';
}

describe('D1 - every component on this surface stacks at the same width', () => {
    test('the catalog authors more than a dozen components, so this is worth holding', () => {
        expect(COMPONENTS.length).toBeGreaterThan(12);
    });

    test('no component names any width other than the one breakpoint', () => {
        const offenders: string[] = [];
        for (const component of COMPONENTS) {
            const widths = [...styleOf(component).matchAll(/max-width:\s*(\d+px)/g)].map(
                (match) => match[1],
            );
            for (const width of widths) {
                if (width !== PHONE_BREAKPOINT) offenders.push(`${component}: ${width}`);
            }
        }
        expect(offenders).toEqual([]);
    });

    test('and the components that have a phone layout actually name it', () => {
        // NEGATIVE CONTROL for
        const withPhoneRules = COMPONENTS.filter((component) =>
            styleOf(component).includes('max-width:'),
        );
        expect(withPhoneRules.length).toBeGreaterThan(12);
        for (const component of withPhoneRules) {
            expect(styleOf(component), component).toContain(
                `@media (max-width: ${PHONE_BREAKPOINT})`,
            );
        }
    });

    test('each one says where the number came from, so nobody re-picks it', () => {
        for (const component of COMPONENTS.filter((name) => styleOf(name).includes('max-width:'))) {
            expect(styleOf(component), component).toContain('--cat-bp');
        }
    });
});

describe('D2 - every consequential control shows focus through the shared edge', () => {
    const COMPONENTS_WITH_CONSEQUENCE = [
        'DetailActions.svelte',
        'ConfirmSheet.svelte',
        'ConsentScripts.svelte',
        'OneShotPicker.svelte',
        'AutoUpdateSwitch.svelte',
    ];
    const FOCUS_CSS = fs.readFileSync(path.join(DIR, '../../opscenter/focus.css'), 'utf8');

    test('focus.css brightens the own edge a little, adds no shadow, and draws no outline', () => {
        expect(FOCUS_CSS).toMatch(/:focus-visible/);
        expect(FOCUS_CSS).toMatch(/outline:\s*none !important/);
        expect(FOCUS_CSS).toMatch(/border-color:\s*var\(--_fbd\) !important/);
        expect(FOCUS_CSS).not.toMatch(/box-shadow:\s*inset/);
        expect(FOCUS_CSS).toMatch(/--oc-focus-lift/);
    });

    for (const component of COMPONENTS_WITH_CONSEQUENCE) {
        test(`${component} draws no focus outline of its own`, () => {
            expect(styleOf(component), component).not.toMatch(/:focus-visible\s*\{[^}]*outline:\s*\d/);
        });
    }
});

describe('D3 - a thumb can hit every consequential control', () => {
    const TARGETS: Array<[string, RegExp]> = [
        ['CatalogToolbar.svelte', /min-height:\s*44px/],
        ['ConsentScripts.svelte', /min-height:\s*44px/],
        ['ConfirmSheet.svelte', /min-height:\s*44px/],
        ['OneShotPicker.svelte', /min-height:\s*44px/],
        ['AutoUpdateSwitch.svelte', /min-height:\s*44px/],
        ['InstallChoices.svelte', /min-height:\s*44px/],
        ['InstallSheet.svelte', /min-height:\s*44px/],
    ];

    for (const [component, rule] of TARGETS) {
        test(`${component} sizes its controls for a thumb at phone width`, () => {
            const block = phoneBlock(styleOf(component));
            expect(block, component).toMatch(rule);
        });
    }

    test('the screen\'s own buttons are the shared `.oc-btn`, thumb-sized in the primitive', () => {
        const controls = fs.readFileSync(path.join(ROOT, 'web/src/opscenter/controls.css'), 'utf8');
        const block = phoneBlock(controls, '1023px');
        expect(block).toContain('.oc-btn');
        expect(block).toMatch(/min-height:\s*44px/);
    });

    test('the block reader refuses a component that has no phone block', () => {
        // NEGATIVE CONTROL for
        expect(phoneBlock('.a { color: red; }')).toBe('');
        expect(phoneBlock(`@media (max-width: ${PHONE_BREAKPOINT}) { .a { b: c; } }`)).toContain(
            '.a { b: c; }',
        );
    });
});
