import { matchParts } from '../drawer/search-match';
import { folderName, matchedField, matchesRow, type MatchField } from '../drawer/search';
import type { SidebarRow } from './legacy';
import { searchRowFacts } from './search-row-facts';
import type { BrowserRowPlan, RowPlan, SearchHitPlan, SessionRowPlan } from './row-plan';

export const SEARCH_AGENTS_BAND = 'search:agents';
export const SEARCH_CONVERSATIONS_KEY = 'search:conversations';

export interface SearchAgentsPlan {
    type: 'search-agents';
    key: string;
    count: number;
    rows: RowPlan[];
}

export interface SearchConversationsPlan {
    type: 'search-conversations';
    key: string;
    agents: number;
    query: string;
}

const FIELD_RANK: Record<MatchField, number> = { name: 0, project: 1, folder: 2 };

export function searchHitRows(list: readonly SidebarRow[], q: string): SidebarRow[] {
    const seen = new Set<string>();
    const hits: Array<{ row: SidebarRow; rank: number; at: number }> = [];
    list.forEach((row, at) => {
        if (seen.has(row.name) || !matchesRow(row, q)) return;
        seen.add(row.name);
        const field = matchedField(row, q);
        hits.push({ row, rank: field ? FIELD_RANK[field] : 0, at });
    });
    return hits.sort((a, b) => a.rank - b.rank || a.at - b.at).map((h) => h.row);
}

const HTML_ESCAPES: ReadonlyArray<readonly [string, string]> = [['&', '&amp;'], ['<', '&lt;'], ['>', '&gt;'], ['"', '&quot;'], ["'", '&#39;']];
const escapeText = (text: string): string => HTML_ESCAPES.reduce((acc, [raw, esc]) => acc.split(raw).join(esc), text);
const unescapeText = (text: string): string => [...HTML_ESCAPES].reverse().reduce((acc, [raw, esc]) => acc.split(esc).join(raw), text);

export function markLayoutName(html: string, q: string): string {
    return html.replace(/(<span class="session-sidebar-row-name"[^>]*>)([^<]*)/, (whole, open: string, text: string) => {
        const parts = matchParts(unescapeText(text), q);
        if (!parts.match) return whole;
        return `${open}${escapeText(parts.before)}<mark class="sd-mark">${escapeText(parts.match)}</mark>${escapeText(parts.after)}`;
    });
}

export function hitPlan(row: SidebarRow, q: string, name: string): SearchHitPlan {
    const field = matchedField(row, q);
    const project = typeof row.project_name === 'string' && row.project_name ? row.project_name : null;
    const folder = folderName(row.working_dir) || null;
    const inName = field === 'name';
    return {
        name: inName ? matchParts(name, q) : { before: name, match: '', after: '' },
        context: inName || (!project && !folder) ? null : {
            project: project ? matchParts(project, q) : null,
            folder: folder ? matchParts(folder, q) : null,
        },
        conversationId: typeof row.claude_session_uuid === 'string' && row.claude_session_uuid ? row.claude_session_uuid : null,
        facts: searchRowFacts(row),
    };
}

export function searchParts(
    list: readonly SidebarRow[], q: string, planRow: (row: SidebarRow) => RowPlan,
): Array<SearchAgentsPlan | SearchConversationsPlan> {
    const hits = searchHitRows(list, q);
    const rows = hits.map((row) => {
        const plan = planRow(row);
        if (plan.type === 'session') {
            const session = plan as SessionRowPlan;
            session.search = hitPlan(row, q, plan.name.text);
            session.pin = null;
        } else if (plan.type === 'browser') {
            (plan as BrowserRowPlan).pin = null;
        } else if (plan.type === 'legacy') {
            plan.html = markLayoutName(plan.html, q);
        }
        return plan;
    });
    const parts: Array<SearchAgentsPlan | SearchConversationsPlan> = [];
    if (rows.length) parts.push({ type: 'search-agents', key: SEARCH_AGENTS_BAND, count: rows.length, rows });
    parts.push({ type: 'search-conversations', key: SEARCH_CONVERSATIONS_KEY, agents: rows.length, query: q.trim() });
    return parts;
}
