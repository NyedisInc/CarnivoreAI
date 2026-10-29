import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { parseLimits, parseRules } from './api-author';

function golden(name: string): unknown {
    return JSON.parse(readFileSync(resolve(__dirname, '../../../../tests/fixtures/publish_page', name), 'utf-8'));
}

describe('author route contracts', () => {
    it('parses limits.json with every field defined', () => {
        const limits = parseLimits(golden('limits.json'));
        for (const [key, value] of Object.entries(limits)) expect(value, key).not.toBeNull();
        expect(limits.media_per_day).toBe(5);
        expect(limits.cooldown_until).toBe('2026-11-11T17:46:40Z');
    });

    it('parses rules.json: four tabs, every cap a number', () => {
        const rules = parseRules(golden('rules.json'));
        expect(rules.kinds.map((k) => k.kind)).toEqual(['skills', 'themes', 'mods', 'plugins']);
        expect(rules.kinds.every((k) => k.open)).toBe(true);
        const raw = golden('rules.json') as { caps: Record<string, number> };
        expect(Object.keys(rules.caps).sort()).toEqual(Object.keys(raw.caps).sort());
        expect(rules.caps.hero_max_bytes).toBe(524288);
        expect(rules.caps.hero_ratio_min).toBe(1.5);
        expect(rules.caps.mod_members).toBe(200);
    });
});
