import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { sessionSummaryLabel } from '../../../../client/js/labels/session-summary.js';

const repoRoot = fileURLToPath(new URL('../../../..', import.meta.url));

interface Summary { summarizeStates(rows: unknown[]): { inner: string; outer: string; bucket: string; total: number };
    summaryLabel(s: unknown): string }

function load(): Summary {
    const context: Record<string, unknown> = { console, CloudeI18n: createI18n(), CloudeLabels: { sessionSummaryLabel } };
    vm.createContext(context);
    for (const f of ['status-led.js', 'session-status-summary.js']) {
        vm.runInContext(fs.readFileSync(path.join(repoRoot, 'client', 'js', f), 'utf8'), context);
    }
    return context['SessionStatusSummary'] as Summary;
}

describe('group roll-up of asleep members', () => {
    const S = load();
    test('every member asleep reads the sleeping moon, not unknown', () => {
        const s = S.summarizeStates([{ status: 'asleep' }, { status: 'asleep', unread: true }]);
        expect(s.inner).toBe('asleep');
        expect(s.outer).toBe('off');
        expect(s.bucket).toBe('asleep');
        expect(S.summaryLabel(s)).toBe('sleeping - 2 sessions, 1 unread');
    });
    test('any measured live state still outranks asleep, and dead outranks it too', () => {
        expect(S.summarizeStates([{ status: 'asleep' }, { status: 'idle' }]).bucket).toBe('done');
        expect(S.summarizeStates([{ status: 'asleep' }, { status: 'dead' }]).bucket).toBe('dead');
    });
    test('an empty or unmeasured group is still unknown', () => {
        expect(S.summarizeStates([]).inner).toBe('unknown');
        expect(S.summarizeStates([{}]).inner).toBe('unknown');
    });
});
