
export const GROUPS_PER_PAGE = 100;

export const SESSIONS_PER_GROUP = 500;

export const MAX_PAGES = 50;

export function overviewQuery(offset = 0): string {
    return build({ include_automated: 'true', sort: 'recent', limit: String(GROUPS_PER_PAGE), session_limit: '1' }, offset);
}

export function projectQuery(key: string): string {
    return build({ project: key, include_automated: 'true', sort: 'recent', limit: '1', session_limit: String(SESSIONS_PER_GROUP) }, 0);
}

function build(params: Record<string, string>, offset: number): string {
    const search = new URLSearchParams(params);
    if (offset) search.set('offset', String(offset));
    return search.toString();
}
