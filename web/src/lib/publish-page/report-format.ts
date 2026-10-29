import type { ReportFinding, ReportGate } from '../catalog/publish';

export const GATE_IDS = [
    'structure', 'schema', 'kind_rules', 'identity', 'digest', 'static_scans',
    'secrets', 'license', 'dependencies', 'ai_review', 'clean_room', 'grade',
] as const;
export type GateId = (typeof GATE_IDS)[number];

export type CheckResult = 'passed' | 'did_not_pass' | 'note' | 'skipped' | 'not_run' | 'running';

export const gateLabelKey = (gate: GateId): string => `publish.page.check.${gate}.label`;

export const gateLooksAtKey = (gate: GateId): string => `publish.page.check.${gate}.looks_at`;

export const resultKey = (result: CheckResult): string => `publish.page.result.${result}`;

export function isGateId(id: string): id is GateId {
    return (GATE_IDS as readonly string[]).includes(id);
}

export function resultOf(gate: ReportGate | undefined, running = false): CheckResult {
    if (!gate) return running ? 'running' : 'not_run';
    if (gate.id === 'clean_room' && gate.code === 'skipped_by_policy') return 'skipped';
    switch (gate.verdict) {
        case 'pass': return 'passed';
        case 'advisory': return 'note';
        case 'fail':
        case 'undetermined': return 'did_not_pass';
        default: return 'not_run';
    }
}

export function gatesById(gates: readonly (ReportGate & { n?: number })[]): Map<GateId, ReportGate> {
    const out = new Map<GateId, ReportGate>();
    for (const gate of gates) {
        const id = isGateId(gate.id) ? gate.id : typeof gate.n === 'number' && gate.n >= 1 && gate.n <= 12 ? GATE_IDS[gate.n - 1] : null;
        if (id && !out.has(id)) out.set(id, gate);
    }
    return out;
}

export function resultsOf(gates: readonly ReportGate[] | null, running = false): CheckResult[] {
    const by = gatesById(gates ?? []);
    return GATE_IDS.map((id) => resultOf(by.get(id), running && !gates));
}

export const failedCount = (results: readonly CheckResult[]): number => results.filter((r) => r === 'did_not_pass').length;

export const passedCount = (results: readonly CheckResult[]): number => results.filter((r) => r === 'passed').length;

export function findingLine(finding: ReportFinding): string {
    const where = finding.path ? `${finding.path}${typeof finding.line === 'number' && finding.line > 0 ? `:${finding.line}` : ''}` : '';
    return where ? `${finding.code}  ${where}` : finding.code;
}

export function findingSentence(finding: ReportFinding, t: (key: string, params?: Record<string, unknown>) => string): string {
    if (!finding.path) return finding.code;
    return typeof finding.line === 'number' && finding.line > 0
        ? t('skill.publish.report.finding', { code: finding.code, path: finding.path, line: finding.line })
        : t('skill.publish.report.finding_path', { code: finding.code, path: finding.path });
}

export interface IdentPart {
    text: string;
    tok: boolean;
    wbr: boolean;
}

export function identParts(text: string): IdentPart[] {
    const out: IdentPart[] = [];
    for (const piece of text.split(/(\s+)/)) {
        if (!piece) continue;
        if (/\s/.test(piece) || !/[-/]/.test(piece)) {
            out.push({ text: piece, tok: false, wbr: false });
            continue;
        }
        const slashes = piece.split('/').length - 1;
        const isPath = slashes >= 2 || /\/[^/]*\.[A-Za-z0-9]+[^A-Za-z0-9]*$/.test(piece);
        const segments = isPath ? piece.split(/(?<=\/)/) : [piece];
        segments.forEach((text, i) => out.push({ text, tok: true, wbr: i < segments.length - 1 }));
    }
    return out;
}
