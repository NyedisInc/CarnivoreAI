import { t } from '../i18n/index.svelte';
import { layouts } from '../layouts-bridge/api.svelte';
import { focusHistory } from '../focus-history/focus-history';
import { goTo } from '../nav-items/nav-items';
import { RAIL_DESTINATIONS, RAIL_RUN, railItemVisible } from '../../opscenter/shell/rail-items';
import { SETTINGS, settingKey } from '../settings-page/settings-registry';
import { openSettingsLink } from '../settings-page/screen-host';
import { applyGlobalTheme } from '../themes-page/global-theme';
import { canPopOutSession, popOutSession } from '../desktop-menu/pop-out-session';
import type { PaletteState } from './palette-query';
import { appActions, sessionActions } from './palette-actions';
import { homeBoards } from '../../opscenter/engine/home-sync.svelte';
import { showDashboard } from '../dashboards/dashboard-actions.svelte';
import { browsers, type BrowserInfo } from '../browser/api.svelte';
import { openPages } from '../browser/pages.svelte';
import type { PageInfo } from '../browser/page-frame';
import { openBrowser } from '../browser/screen-host';
import { openFiles, type OpenFileInfo } from '../open-files/api.svelte';
import { GUIDE_SECTIONS, type GuideSection } from '../user-guide/guide-content';
import { followGuideTarget } from '../user-guide/guide-nav';
import { DOCS_HASH_BASE } from '../info-pages/docs-sections';

export type PaletteKind =
    | 'session' | 'project' | 'layout' | 'dashboard' | 'page' | 'browser' | 'file' | 'help' | 'setting' | 'theme' | 'action' | 'search';

export interface PaletteItem {
    id: string;
    kind: PaletteKind;
    title: string;
    subtitle: string;
    host?: string;
    project?: string;
    states?: PaletteState[];
    offline?: boolean;
    run(opts: { popout: boolean }): unknown;
    actions?: () => PaletteItem[];
    chip?: string;
}

export interface DrawerRowLike {
    name?: string;
    label?: string | null;
    session_id?: string | null;
    session_uuid?: string | null;
    session_row_id?: number | null;
    status?: string | null;
    unread?: boolean;
    asleep?: boolean;
    archived?: boolean;
    closed?: boolean;
    startup_gate?: unknown;
    host_key?: string | null;
    host_label?: string | null;
    host_state?: string | null;
    project_name?: string | null;
    last_work_at?: string | null;
    [key: string]: unknown;
}

export function drawerRows(): DrawerRowLike[] {
    const rows = (globalThis as { SessionSidebar?: { _rows?: DrawerRowLike[] } }).SessionSidebar?._rows;
    return Array.isArray(rows) ? rows.filter((r) => r && r.name && !r.archived && !r.closed) : [];
}

export function rowStates(row: DrawerRowLike): PaletteState[] {
    const out: PaletteState[] = [];
    const s = String(row.status ?? '');
    if (row.asleep) out.push('asleep');
    else if (s === 'question' || s === 'notice') out.push('waiting');
    else if (s === 'working' || s === 'working_subagent') out.push('working');
    else if (s === 'idle' || s === 'finished_unread') out.push('idle');
    if (row.startup_gate) out.push('blocked');
    if (row.unread || s === 'finished_unread') out.push('unread');
    return out;
}

function ago(iso: string | null | undefined, now: number): string {
    const at = iso ? Date.parse(iso) : NaN;
    if (!Number.isFinite(at)) return '';
    const m = Math.max(0, Math.round((now - at) / 60000));
    return m < 60 ? `${m} m` : m < 1440 ? `${Math.round(m / 60)} h` : `${Math.round(m / 1440)} d`;
}

function hostOf(row: DrawerRowLike): string {
    return (row.host_key && row.host_key !== 'local' ? row.host_label || row.host_key : t('palette.host.here')) || '';
}

export function sessionItem(row: DrawerRowLike, now: number): PaletteItem {
    const states = rowStates(row);
    const remote = !!row.host_key && row.host_key !== 'local';
    const offline = remote && !!row.host_state && row.host_state !== 'online' && row.host_state !== 'ok';
    const host = hostOf(row);
    const parts = [host, row.project_name ?? '', offline ? t('palette.offline') : states.join(' '), ago(row.last_work_at, now)];
    const id = String(row.session_id || row.name);
    return {
        id: `session:${id}`, kind: 'session', title: String(row.label || row.name), subtitle: parts.filter(Boolean).join(' · '),
        host: host.toLowerCase(), project: (row.project_name ?? '').toLowerCase(), states, offline,
        run: ({ popout }) => {
            if (popout && canPopOutSession(row.session_row_id ?? null)) return popOutSession(row.session_row_id!, `terminal:row:${row.session_row_id}`);
            return goTo({ kind: 'session', id, tmuxName: String(row.name) });
        },
        actions: () => sessionActions(row),
    };
}

function pageItems(): PaletteItem[] {
    return RAIL_DESTINATIONS.filter(railItemVisible).map((item) => ({
        id: `page:${item.id}`, kind: 'page' as const, title: t(item.labelKey), subtitle: t('palette.kind.page'),
        run: () => (item.run ?? RAIL_RUN[item.id])?.(),
    }));
}

function settingItems(): PaletteItem[] {
    return SETTINGS.map((s) => ({
        id: `setting:${s.id}`, kind: 'setting' as const, title: t(settingKey(s.id, 'label')), subtitle: t('palette.kind.setting'),
        run: () => openSettingsLink(`#settings/${s.section}?highlight=${s.id}`),
    }));
}

