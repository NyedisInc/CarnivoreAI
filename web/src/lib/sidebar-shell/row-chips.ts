import { glyphSvg } from '../../../../client/js/icons/glyphs.js';
import { whenLabel as fireLabel } from '../automations/format';
import { timerStateKey, timerStateOf } from '../automations/timer-state';
import { escapeAttr } from '../led';
import { effortClass, effortLevel } from '../effort/effort-level';
import { t } from '../i18n/index.svelte';
import { badgeText, badgeTitle, runningCount } from '../subagents/subagents';
import type { ScheduledMark } from '../sessions/types';
import { timerChip } from '../timers/timers';
import { icons, type SizedIcon } from '../../opscenter/ui/icons';
import type { SidebarRow } from './legacy';
import type { RowHost } from './row-host';
import type { Attrs, GlyphChip, MetaPlan, ModelPlan, TextChip } from './row-plan';
import { ageLabel, hintText, originBadge, whenLabel } from './row-text';

const TOP_TIER = 5;
const TOP_EFFORTS = ['xhigh', 'max'];
const SHIMMER_EFFORTS = ['xhigh', 'max', 'ultracode'];
const SHEEN_EFFORTS = ['high', 'xhigh'];

export const PIN_SVG = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="17" x2="12" y2="22"></line><path d="M5 17h14l-2-4V4H7v9l-2 4z"></path></svg>';

export function pinAttrs(name: string, pinned: boolean): Attrs {
    return {
        type: 'button',
        class: 'session-sidebar-row-pin',
        'data-pin-session': name,
        'aria-pressed': pinned ? 'true' : 'false',
        tabindex: '-1',
        'aria-label': pinned ? `Unpin ${name}` : `Pin ${name} to the top`,
        title: pinned ? 'unpin' : 'pin to top',
    };
}

export type BrowserKeyAction = 'popout' | 'close';

export function browserKeyAttrs(action: BrowserKeyAction, isPage = false, isFile = false): Attrs {
    const label = action === 'close'
        ? t(isFile ? 'files.menu.close' : isPage ? 'browser.menu.close_page' : 'browser.menu.close')
        : t('browser.menu.pop_out');
    return {
        type: 'button',
        class: action === 'close' ? 'session-sidebar-row-key session-sidebar-row-key--close' : 'session-sidebar-row-key',
        'data-browser-row-action': action,
        tabindex: '-1',
        'aria-label': label,
        title: label,
    };
}

export function sharePlan(r: SidebarRow): GlyphChip | null {
    const expiresAt = r.spectator_expires_at;
    if (expiresAt == null || expiresAt === '') return null;
    const at = new Date(expiresAt as string);
    const when = Number.isNaN(at.getTime())
        ? String(expiresAt)
        : at.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
    const label = t('session.share.mark', { when });
    return {
        attrs: {
            type: 'button',
            class: 'session-sidebar-row-share',
            'data-share-session-id': r.session_id == null ? '' : String(r.session_id),
            'data-share-session': r.name,
            tabindex: '-1',
            'aria-label': label,
            title: label,
        },
        svg: glyphSvg('telescope'),
    };
}

export function keepAwakePlan(r: SidebarRow, host: RowHost): GlyphChip | null {
    if (!host.autoSleep || host.autoSleep.isKeptAwake(r.name) !== true) return null;
    const text = t('auto_sleep.keep_awake.on', { name: r.name });
    return {
        attrs: {
            type: 'button',
            class: 'session-sidebar-row-keep-awake',
            'data-keep-awake-session': r.name,
            'data-keep-awake': '1',
            tabindex: '-1',
            'aria-pressed': 'true',
            'aria-label': text,
            title: text,
        },
        svg: glyphSvg('coffee', 13),
    };
}

function subagentTotal(r: SidebarRow, running: number): number {
    return typeof r.subagents_total === 'number' ? r.subagents_total : running;
}

export function subagentChip(r: SidebarRow): TextChip | null {
    const running = runningCount(r.subagents_running);
    if (running === null || !r.session_id) return null;
    const title = badgeTitle(running, subagentTotal(r, running));
    return {
        attrs: {
            type: 'button',
            class: 'subagent-count subagent-count--button',
            'data-subagents-session-id': String(r.session_id),
            'data-subagents-session': r.name,
            tabindex: '-1',
            'aria-haspopup': 'dialog',
            'aria-label': title,
        },
        text: badgeText(running),
    };
}

export function subagentCount(r: SidebarRow): TextChip | null {
    const running = runningCount(r.subagents_running);
    if (running === null) return null;
    let cls = 'session-row__subagent-count';
    if (r.workflow_active === true) cls += ' session-row__subagent-count--workflow';
    return { attrs: { class: cls }, text: String(running) };
}

