export type StageKey = 'submitted' | 'in_review' | 'approved' | 'rejected';

export const STAGES: readonly StageKey[] = ['submitted', 'in_review', 'approved', 'rejected'];

export interface StageSource {
    status: string;
    gate_state?: string | null;
    media_only?: boolean;
    appeals_left?: number | null;
}

const REJECTED = new Set(['gate_failed', 'rejected', 'revoked']);

export function stageOf(row: StageSource): StageKey | null {
    if (row.media_only) return null;
    if (REJECTED.has(row.status)) return 'rejected';
    if (row.status === 'approved' || row.status === 'published') return 'approved';
    if (row.status === 'publishing') return 'in_review';
    if (row.status === 'pending') return row.gate_state === 'received' ? 'submitted' : 'in_review';
    return null;
}

export function versionStage(row: StageSource): StageKey | null {
    return row.status === 'superseded' && !row.media_only ? 'approved' : stageOf(row);
}

export function isOpen(row: StageSource): boolean {
    return !row.media_only && (row.status === 'pending' || row.status === 'approved' || row.status === 'publishing');
}

export function canWithdraw(row: StageSource): boolean {
    return !row.media_only && (row.status === 'pending' || row.status === 'approved');
}

export function stageKey(stage: StageKey): string {
    return `publish.page.stage.${stage}`;
}

export type FolderPhase = 'none' | 'checked' | 'refused';

export function rowWord(latest: StageSource | null, phase: FolderPhase = 'none'): string {
    const stage = latest ? stageOf(latest) : null;
    if (phase === 'checked' && (!latest || !isOpen(latest))) return 'publish.page.row.checked_ready';
    if (phase === 'refused') return 'publish.page.row.check_failed';
    if (!stage) return 'publish.page.row.on_computer';
    return stageKey(stage);
}

export const BUCKETS = ['needs_you', 'submitted', 'in_review', 'approved', 'rejected'] as const;
export type Bucket = (typeof BUCKETS)[number];

export function bucketOf(row: StageSource): Bucket {
    if (row.status === 'gate_failed' || (row.status === 'rejected' && (row.appeals_left ?? 0) > 0)) return 'needs_you';
    return stageOf(row) ?? 'rejected';
}

export function bucketKey(bucket: Bucket): string {
    return bucket === 'needs_you' ? 'publish.page.group.needs_you' : stageKey(bucket);
}
