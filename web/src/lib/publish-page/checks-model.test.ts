import { describe, expect, it } from 'vitest';
import type { ReportGate, SubmissionReport } from '../catalog/publish';
import { buildCells, defaultOpen, fillPlan, mentionSkipped, phaseOf, shownFindings, storedCodes, storedFacts, storedRows, summaryOf, FILL_MS, FINDINGS_SHOWN } from './checks-model';
import { GATE_IDS } from './report-format';

const gate = (id: string, verdict: string, code = '', findings: ReportGate['findings'] = [], extra: Record<string, unknown> = {}): ReportGate =>
    ({ id, verdict, code, fix: verdict === 'fail' ? 'fix it' : '', findings, ...extra }) as ReportGate;
const full = (over: Record<string, ReportGate> = {}): SubmissionReport => ({
    outcome: 'pass',
    gates: GATE_IDS.map((id) => over[id] ?? gate(id, 'pass')),
});

describe('the 12 checks model', () => {
    it('lists the cells in the D4 order', () => {
        expect(buildCells(full(), false).map((c) => c.id)).toEqual([...GATE_IDS]);
    });

    it('reads a gate missing from the report as not run yet, never passed', () => {
        const report: SubmissionReport = { outcome: '', gates: GATE_IDS.slice(0, 5).map((id) => gate(id, 'pass')) };
        const results = buildCells(report, false).map((c) => c.result);
        expect(results.slice(0, 5)).toEqual(Array(5).fill('passed'));
        expect(results.slice(5)).toEqual(Array(7).fill('not_run'));
    });

    it('puts a report_scan row under its source gate as did not pass', () => {
        const report = full();
        report.gates[6] = gate('report_scan', 'undetermined', 'report_secret', [], { n: 7 });
        const cells = buildCells(report, false);
        expect(cells[6]?.id).toBe('secrets');
        expect(cells[6]?.result).toBe('did_not_pass');
        expect(cells.some((c) => (c.id as string) === 'report_scan')).toBe(false);
    });

    it('reads a cplug clean room skipped_by_policy as skipped and sets the mention', () => {
        const report = full({ clean_room: gate('clean_room', 'advisory', 'skipped_by_policy') });
        expect(buildCells(report, false)[10]?.result).toBe('skipped');
        expect(mentionSkipped(report, 'cplug')).toBe(true);
        expect(mentionSkipped(null, 'cplug')).toBe(true);
    });

    it('reads a failed clean room of a Claude Code plugin as did not pass with no mention', () => {
        const report = full({ clean_room: gate('clean_room', 'fail', 'sandbox_error') });
        expect(buildCells(report, false)[10]?.result).toBe('did_not_pass');
        expect(mentionSkipped(report, 'plugin')).toBe(false);
        expect(mentionSkipped(null, 'plugin')).toBe(false);
        expect(mentionSkipped(null, 'mod')).toBe(false);
    });

    it('shows five findings and then "show n more"', () => {
        const findings = Array.from({ length: 8 }, (_, i) => ({ code: `c${i}` }));
        expect(FINDINGS_SHOWN).toBe(5);
        expect(shownFindings(findings, false)).toEqual({ shown: findings.slice(0, 5), hidden: 3 });
        expect(shownFindings(findings, true)).toEqual({ shown: findings, hidden: 0 });
        expect(shownFindings(findings.slice(0, 5), false).hidden).toBe(0);
    });

    it('opens failures by default and nothing else', () => {
        expect(defaultOpen('did_not_pass')).toBe(true);
        for (const r of ['passed', 'note', 'skipped', 'not_run', 'running'] as const) expect(defaultOpen(r)).toBe(false);
    });

    it('draws every cell running while gating, with a summary that has no count', () => {
        const phase = phaseOf('gating', false);
        expect(phase).toBe('running');
        const cells = buildCells(null, true);
        expect(cells.every((c) => c.result === 'running')).toBe(true);
        const sum = summaryOf(cells, phase);
        expect(sum).toEqual({ key: 'publish.page.checks.summary_running', params: {} });
        expect(phaseOf('received', false)).toBe('not_started');
        expect(summaryOf(buildCells(null, false), 'not_started')?.key).toBe('publish.page.checks.summary_not_started');
    });

    it('summarises a finished report', () => {
        const bad = buildCells(full({ license: gate('license', 'fail', 'license_missing'), secrets: gate('secrets', 'undetermined') }), false);
        expect(summaryOf(bad, 'done')).toEqual({ key: 'publish.page.checks.summary_failed', params: { count: 2 } });
        expect(summaryOf(buildCells(full(), false), 'done')?.key).toBe('publish.page.checks.summary_passed');
        expect(summaryOf(buildCells(full({ clean_room: gate('clean_room', 'advisory', 'skipped_by_policy') }), false), 'done')?.key).toBe('publish.page.checks.summary_passed');
        expect(summaryOf(buildCells({ outcome: '', gates: [gate('structure', 'pass')] }, false), 'done')).toBeNull();
    });

    it('masks the cells not yet filled as running', () => {
        const cells = buildCells(full({ license: gate('license', 'fail'), ai_review: gate('ai_review', 'fail') }), false, 8);
        expect(cells[6]?.result).toBe('passed');
        expect(cells[7]?.result).toBe('did_not_pass');
        expect(cells.slice(8).every((c) => c.result === 'running')).toBe(true);
    });

    it('fills one step per 380 ms only after an observed gating-to-report transition', () => {
        expect(FILL_MS).toBe(380);
        expect(fillPlan({ observed: true, reducedMotion: false })).toEqual({ steps: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], intervalMs: 380 });
        expect(fillPlan({ observed: true, reducedMotion: true })).toEqual({ steps: [12], intervalMs: 0 });
        expect(fillPlan({ observed: false, reducedMotion: false })).toEqual({ steps: [12], intervalMs: 0 });
    });
});

describe('a stored local check (X5-10)', () => {
    it('keeps GRADE and FILES from the record when this visit has no preview', () => {
        expect(storedFacts({ grade: 'A', files: 6, bytes: 12044 })).toEqual({ grade: 'A', files: 6, bytes: 12044 });
    });

    it('a record made before the facts were kept reads grade empty and files null, never zero', () => {
        expect(storedFacts({})).toEqual({ grade: '', files: null, bytes: null });
    });

    it('splits a refused summary into codes only', () => {
        expect(storedCodes('secret_found, license_missing')).toEqual(['secret_found', 'license_missing']);
        expect(storedCodes('')).toEqual([]);
    });

    it('draws a finding with its path and a summary code no finding covers as a bare code', () => {
        expect(storedRows({ summary: 'secret_found, license_missing', findings: [{ code: 'secret_found', path: 'a.sh' }] })).toEqual([
            { code: 'secret_found', path: 'a.sh' },
            { code: 'license_missing', path: '' },
        ]);
        expect(storedRows({ summary: 'x' })).toEqual([{ code: 'x', path: '' }]);
    });
});
