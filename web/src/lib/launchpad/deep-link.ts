import { derivedDisplayName } from '../sessions/session-label';
import type { RunningSessionRow } from '../sessions/types';

export function findRunningSessionBySlug(
    rows: readonly RunningSessionRow[] | null | undefined,
    target: string,
): RunningSessionRow | null {
    const all = rows || [];
    const wanted = String(target ?? '');
    const bySlug =
        all.find((row) => derivedDisplayName(row.name ?? null) === wanted) ||
        all.find(
            (row) =>
                (derivedDisplayName(row.name ?? null) || '').toLowerCase() ===
                wanted.toLowerCase(),
        );
    if (bySlug) return bySlug;

    const trimmed = wanted.trim();
    if (!trimmed) return null;
    const byLabel =
        all.find((row) => typeof row.label === 'string' && row.label.trim() === trimmed) ||
        all.find(
            (row) =>
                typeof row.label === 'string' &&
                row.label.trim().toLowerCase() === trimmed.toLowerCase(),
        );
    return byLabel || null;
}
