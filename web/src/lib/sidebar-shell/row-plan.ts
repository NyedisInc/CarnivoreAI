import { t } from '../i18n/index.svelte';
import { hostOffline, usageLimitLabel } from '../led';
import type { Membership } from '../swarm-membership/member-face';
import { closedPart } from './row-closed';
import { sessionMark } from '../sessions/agent-marks';
import { iconVisible } from '../drawer/row-icon-prefs';
import type { SidebarRow } from './legacy';
import { colorValue, isRowIcon } from '../open-files/row-looks';
import { rowBodyPlan, type RowBodyPlan } from './row-body';
import { contextPlan, type ContextPlan } from './row-context';
import type { LayoutRowParts } from '../drawer/layouts-row-html';
import type { RowHost } from './row-host';
import {
    agentsIconPlan, browserKeyAttrs, keepAwakePlan, metaPlan, modelPlan, pinAttrs, sharePlan, shellsIconPlan, subagentChip,
    subagentCount, hostChip, archivedPart, timerPlan, timersIconPlan, automationsIconPlan, whenChip, automationChip, wakeIconPlan, workflowIconPlan, roleMarks,
} from './row-chips';
import { originBadge, renameState, workAttrs } from './row-text';

export type Attrs = Record<string, string | undefined>;

export interface TextChip {
    attrs: Attrs;
    text: string;
}

export interface GlyphChip {
    attrs: Attrs;
    svg: string;
}

export interface RowChipSpec {
    attrs: Attrs;
    svg?: string;
    text?: string;
}

export interface LedPlan {
    status: string | null;
    unread: boolean;
    startupGate: string | null;
    statusSource: string | null;
    activityHint: string | null;
    parkedSummary: string | null;
    transport: string;
    hostOffline: string | null;
    usageLimit: string | null;
}

export interface ModelPlan {
    attrs: Attrs;
    svg: string;
    spark: boolean;
    sheen: boolean;
}

export interface MetaPlan {
    badge: TextChip | null;
    age: TextChip | null;
    when: TextChip | null;
    hint: TextChip | null;
    host: TextChip | null;
}

export interface LeaderMark {
    rank: 'alpha' | 'company' | 'project';
    label: string;
}

export interface SessionRowPlan {
    type: 'session';
    search?: SearchHitPlan;
    leader?: LeaderMark | null;
    ghost?: { agentId: number; name: string; rank: 'alpha' | 'company' | 'project' } | null;
    member?: Membership | null;
    key: string;
    attrs: Attrs;
    led: LedPlan | null;
    agentsIcon: GlyphChip | null;
    shellsIcon: GlyphChip | null;
    timersIcon: GlyphChip | null;
    automationsIcon: GlyphChip | null;
    cozySubagents: TextChip | null;
    cozyTimer: TextChip | null;
    workflow: GlyphChip | null;
    wake: GlyphChip | null;
    auto: TextChip | null;
    messaging: unknown;
    context: ContextPlan | null;
    provider: GlyphChip;
    model: ModelPlan | null;
    detailedCount: TextChip | null;
    detailedTimer: TextChip | null;
    name: TextChip;
    subtitle: TextChip | null;
    cozyBadge: TextChip | null;
    cozyWhen: TextChip | null;
    hostInline: TextChip | null;
    archived?: GlyphChip;
    closed?: TextChip;
    share: GlyphChip | null;
    keepAwake: GlyphChip | null;
    pin: Attrs | null;
    actions: RowChipSpec[];
    menu: RowChipSpec | null;
    meta: MetaPlan | null;
    body: RowBodyPlan | null;
}

export interface BrowserRowPlan {
    type: 'browser';
    key: string;
    attrs: Attrs;
    globe: { attrs: Attrs; live: boolean; page: boolean; file: boolean };
    icon: string | null;
    name: TextChip;
    subtitle: TextChip | null;
    dirty: Attrs | null;
    pin: Attrs | null;
    popOut: Attrs | null;
    closeKey: Attrs;
    menu: RowChipSpec | null;
}

