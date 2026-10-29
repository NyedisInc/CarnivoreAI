import { reviewView, type ReviewShape, type ReviewVerdict } from './review';
import type { CatalogVersion } from './types';

export const TRUST_PREFIX_CHARS = 12;

export const TRUST_TEXT_CHARS = 80;

export interface TrustView {
    signerKey: string | null;
    reviewShape: ReviewShape;
    verdict: ReviewVerdict | null;
    overridden: boolean;
    overrideReason: string | null;
    digest: string | null;
    sourceRepo: string | null;
    sourceCommit: string | null;
    scripts: number | null;
}

function bounded(value: unknown, max: number): string | null {
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    return trimmed ? trimmed.slice(0, max) : null;
}

export function trustView(version: CatalogVersion | null): TrustView {
    const review = reviewView(version?.review ?? null);
    const src = (version?.src ?? null) as { repo?: unknown; commit?: unknown } | null;
    const digest = bounded(version?.digest, 64);
    const commit = bounded(src?.commit, 40);
    const scripts = version && typeof version.scripts === 'number' ? version.scripts : null;
    return {
        signerKey: bounded(version?.sig?.key_id, TRUST_TEXT_CHARS),
        reviewShape: review.shape,
        verdict: review.verdict,
        overridden: review.overridden,
        overrideReason: review.overrideReason,
        digest: digest ? digest.slice(0, TRUST_PREFIX_CHARS) : null,
        sourceRepo: bounded(src?.repo, TRUST_TEXT_CHARS),
        sourceCommit: commit ? commit.slice(0, TRUST_PREFIX_CHARS) : null,
        scripts,
    };
}
