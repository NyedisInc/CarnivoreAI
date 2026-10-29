import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';

const css = readFileSync(new URL('./controls.css', import.meta.url), 'utf8');
const tokens = readFileSync(new URL('./tokens.css', import.meta.url), 'utf8');

function block(selector: string): string {
    const at = css.indexOf(`${selector} {`);
    expect(at, `${selector} rule exists`).toBeGreaterThan(-1);
    return css.slice(at, css.indexOf('}', at));
}

test('the type scale has a hint size, and hint text uses it', () => {
    expect(tokens).toMatch(/--oc-fs-hint:\s*11px/);
    expect(block('.oc-group__hint')).toContain('font-size: var(--oc-fs-hint');
    expect(block('.oc-choice__desc')).toContain('font-size: var(--oc-fs-hint');
});

test('controls never inherit the page font size', () => {
    for (const selector of ['.oc-check', '.oc-choice', '.oc-order__item']) {
        expect(block(selector), selector).toMatch(/font-size:\s*var\(--oc-fs-/);
    }
});

test('a group is two columns only in a wide PANE (container query), never by viewport', () => {
    expect(css).toContain('.oc-pane {\n    container: oc-pane / inline-size;');
    expect(css).toMatch(/@container oc-pane \(min-width: 820px\)\s*{\s*\.oc-group {\s*grid-template-columns: 190px/);
    expect(block('.oc-group')).toContain('grid-template-columns: minmax(0, 1fr)');
    expect(css).not.toMatch(/@media[^{]*{\s*\.oc-group\s*{/);
});

test('grids: three-up only when the main column is 600px, four-up auto-fills 140px cells', () => {
    expect(css).toMatch(/@container oc-main \(min-width: 600px\)\s*{\s*\.oc-grid-3 {\s*grid-template-columns: repeat\(3/);
    expect(css).toMatch(/\.oc-grid-4 {\s*grid-template-columns: repeat\(auto-fill, minmax\(140px, 1fr\)\)/);
});
