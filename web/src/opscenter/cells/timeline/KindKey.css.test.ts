import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test } from 'vitest';

test('the key button does not shrink and sets its own focus edge', () => {
    const text = readFileSync(resolve(process.cwd(), 'src/opscenter/cells/timeline/KindKey.svelte'), 'utf8');
    const rule = text.match(/\.tlx-key__btn \{([^}]*)\}/)![1];
    expect(rule).toMatch(/flex:\s*none;/);
    expect(rule).toMatch(/--_btn-focus:\s*var\(--oc-text-secondary\);/);
});