function themeItems(): PaletteItem[] {
    const reg = (globalThis as { Themes?: { listAll?: () => { id?: string; name?: string }[] } }).Themes;
    const all = typeof reg?.listAll === 'function' ? reg.listAll() : [];
    return all.filter((m) => m && m.id).map((m) => ({
        id: `theme:${m.id}`, kind: 'theme' as const, title: t('palette.theme', { name: m.name || m.id }), subtitle: t('palette.kind.theme'),
        run: () => applyGlobalTheme(String(m.id)),
    }));
}

function layoutItems(): PaletteItem[] {
    return (layouts.data ?? []).map((l) => ({
        id: `layout:${l.layout_uuid}`, kind: 'layout' as const, title: l.name, subtitle: t('palette.kind.layout'),
        run: () => goTo({ kind: 'layout', uuid: l.layout_uuid }),
    }));
}

/* the home screen */
export function dashboardItems(boards: readonly { id: string; name: string }[]): PaletteItem[] {
    return boards.map((b) => ({
        id: `dashboard:${b.id}`, kind: 'dashboard' as const, title: b.name || b.id, subtitle: t('palette.kind.dashboard'),
        run: () => showDashboard(b.id),
    }));
}

export function browserItems(list: readonly BrowserInfo[], pages: readonly PageInfo[]): PaletteItem[] {
    const live = list.map((b) => ({ id: b.id, title: b.label || b.url || b.id, sub: b.url }));
    const opened = pages.map((p) => ({ id: p.id, title: p.title || p.key || p.id, sub: '' }));
    return [...live, ...opened].map((b) => ({
        id: `browser:${b.id}`, kind: 'browser' as const, title: b.title,
        subtitle: [t('palette.kind.browser'), b.sub].filter(Boolean).join(' · '), run: () => openBrowser(b.id),
    }));
}

export function fileItems(files: readonly OpenFileInfo[]): PaletteItem[] {
    return files.map((f) => ({
        id: `file:${f.id}`, kind: 'file' as const, title: f.title || f.path,
        subtitle: [t('palette.kind.file'), f.path].filter(Boolean).join(' · '), run: () => openBrowser(f.id),
    }));
}

export function helpItems(sections: readonly GuideSection[]): PaletteItem[] {
    return sections.map((s) => ({
        id: `help:${s.id}`, kind: 'help' as const, title: s.title, subtitle: t('palette.kind.help'),
        run: () => followGuideTarget(`${DOCS_HASH_BASE}/${s.id}`),
    }));
}

function projectItems(rows: readonly DrawerRowLike[]): PaletteItem[] {
    const names = [...new Set(rows.map((r) => r.project_name).filter((n): n is string => !!n))];
    return names.map((name) => ({
        id: `project:${name}`, kind: 'project' as const, title: name, subtitle: t('palette.kind.project'), chip: name.toLowerCase(), run: () => undefined,
    }));
}

export interface PaletteCorpus {
    items: PaletteItem[];
    actions: PaletteItem[];
    sessions: PaletteItem[];
    pages: PaletteItem[];
    known: { host: string[]; project: string[]; state: string[] };
    byId: Map<string, PaletteItem>;
}

export function buildCorpus(now: number = Date.now()): PaletteCorpus {
    const rows = drawerRows();
    const sessions = rows.map((r) => sessionItem(r, now));
    const layoutsList = layoutItems();
    const pages = pageItems();
    const items = [
        ...sessions, ...projectItems(rows), ...layoutsList, ...dashboardItems(homeBoards.list), ...pages,
        ...browserItems(browsers.data ?? [], openPages.data ?? []), ...fileItems(openFiles.data ?? []),
        ...settingItems(), ...themeItems(), ...helpItems(GUIDE_SECTIONS),
    ];
    const byId = new Map<string, PaletteItem>([...sessions, ...layoutsList].map((i) => [i.id, i]));
    return {
        items, sessions, pages, byId,
        actions: appActions(rows),
        known: {
            host: [...new Set(sessions.map((s) => s.host ?? '').filter(Boolean))],
            project: [...new Set(sessions.map((s) => s.project ?? '').filter(Boolean))],
            state: ['waiting', 'working', 'idle', 'asleep', 'blocked', 'unread'],
        },
    };
}

export function emptyGroups(corpus: PaletteCorpus): { key: string; items: PaletteItem[] }[] {
    const entries = focusHistory.entries();
    const cursor = focusHistory.cursor();
    const recent: PaletteItem[] = [];
    for (let i = entries.length - 1; i >= 0; i -= 1) {
        if (i === cursor) continue;
        const e = entries[i]!;
        const item = corpus.byId.get(e.kind === 'layout' ? `layout:${e.uuid}` : `session:${e.id}`);
        if (item && !recent.includes(item)) recent.push(item);
    }
    const waiting = corpus.sessions.filter((s) => s.states?.includes('waiting') || s.states?.includes('blocked'));
    const rows = drawerRows();
    const workAt = new Map(rows.map((r) => [`session:${r.session_id || r.name}`, r.last_work_at ? Date.parse(r.last_work_at) : 0]));
    waiting.sort((a, b) => (workAt.get(a.id) ?? 0) - (workAt.get(b.id) ?? 0));
    return [
        { key: 'palette.group.recent', items: recent.slice(0, 8) },
        { key: 'palette.group.needs_you', items: waiting },
        { key: 'palette.group.pages', items: corpus.pages },
    ].filter((g) => g.items.length);
}