export function timerPlan(r: SidebarRow): TextChip | null {
    const chip = timerChip(r as Parameters<typeof timerChip>[0], Date.now());
    if (!chip || !r.session_id) return null;
    return {
        attrs: {
            type: 'button',
            class: 'timer-chip timer-chip--button',
            'data-timers-session-id': String(r.session_id),
            'data-timers-session': r.name,
            tabindex: '-1',
            'aria-haspopup': 'dialog',
            'aria-label': chip.title,
        },
        text: chip.text,
    };
}

export function agentsIconPlan(r: SidebarRow): GlyphChip | null {
    const running = runningCount(r.subagents_running);
    if (running === null) return null;
    const total = subagentTotal(r, running);
    const title = t('sidebar.row.agents_icon.title', { count: running, total });
    return {
        attrs: {
            class: 'session-sidebar-row-agents-icon',
            role: 'img',
            'aria-label': title,
            title,
        },
        svg: glyphSvg('users', 13),
    };
}

export function workflowIconPlan(r: SidebarRow): GlyphChip | null {
    if (r.workflow_active !== true) return null;
    const title = t('sidebar.row.workflow_icon.title');
    return {
        attrs: {
            class: 'session-sidebar-row-workflow-icon',
            role: 'img',
            'aria-label': title,
            title,
        },
        svg: glyphSvg('workflow', 13),
    };
}

export function shellsIconPlan(r: SidebarRow): GlyphChip | null {
    const openRaw = r.background_open;
    const open = typeof openRaw === 'number' && Number.isFinite(openRaw) && openRaw > 0
        ? Math.floor(openRaw) : null;
    const parked = (r.parked_summary as string | undefined) || null;
    if (open === null && !parked) return null;
    let title: string;
    if (open !== null) {
        title = t('sidebar.row.shells_icon.title', { count: open });
        if (parked) title += `: ${parked}`;
    } else {
        title = parked as string;
    }
    return {
        attrs: {
            class: 'session-sidebar-row-shells-icon',
            role: 'img',
            'aria-label': title,
            title,
        },
        svg: glyphSvg('terminal', 13),
    };
}

export function timersIconPlan(r: SidebarRow): GlyphChip | null {
    const chip = timerChip(r as Parameters<typeof timerChip>[0], Date.now());
    if (!chip) return null;
    return {
        attrs: {
            class: 'session-sidebar-row-timers-icon',
            role: 'img',
            'aria-label': chip.title,
            title: chip.title,
        },
        svg: glyphSvg('clock', 13),
    };
}

function automationsTitle(r: SidebarRow, state: NonNullable<ReturnType<typeof timerStateOf>>): string {
    const total = Number(r.automations_total ?? 0);
    const head = t('sidebar.row.automations_icon.title', {
        count: total,
        enabled: Number(r.automations_enabled ?? 0),
        status: t(timerStateKey(state)),
    });
    const marks: ScheduledMark[] = Array.isArray(r.automations_next) ? r.automations_next : [];
    const lines = marks.map((m) =>
        m.next_fire_at == null
            ? t('sidebar.row.automations_icon.item_off', { name: m.name })
            : t('sidebar.row.automations_icon.item', { name: m.name, when: fireLabel(m.next_fire_at) }),
    );
    if (marks.length > 0 && total > marks.length) lines.push(t('sidebar.row.automations_icon.more', { count: total - marks.length }));
    return [head, ...lines].join('\n');
}

export function automationsIconPlan(r: SidebarRow): GlyphChip | null {
    const state = timerStateOf(r.automations_state);
    const uuid = typeof r.session_uuid === 'string' ? r.session_uuid : '';
    if (!state || !uuid) return null;
    const title = automationsTitle(r, state);
    return {
        attrs: {
            type: 'button',
            class: 'session-sidebar-row-automations-icon oc-timer-state',
            'data-state': state,
            'data-automations-session-uuid': uuid,
            tabindex: '-1',
            'aria-label': title,
            title,
        },
        svg: `<span class="oc-timer-glyph">${glyphSvg('alarm', 13)}</span>`,
    };
}


export function modelPlan(r: SidebarRow): ModelPlan | null {
    const model = r.running_model;
    if (typeof model !== 'string' || !model.trim()) return null;
    const tier = r.running_model_tier;
    const effort = r.running_model_effort;
    const topped = tier === TOP_TIER && typeof effort === 'string'
        && TOP_EFFORTS.includes(effort.trim().toLowerCase());
    const shimmer = SHIMMER_EFFORTS.includes(effortLevel(effort) ?? '') ? ` ${effortClass(effort)}` : '';
    const tierOk = typeof tier === 'number' && Number.isInteger(tier) && tier >= 1 && tier <= TOP_TIER;
    const label = model.trim() + (effort ? ` at ${String(effort)}` : '');
    return {
        attrs: {
            class: `session-sidebar-row-model${shimmer}`,
            'data-model-tier': tierOk ? String(tier) : '',
            'data-model-top': topped ? '1' : undefined,
            role: 'img',
            'aria-label': label,
            title: label,
        },
        svg: (icons.bot as SizedIcon).path,
        spark: topped,
        sheen: shimmer !== '' && SHEEN_EFFORTS.includes(effortLevel(effort) ?? ''),
    };
}

