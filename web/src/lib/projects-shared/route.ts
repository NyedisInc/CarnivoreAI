
export type PageView = 'projects';

export interface PageRoute {
    readonly view: PageView;
    readonly company: string | null;
    readonly project: string | null;
    readonly session: string | null;
}

export const PROJECTS_HOME: PageRoute = { view: 'projects', company: null, project: null, session: null };

export const ORPHANED = 'orphaned';

const COMPANY_WORD = 'c';

const segment = (value: string): string => encodeURIComponent(value);

export function routeHash(route: PageRoute): string {
    const parts: string[] = [route.view];
    if (typeof route.company === 'string') parts.push(COMPANY_WORD, segment(route.company));
    if (route.project) parts.push(segment(route.project));
    if (route.session && route.project) parts.push(segment(route.session));
    return `#${parts.join('/')}`;
}

export function routeOfHash(hash: string | null | undefined): PageRoute | null {
    if (typeof hash !== 'string') return null;
    const bare = hash.trim().replace(/^#/, '');
    const parts = bare.split('/').filter((p) => p !== '');
    const view = parts[0];
    if (view !== 'projects') return null;
    let decoded: string[];
    try {
        decoded = parts.slice(1).map(decodeURIComponent);
    } catch {
        return PROJECTS_HOME;
    }
    const company = decoded[0] === COMPANY_WORD && decoded[1] !== undefined ? decoded[1] : null;
    const rest = company === null ? decoded : decoded.slice(2);
    const project = decoded[0] === COMPANY_WORD && company === null ? null : (rest[0] ?? null);
    return { view, company, project, session: project ? (rest[1] ?? null) : null };
}

export const sameRoute = (a: PageRoute, b: PageRoute): boolean =>
    a.view === b.view && a.company === b.company && a.project === b.project && a.session === b.session;
