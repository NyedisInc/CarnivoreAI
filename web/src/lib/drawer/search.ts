/* and writes nothing */
import { handleWithoutPrefix } from '../product-identity';
import { drawerController } from './controller-ref';
import { esc } from './listing-state';
import { drawerEnv } from './env';
import { rowCountsAs } from './agent-counts';
import { activeCountFilter } from './count-filter.svelte';

let query = '';

interface LabelGlobals {
    SessionLabel?: { resolve(row: unknown): string | null };
    CloudeI18n?: { t(key: string, params?: Record<string, unknown>): string };
}

export const FILTER_ONLY_QUERY = '\u0001';

export function normalize(raw: unknown): string {
    return (raw == null ? '' : String(raw)).trim().toLowerCase();
}

export function getQuery(): string {
    return query;
}

export function effectiveQuery(): string {
    return query || (activeCountFilter() ? FILTER_ONLY_QUERY : '');
}

export function filterActive(): boolean {
    return effectiveQuery() !== '';
}

export function setQuery(raw: unknown): void {
    const next = normalize(raw);
    if (next === query) return;
    const crossed = (next === '') !== (query === '');
    query = next;
    const target = drawerController();
    target?.repaint();
    if (crossed) void target?.refreshNow?.();
}

export function searchLists(): boolean {
    return query !== '';
}

export type MatchField = 'name' | 'project' | 'folder';

export function displayName(row: Record<string, unknown>): string {
    const label = (drawerEnv() as LabelGlobals).SessionLabel;
    const resolved = label ? label.resolve(row) : null;
    const display = resolved === null ? row.name : resolved;
    return typeof display === 'string' ? display : '';
}

export function folderName(path: unknown): string {
    if (typeof path !== 'string') return '';
    const parts = path.split('/').filter((seg) => seg !== '');
    return parts.length ? (parts[parts.length - 1] as string) : '';
}

function fieldsFor(row: Record<string, unknown>): Record<MatchField, string[]> {
    const handle = typeof row.name === 'string' ? handleWithoutPrefix(row.name) : row.name;
    const name: unknown[] = [displayName(row), handle];
    if (row && row.kind === 'layout' && Array.isArray(row.member_names)) name.push(...row.member_names);
    const strings = (list: unknown[]): string[] => list.filter((v): v is string => typeof v === 'string' && v !== '');
    return { name: strings(name), project: strings([row.project_name]), folder: strings([folderName(row.working_dir)]) };
}

export function matchedField(row: Record<string, unknown> | null | undefined, q: string): MatchField | null {
    if (!row || !q || q === FILTER_ONLY_QUERY) return null;
    const fields = fieldsFor(row);
    for (const key of ['name', 'project', 'folder'] as const) {
        if (fields[key].some((v) => v.toLowerCase().includes(q))) return key;
    }
    return null;
}

export function matchesRow(row: Record<string, unknown> | null | undefined, q: string): boolean {
    if (!q) return true;
    if (!row) return false;
    const filter = activeCountFilter();
    if (filter && !rowCountsAs(row as never, filter)) return false;
    if (q === FILTER_ONLY_QUERY) return true;
    return matchedField(row, q) !== null;
}

export function matchesLabel(label: unknown, q: string): boolean {
    if (!q) return true;
    return typeof label === 'string' && label.toLowerCase().includes(q);
}

export function noMatchesHtml(q: string): string {
    const i18n = (drawerEnv() as LabelGlobals).CloudeI18n;
    const translate = i18n && typeof i18n.t === 'function' ? i18n.t.bind(i18n) : null;
    const text = q === FILTER_ONLY_QUERY
        ? (translate ? translate('drawer.stats.filter.none') : 'no agents match this count')
        : (translate ? translate('drawer.search.no_matches', { query: q }) : `no agents match "${q}"`);
    return `<div class="session-sidebar-empty" data-search-empty="1">${esc(text)}</div>`;
}