export function metaPlan(r: SidebarRow): MetaPlan {
    const badge = originBadge(r, true);
    const age = ageLabel(r.created_at_epoch);
    const hint = hintText(r);
    return {
        badge: badge ? { attrs: { class: 'session-sidebar-row-badge' }, text: badge.text } : null,
        age: age ? { attrs: { class: 'session-sidebar-row-age' }, text: `${age} old` } : null,
        when: whenChip(r),
        hint: hint ? { attrs: { class: 'session-sidebar-row-hint' }, text: hint } : null,
        host: hostChip(r),
    };
}

export function hostChip(r: SidebarRow): TextChip | null {
    const key = r.host_key as string | undefined;
    if (!key || key === 'local') return null;
    const label = (r.host_label as string | undefined) || key;
    const state = (r.host_state as string | undefined) || 'up';
    return {
        attrs: {
            class: 'session-sidebar-row-badge session-sidebar-row-host',
            'data-host-state': state !== 'up' ? state : undefined,
        },
        text: label,
    };
}

export function automationChip(r: SidebarRow): TextChip | null {
    const mark = r.automation as { name?: string } | null | undefined;
    if (!mark || typeof mark !== 'object') return null;
    const title = t('sidebar.row.auto_title', { name: mark.name ?? '' });
    return { attrs: { class: 'session-sidebar-row-badge session-sidebar-row-auto', title }, text: t('sidebar.row.auto') };
}

export function whenChip(r: SidebarRow): TextChip | null {
    const rel = whenLabel(r);
    if (!rel) return null;
    return { attrs: { class: 'session-sidebar-row-when' }, text: rel };
}

export function wakeTitle(epoch: unknown): string | null {
    if (typeof epoch !== 'number' || !Number.isFinite(epoch) || epoch <= 0) return null;
    return t('sidebar.row.wake_icon.title', { when: fireLabel(epoch) });
}

export function wakeIconPlan(r: SidebarRow): GlyphChip | null {
    const when = r.asleep ? wakeTitle(r.next_wake_at) : null;
    if (when === null) return null;
    const title = t('sidebar.row.wake_icon.open', { title: when });
    const uuid = typeof r.session_uuid === 'string' ? r.session_uuid : '';
    const attrs: Record<string, string> = uuid
        ? { type: 'button', class: 'session-sidebar-row-wake-icon', 'data-automations-session-uuid': uuid, tabindex: '-1', 'aria-label': title, title }
        : { class: 'session-sidebar-row-wake-icon', role: 'img', 'aria-label': title, title };
    return {
        attrs,
        svg: glyphSvg('clock', 13),
    };
}

export function archivedChip(r: SidebarRow): GlyphChip | null {
    if (r.archived !== true) return null;
    const title = t('session.archive.badge.title');
    return {
        attrs: { class: 'session-sidebar-row-archived-icon', role: 'img', 'aria-label': title, title },
        svg: glyphSvg('archive-box', 14),
    };
}

export function inactiveProjectIcon(): GlyphChip {
    const title = t('sidebar.project.inactive.title');
    return {
        attrs: { class: 'session-sidebar-group__inactive-icon', role: 'img', 'aria-label': title, title },
        svg: glyphSvg('project-inactive', 14),
    };
}

export function movedAwayChip(machine: string): TextChip {
    const text = machine ? t('pack.moved_to', { machine }) : t('pack.moved_to.unnamed');
    return { attrs: { class: 'session-sidebar-row-badge' }, text };
}

/* nothing at all */
export function archivedPart(r: SidebarRow): { archived?: GlyphChip } {
    const chip = archivedChip(r);
    return chip ? { archived: chip } : {};
}

export function roleMarks(r: SidebarRow): { attrs: Attrs; html: string } {
    const lead = r.task_lead === true;
    const label = t('cplug.huddle.role.lead_mark');
    return {
        attrs: { 'data-role-lead': lead ? '1' : undefined },
        html: lead
            ? `<span class="session-sidebar-row-provider__lead" role="img" aria-label="${escapeAttr(label)}" title="${escapeAttr(label)}">${glyphSvg('star', 7)}</span>`
            : '',
    };
}
