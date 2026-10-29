import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, test } from 'vitest';
import { cssRules } from './css-rules';

describe('Switch label floor', () => {
    test('.oc-check keeps at least its own content width so a flex neighbor cannot clip the label', () => {
        const css = readFileSync(resolve(__dirname, '../../opscenter/controls.css'), 'utf8');
        const rule = cssRules(css).find((r) => r.selector === '.oc-check');
        expect(rule?.decls['min-width']).toBe('min-content');
    });
});
