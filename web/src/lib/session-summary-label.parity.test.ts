import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

import { createI18n } from '../../../client/js/i18n/runtime.js';
import { sessionSummaryLabel } from '../../../client/js/labels/session-summary.js';
import { summaryLabel } from './session-summary-label';

const repoRoot = fileURLToPath(new URL('../../..', import.meta.url));

interface I18nLike {
    t(key: string, params?: Record<string, unknown> | null): string;
    setLocale(next: string): boolean;
    readonly locale: string;
}

interface LegacySummary {
    summaryHtml(children: unknown[], opts?: unknown): string;
    summaryLabel(summary: unknown): string;
    summarizeStates(children: unknown[]): Record<string, unknown>;
}

function legacySummary(i18n: I18nLike): LegacySummary {
    const context: Record<string, unknown> = {
        console,
        CloudeI18n: i18n,
        CloudeLabels: { sessionSummaryLabel },
    };
    vm.createContext(context);
    for (const file of ['status-led.js', 'session-status-summary.js']) {
        const src = fs.readFileSync(path.join(repoRoot, 'client', 'js', file), 'utf8');
        vm.runInContext(src, context);
    }
    return context['SessionStatusSummary'] as LegacySummary;
}

const BUCKETS = [
    'permission',
    'input',
    'working',
    'unread',
    'done',
    'dead',
    'unknown',
    'a-bucket-from-2030',
];

const TOTALS = [0, 1, 2, 3, 19, 1234];

describe('the legacy tree and the compiled tree render one sentence', () => {
    test('over the whole bucket x total x unread matrix', () => {
        const i18n = createI18n({ locale: 'en' }) as I18nLike;
        const legacy = legacySummary(i18n);
        const t = (k: string, p?: Record<string, unknown> | null) => i18n.t(k, p);
        let compared = 0;
        for (const bucket of BUCKETS) {
            for (const total of TOTALS) {
                for (const unreadCount of [0, 1, 2, total]) {
                    const summary = { bucket, total, unreadCount };
                    expect(
                        summaryLabel(summary, t),
                        `bucket=${bucket} total=${total} unread=${unreadCount}`,
                    ).toBe(legacy.summaryLabel(summary));
                    compared++;
                }
            }
        }
        expect(compared).toBe(BUCKETS.length * TOTALS.length * 4);
        expect(compared).toBeGreaterThan(150);
    });

    test('and they agree in the pseudo locale too, so both really read the catalog', () => {
        const i18n = createI18n({ locale: 'pseudo' }) as I18nLike;
        const legacy = legacySummary(i18n);
        const t = (k: string, p?: Record<string, unknown> | null) => i18n.t(k, p);
        const summary = { bucket: 'working', total: 2, unreadCount: 1 };
        const mine = summaryLabel(summary, t);
        expect(mine).toBe(legacy.summaryLabel(summary));
        expect(mine).toContain('⟦');
    });

    test('NEGATIVE CONTROL: the comparison can actually fail', () => {
        const i18n = createI18n({ locale: 'en' }) as I18nLike;
        const legacy = legacySummary(i18n);
        const t = (k: string, p?: Record<string, unknown> | null) => i18n.t(k, p);
        expect(summaryLabel({ bucket: 'working', total: 1, unreadCount: 0 }, t)).not.toBe(
            legacy.summaryLabel({ bucket: 'working', total: 2, unreadCount: 0 }),
        );
    });
});

describe('the copy on screen did not move', () => {
    const PRE_PORT: Array<[{ bucket: string; total: number; unreadCount: number }, string]> = [
        [{ bucket: 'unknown', total: 0, unreadCount: 0 }, 'no sessions'],
        [{ bucket: 'working', total: 1, unreadCount: 0 }, 'working - 1 session'],
        [{ bucket: 'working', total: 2, unreadCount: 0 }, 'working - 2 sessions'],
        [{ bucket: 'unread', total: 2, unreadCount: 1 }, 'unread - 2 sessions, 1 unread'],
        [{ bucket: 'permission', total: 19, unreadCount: 3 }, 'permission - 19 sessions, 3 unread'],
        [{ bucket: 'done', total: 1, unreadCount: 1 }, 'done - 1 session, 1 unread'],
        [{ bucket: 'dead', total: 3, unreadCount: 0 }, 'dead - 3 sessions'],
        [{ bucket: 'input', total: 2, unreadCount: 2 }, 'input - 2 sessions, 2 unread'],
    ];

    test('every pre-port sentence is reproduced byte for byte', () => {
        const i18n = createI18n({ locale: 'en' }) as I18nLike;
        const t = (k: string, p?: Record<string, unknown> | null) => i18n.t(k, p);
        for (const [summary, expected] of PRE_PORT) {
            expect(summaryLabel(summary, t), JSON.stringify(summary)).toBe(expected);
        }
    });

    test('the legacy summaryHtml still puts that sentence in the LED title', () => {
        const i18n = createI18n({ locale: 'en' }) as I18nLike;
        const legacy = legacySummary(i18n);
        const html = legacy.summaryHtml([
            { activity_status: 'idle', unread: true },
            { activity_status: 'working' },
        ]);
        expect(html).toContain('title="working - 2 sessions, 1 unread"');
    });

    test('and the empty group still says so honestly', () => {
        const i18n = createI18n({ locale: 'en' }) as I18nLike;
        const legacy = legacySummary(i18n);
        expect(legacy.summaryHtml([])).toContain('title="no sessions"');
    });
});
