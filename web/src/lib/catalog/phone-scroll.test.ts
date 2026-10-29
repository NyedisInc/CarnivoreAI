import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

const SOURCE = fs
    .readFileSync(
        path.join(path.dirname(fileURLToPath(import.meta.url)), 'CatalogScreen.svelte'),
        'utf8',
    )
    .replace(/\/\*[\s\S]*?\*\//g, '');

function phoneBlock(css: string, width = '767px'): string {
    const at = css.indexOf(`@media (max-width: ${width})`, css.indexOf('<style>'));
    if (at === -1) return '';
    const open = css.indexOf('{', at);
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

function rule(css: string, selector: string): string {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const match = css.match(new RegExp(`(?:^|[}\\s])${escaped}\\s*\\{([^}]*)\\}`));
    return match?.[1] ?? '';
}

const PAGE_CSS = fs
    .readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '../../opscenter/page.css'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '');

describe('the catalog screen scrolls as one page on a phone', () => {
    const phone = phoneBlock(SOURCE);
    const framePhone = phoneBlock(PAGE_CSS, '1023px');

    test('the phone block exists, so the cases below read something', () => {
        expect(phone).toContain('.screen__body--reading');
    });

    test('the overlay is the scroller and keeps its overscroll to itself', () => {
        const screen = rule(framePhone, '.oc-page');
        expect(screen).toMatch(/overflow-y:\s*auto/);
        expect(screen).toMatch(/overscroll-behavior:\s*contain/);
    });

    test('the body sizes to its content instead of the height left over', () => {
        expect(rule(phone, '.screen__body')).toMatch(/flex:\s*none/);
    });
});