export interface LayoutMembersPlan {
    bodyId: string;
    uuid: string;
    rows: RowPlan[];
}

export interface LayoutRowPlan {
    type: 'layout';
    key: string;
    parts: LayoutRowParts;
    pin: Attrs;
    menu: RowChipSpec | null;
    nameMatch: { before: string; match: string; after: string } | null;
    members: LayoutMembersPlan | null;
}

export interface SearchHitPlan {
    name: { before: string; match: string; after: string };
    context: { project: { before: string; match: string; after: string } | null; folder: { before: string; match: string; after: string } | null } | null;
    conversationId: string | null;
    facts: SearchRowFacts;
}

export interface SearchRowFacts {
    age: string;
    note: string | null;
    model: ModelPlan | null;
    modelName: string;
    effort: string;
}

export type RowPlan = SessionRowPlan | BrowserRowPlan | LayoutRowPlan;

const DENSITIES = ['compact', 'cozy', 'detailed'];

function bandAttrs(name: string, band: string | undefined): Attrs {
    return {
        'data-band': band || undefined,
        id: band ? `session-sidebar-row__${name}__${band}` : undefined,
    };
}

function sessionRowPlan(
    r: SidebarRow, density: string, band: string | undefined, subtitle: string | null | undefined, host: RowHost,
): SessionRowPlan {
    const mode = DENSITIES.includes(density) ? density : 'compact';
    const rename = renameState(r, host);
    const resolved = host.label ? host.label.resolve(r) : null;
    const offersMenu = !!(host.actions && host.actions.offersMenu(r.status));
    const cupVisible = iconVisible(mode, 'cup');
    const pinVisible = iconVisible(mode, 'pin');
    const menuVisible = iconVisible(mode, 'menu');
    const keepAwakeChip = keepAwakePlan(r, host);
    const awakeHiddenNote = (keepAwakeChip && !cupVisible) ? t('sidebar.row.kept_awake.hidden_note') : '';
    const noteReason = rename.state === 'renameable' ? '' : rename.reason;
    const nameTitle = awakeHiddenNote
        ? (noteReason ? `${noteReason} - ${awakeHiddenNote}` : awakeHiddenNote)
        : noteReason;
    const menu = (offersMenu && host.menu)
        ? host.menu.triggerSpec(host.menu.contextFromRow(r, {
            surface: 'sidebar',
            renameable: rename.state === 'renameable',
            renameReason: rename.state === 'renameable' ? '' : rename.reason,
            band,
            menuHidden: !menuVisible,
        }))
        : null;
    const led: LedPlan | null = r.agent_family === 'shell' || r.closed === true || r.archived === true ? null : {
        status: (r.status as string | undefined) ?? null,
        unread: !!r.unread,
        startupGate: (r.startup_gate as string | undefined) ?? null,
        statusSource: (r.status_source as string | undefined) ?? null,
        activityHint: (r.activity_hint as string | undefined) ?? null,
        parkedSummary: (r.parked_summary as string | undefined) ?? null,
        transport: host.transport ? host.transport.stateFor(r.name) : 'unknown',
        hostOffline: hostOffline(r),
        usageLimit: usageLimitLabel(r),
    };
    const body = rowBodyPlan(r, mode, led);
    const legacyMode = body ? 'compact' : mode;
    const cozyOrigin = legacyMode === 'cozy' ? originBadge(r, false) : null;
    return {
        type: 'session',
        key: r.name,
        attrs: {
            class: 'session-sidebar-row',
            'data-name': r.name,
            ...bandAttrs(r.name, band),
            'data-active': r.is_this_tab ? '1' : '0',
            'data-asleep': r.asleep ? '1' : undefined,
            'data-archived': r.archived === true ? '1' : undefined,
            'data-closed': r.closed === true ? '1' : undefined,
            'data-pinned': r.is_pinned ? '1' : '0',
            'data-rename-state': rename.state,
            ...workAttrs(r),
            role: 'option',
            'aria-selected': r.is_this_tab ? 'true' : 'false',
            tabindex: '-1',
            'data-session-id': r.session_id ? String(r.session_id) : undefined,
            'data-session-uuid': r.session_uuid ? String(r.session_uuid) : undefined,
        },
        led,
        agentsIcon: !body && iconVisible(mode, 'agents') ? agentsIconPlan(r) : null,
        shellsIcon: !body && iconVisible(mode, 'shells') ? shellsIconPlan(r) : null,
        timersIcon: !body && iconVisible(mode, 'timers') ? timersIconPlan(r) : null,
        automationsIcon: !r.asleep && iconVisible(mode, 'automations') ? automationsIconPlan(r) : null,
        cozySubagents: legacyMode === 'cozy' ? subagentChip(r) : null,
        cozyTimer: legacyMode === 'cozy' ? timerPlan(r) : null,
        workflow: workflowIconPlan(r),
        wake: wakeIconPlan(r),
        auto: automationChip(r),
        messaging: r.messaging ?? null,
        context: iconVisible(mode, 'context') ? contextPlan(r) : null,
        provider: providerPlan(r),
        model: body ? null : modelPlan(r),
        detailedCount: legacyMode === 'detailed' ? subagentCount(r) : null,
        detailedTimer: legacyMode === 'detailed' ? timerPlan(r) : null,
        name: {
            attrs: { class: 'session-sidebar-row-name', 'data-row-name': r.name, ...(nameTitle ? { 'data-name-note': nameTitle } : {}) },
            text: resolved === null ? r.name : resolved,
        },
        subtitle: subtitle
            ? { attrs: { class: 'session-sidebar-row-subtitle' }, text: subtitle }
            : null,
        cozyBadge: cozyOrigin
            ? { attrs: { class: 'session-sidebar-row-badge' }, text: cozyOrigin.text }
            : null,
        cozyWhen: legacyMode === 'cozy' ? whenChip(r) : null,
        hostInline: legacyMode === 'detailed' ? null : hostChip(r),
        ...archivedPart(r),
        ...closedPart(r),
        share: sharePlan(r),
        keepAwake: cupVisible ? keepAwakeChip : null,
        pin: pinVisible ? pinAttrs(r.name, !!r.is_pinned) : null,
        actions: (host.actions && !offersMenu)
            ? host.actions.specs(r.status, r.name, 'session-sidebar-row-delete')
            : [],
        menu,
        meta: legacyMode === 'detailed' ? metaPlan(r) : null,
        body,
    };
}

