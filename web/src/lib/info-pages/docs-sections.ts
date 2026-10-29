
export const DOCS_HASH_BASE = '#docs';

export const DOCS_TOP_SECTION = 'lights';

export const DOCS_WRAPPERS_SECTION = 'wrappers';

export const DOCS_WRAPPERS_HASH = `${DOCS_HASH_BASE}/${DOCS_WRAPPERS_SECTION}`;

export function docsSectionOf(hash: string | null | undefined): string | null {
    if (typeof hash !== 'string') return null;
    const match = /^#?docs\/([a-z0-9-]+)$/.exec(hash.trim());
    return match?.[1] ?? null;
}
