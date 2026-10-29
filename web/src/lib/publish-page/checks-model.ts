import type { ReportFinding, ReportGate, SubmissionReport } from '../catalog/publish';
import { cleanRoomSkipExpected, cleanRoomSkipped } from './kinds';
import { failedCount, GATE_IDS, gatesById, resultOf, type CheckResult, type GateId } from './report-format';

export const FINDINGS_SHOWN = 5;
export const FILL_MS = 380;

export interface CheckCell {
    id: GateId;
    result: CheckResult;
    code: string;
    fix: string;
    findings: ReportFinding[];
}

export type ChecksPhase = 'not_started' | 'running' | 'done';

export function phaseOf(gateState: string | undefined, hasReport: boolean): ChecksPhase {
    if (hasReport) return 'done';
    if (gateState === 'received') return 'not_started';
    return gateState === 'gating' ? 'running' : 'done';
}

export function buildCells(report: SubmissionReport | null, running: boolean, shown: number = GATE_IDS.length): CheckCell[] {
    const by = gatesById((report?.gates ?? []) as (ReportGate & { n?: number })[]);
    return GATE_IDS.map((id, index) => {
        const row = by.get(id);
        if (index >= shown) return { id, result: 'running', code: '', fix: '', findings: [] };
        return {
            id,
            result: resultOf(row, running && !report),
            code: row?.code ?? '',
            fix: row?.fix ?? '',
            findings: row?.findings ?? [],
        };
    });
}

export function summaryOf(cells: readonly CheckCell[], phase: ChecksPhase): { key: string; params: Record<string, number> } | null {
    if (phase === 'running') return { key: 'publish.page.checks.summary_running', params: {} };
    if (phase === 'not_started') return { key: 'publish.page.checks.summary_not_started', params: {} };
    const results = cells.map((c) => c.result);
    const failed = failedCount(results);
    if (failed > 0) return { key: 'publish.page.checks.summary_failed', params: { count: failed } };
    return results.every((r) => r === 'passed' || r === 'note' || r === 'skipped') ? { key: 'publish.page.checks.summary_passed', params: {} } : null;
}

export const defaultOpen = (result: CheckResult): boolean => result === 'did_not_pass';

export function shownFindings(findings: readonly ReportFinding[], all: boolean): { shown: ReportFinding[]; hidden: number } {
    if (all || findings.length <= FINDINGS_SHOWN) return { shown: [...findings], hidden: 0 };
    return { shown: findings.slice(0, FINDINGS_SHOWN), hidden: findings.length - FINDINGS_SHOWN };
}

export function mentionSkipped(report: SubmissionReport | null, kind: string | null | undefined): boolean {
    return report ? cleanRoomSkipped(report) : cleanRoomSkipExpected({ kind });
}

export function fillPlan(input: { observed: boolean; reducedMotion: boolean }): { steps: number[]; intervalMs: number } {
    const total = GATE_IDS.length;
    if (!input.observed || input.reducedMotion) return { steps: [total], intervalMs: 0 };
    return { steps: Array.from({ length: total }, (_, i) => i + 1), intervalMs: FILL_MS };
}

export interface StoredFacts {
    grade: string;
    files: number | null;
    bytes: number | null;
}

export function storedFacts(record: { grade?: string; files?: number | null; bytes?: number | null }): StoredFacts {
    return { grade: record.grade ?? '', files: record.files ?? null, bytes: record.bytes ?? null };
}

export const storedCodes = (summary: string): string[] => summary.split(',').map((code) => code.trim()).filter(Boolean);

export function storedRows(record: { summary: string; findings?: { code: string; path: string }[] }): { code: string; path: string }[] {
    const rows = (record.findings ?? []).filter((f) => f.code).map((f) => ({ code: f.code, path: f.path ?? '' }));
    const covered = new Set(rows.map((r) => r.code));
    return [...rows, ...storedCodes(record.summary).filter((code) => !covered.has(code)).map((code) => ({ code, path: '' }))];
}
