import { describe, expect, test } from 'vitest';
import { hiddenCount, visibleProfiles } from './visibility';
import type { ProfileRow } from './api';

const row = (id: string, installed?: boolean): ProfileRow => ({ id, installed } as ProfileRow);

describe('visibleProfiles', () => {
    const rows = [row('claude-default', true), row('codex-default', false), row('old-server')];
    test('hides installed:false and keeps true and an absent flag (an older server)', () => {
        expect(visibleProfiles(rows).map((r) => r.id)).toEqual(['claude-default', 'old-server']);
    });
    test('show hidden brings every row back, in order', () => {
        expect(visibleProfiles(rows, { showHidden: true }).map((r) => r.id)).toEqual(['claude-default', 'codex-default', 'old-server']);
    });
    test('a row the caller keeps (the open profile, a restart preselect) stays even when hidden', () => {
        expect(visibleProfiles(rows, { keep: ['codex-default'] }).map((r) => r.id)).toContain('codex-default');
    });
    test('hiddenCount counts what the switch would reveal', () => {
        expect(hiddenCount(rows)).toBe(1);
    });
});