function providerPlan(r: SidebarRow): GlyphChip {
    const mark = sessionMark((r.agent_family as string | undefined) ?? null, (r as { agent_wrapper_icon?: string | null }).agent_wrapper_icon);
    const roles = roleMarks(r);
    return {
        attrs: {
            class: 'session-sidebar-row-provider',
            'data-grip-session': r.name,
            'data-agent-family': mark.key,
            ...roles.attrs,
            role: 'img',
            'aria-label': mark.label,
            title: mark.label,
        },
        svg: mark.svg + roles.html,
    };
}

export function browserMenuContext(r: SidebarRow, groupable: boolean): Record<string, unknown> {
    return {
        name: r.name, label: (r.label as string | undefined) || '', sessionId: null, projectId: null,
        surface: 'sidebar', kind: 'browser', owned: true, status: 'unknown', unread: false,
        restartable: false, pluginItems: '', groupable, renameable: !r.page && !r.file,
        renameReason: r.file ? t('files.row.rename_locked') : r.page ? t('browser.page.rename_locked') : '',
        isPage: !!r.page, isFile: !!r.file, forkable: false, forkReason: '', muted: false,
    };
}

function hostOf(url: unknown): string | null {
    try {
        return new URL(String(url)).host || null;
    } catch {
        return null;
    }
}

