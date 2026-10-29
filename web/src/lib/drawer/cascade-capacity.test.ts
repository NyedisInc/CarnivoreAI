/** @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';
import { isCollapsed, save, setCollapsedMany, toggleCollapsed } from './store';

describe('cascade close capacity', () => {
    it('keeps every descendant folded after a cascade close and a plain expand of the parent', () => {
        save([], [], []);
        const kids = Array.from({ length: 250 }, (_, i) => `p:${i + 1}`);
        setCollapsedMany(['companies', 'c:1', ...kids], []);
        expect(isCollapsed('companies')).toBe(true);
        toggleCollapsed('companies');
        expect(isCollapsed('companies')).toBe(false);
        for (const k of ['c:1', ...kids]) expect(isCollapsed(k), k).toBe(true);
    });
});
