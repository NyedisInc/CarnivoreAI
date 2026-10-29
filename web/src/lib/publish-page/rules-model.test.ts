import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { parseLimits, parseRules } from './api-author';
import { kindPanel, limitSentences, limitsLine } from './rules-model';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);
const golden = (name: string): unknown => JSON.parse(readFileSync(new URL(`../../../../tests/fixtures/publish_page/${name}.json`, import.meta.url), 'utf8'));
const NOW = Date.parse('2026-10-24T12:00:00Z');

describe('the limits line', () => {
    it('names the new account rule for a new account and drops it for a settled one', () => {
        const settled = parseLimits(golden('limits'));
        expect(limitsLine(settled, t)).toBe('2 of 5 today, 3 of 3 open');
        const fresh = parseLimits({ ...(golden('limits') as object), new_account: true });
        expect(limitsLine(fresh, t)).toBe('2 of 1 today (new accounts get 1 a day for 7 days), 3 of 3 open');
    });
    it('a new account reads its own cap, not the standard one (X5-6)', () => {
        const fresh = parseLimits({ ...(golden('limits') as object), new_account: true, used_today: 0 });
        expect(limitsLine(fresh, t)).toBe('0 of 1 today (new accounts get 1 a day for 7 days), 3 of 3 open');
    });
    it('is empty when the answer lacks a number, never a guess', () => {
        expect(limitsLine(parseLimits({ per_day: 5 }), t)).toBe('');
    });
});

describe('the limits sentences', () => {
    it('lists every sentence of the golden answer, the cooldown and the image cap included', () => {
        const lines = limitSentences(parseLimits(golden('limits')), t, NOW);
        expect(lines).toEqual([
            '5 submissions a day, 3 open at once.',
            'accounts under 7 days old get 1 a day.',
            'a rejected submission can be appealed 2 times.',
            '3 rejections in 30 days starts a 30 day cooldown.',
            '5 images a day, on top of the sends.',
            '3 of 3 rejections in the last 30 days.',
            'sending is paused until 11 nov.',
            'when a limit holds a send, the button says why, right beside it.',
        ]);
    });
    it('leaves out what the answer did not say and a cooldown already over', () => {
        const lines = limitSentences(parseLimits({ per_day: 5, open_max: 3, cooldown_until: '2026-10-01T00:00:00Z' }), t, NOW);
        expect(lines).toEqual(['5 submissions a day, 3 open at once.', 'when a limit holds a send, the button says why, right beside it.']);
    });
});

describe('the kinds panel', () => {
    it('lists the four kinds in order with their copy and folder', () => {
        const rows = kindPanel(parseRules(golden('rules')), t);
        expect(rows.map((r) => r.tab)).toEqual(['skills', 'themes', 'mods', 'plugins']);
        expect(rows.every((r) => r.open)).toBe(true);
        expect(rows[0]?.text).toBe('a SKILL.md folder an agent loads on demand. one folder, SKILL.md with name and description, up to 1 MiB, scripts allowed. read from your skills folder.');
    });
    it('shows a closed kind with the closed sentence', () => {
        const body = golden('rules') as { kinds: { kind: string; open: boolean }[] };
        const rows = kindPanel(parseRules({ ...body, kinds: body.kinds.map((k) => (k.kind === 'mods' ? { ...k, open: false } : k)) }), t);
        const mods = rows.find((r) => r.tab === 'mods');
        expect(mods?.open).toBe(false);
        expect(mods?.text).toBe(t('publish.page.kinds.closed', { kind: t('publish.page.tab.mods') }));
    });
    it('is empty when the rules were not read', () => {
        expect(kindPanel(null, t)).toEqual([]);
    });
});