function browserRowPlan(r: SidebarRow, band: string | undefined, host: RowHost): BrowserRowPlan {
    const isFile = !!r.file;
    const isPage = !!r.page && !isFile;
    const live = r.status === 'live';
    const globeLabel = isFile ? t(r.file_kind === 'diff' ? 'files.row.diff' : 'files.row.file', { path: String(r.path ?? '') })
        : t(isPage ? 'browser.row.page' : live ? 'browser.row.live' : 'browser.row.stopped');
    const dirtyLabel = t('files.row.dirty');
    const host_ = hostOf(r.url);
    const look = r.look as { color?: string | null; icon?: string | null } | undefined;
    const tint = colorValue(look?.color);
    const tintStyle = tint ? { style: `color: ${tint};` } : {};
    return {
        type: 'browser',
        key: r.name,
        attrs: {
            class: 'session-sidebar-row',
            'data-name': r.name,
            ...bandAttrs(r.name, band),
            'data-kind': 'browser',
            'data-browser-id': r.browser_id == null ? '' : String(r.browser_id),
            'data-active': r.is_this_tab ? '1' : '0',
            'data-pinned': r.is_pinned ? '1' : '0',
            'data-rename-state': isPage || isFile ? 'unavailable' : 'renameable',
            role: 'option',
            'aria-selected': r.is_this_tab ? 'true' : 'false',
            tabindex: '-1',
        },
        globe: {
            attrs: {
                class: 'session-sidebar-row-provider',
                'data-grip-session': r.name,
                'data-browser-state': isFile ? 'file' : isPage ? 'page' : live ? 'live' : 'stopped',
                role: 'img',
                'aria-label': globeLabel,
                title: globeLabel,
                ...tintStyle,
            },
            live,
            page: isPage,
            file: isFile,
        },
        icon: isRowIcon(look?.icon) ? look.icon : null,
        name: {
            attrs: { class: 'session-sidebar-row-name', 'data-row-name': r.name, ...tintStyle },
            text: String((r.label as string | undefined) || r.name),
        },
        dirty: isFile && r.dirty
            ? { class: 'session-sidebar-row-dirty', role: 'img', 'aria-label': dirtyLabel, title: dirtyLabel }
            : null,
        subtitle: host_
            ? { attrs: { class: 'session-sidebar-row-subtitle' }, text: host_ }
            : null,
        pin: pinAttrs(r.name, !!r.is_pinned),
        popOut: isFile ? null : browserKeyAttrs('popout'),
        closeKey: browserKeyAttrs('close', isPage, isFile),
        menu: host.menu ? host.menu.triggerSpec(browserMenuContext(r, true)) : null,
    };
}

export function buildRowPlan(
    r: SidebarRow, density: string, band: string | undefined, subtitle: string | null | undefined, host: RowHost,
): RowPlan {
    if (r.kind === 'browser') return browserRowPlan(r, band, host);
    if (r.kind === 'layout' && host.layouts) return layoutRowPlan(r, density, band, host, host.layouts);
    return sessionRowPlan(r, density, band, subtitle, host);
}

function layoutRowPlan(
    r: SidebarRow, density: string, band: string | undefined, host: RowHost,
    layouts: NonNullable<RowHost['layouts']>,
): LayoutRowPlan {
    const parts = layouts.rowParts(r, band);
    const body = layouts.memberBody ? layouts.memberBody(r, band) : null;
    const members = body
        ? {
            bodyId: body.bodyId,
            uuid: body.uuid,
            rows: body.members
                .filter((m, i, all) => all.findIndex((o) => o.name === m.name) === i)
                .map((m) => buildRowPlan(m, density, body.band, undefined, host)),
        }
        : null;
    return {
        type: 'layout', key: r.name, parts, pin: pinAttrs(parts.pin.name, parts.pin.pinned),
        menu: host.menu ? host.menu.triggerSpec(parts.menuContext) : null,
        nameMatch: null, members,
    };
}
