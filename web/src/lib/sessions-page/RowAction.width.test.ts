import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';

const css = readFileSync(new URL('./sessions-list.css', import.meta.url), 'utf8');
const phone = css.slice(css.indexOf('@media (max-width: 700px)', css.indexOf('phone: the rail becomes chip rows')));

const ruleBody = (scope: string, selector: string): string => new RegExp(`\\n\\s+${selector.replace(/[[\]]/g, '\\$&')} \\{([^}]*)\\}`).exec(scope)?.[1] ?? '';

test('the phone row gives the action track its content width, never a fixed 64px', () => {
    expect(ruleBody(phone, '.sp-row')).toMatch(/grid-template-columns:[^;]*max-content/);
});

test('the action button never shrinks below its label', () => {
    const body = ruleBody(css, '.sp-tail [data-go]');
    expect(body).toMatch(/flex:\s*none/);
    expect(body).toMatch(/white-space:\s*nowrap/);
});

test('the action button is as wide as its label and never narrower than the column default', () => {
    expect(css).toMatch(/width:\s*auto;\s*min-width:\s*var\(--go-w\);\s*max-width:\s*none/);
});
