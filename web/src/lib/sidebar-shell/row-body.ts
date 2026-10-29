import { glyphSvg } from '../../../../client/js/icons/glyphs.js';
import { scaleStep } from '../../../../client/js/labels/usage-panel.js';
import { iconVisible, type IconKind } from '../drawer/row-icon-prefs';
import { t } from '../i18n/index.svelte';
import { ledStateFor, type InnerState } from '../led';
import { normalizeStatus } from '../status-dot';
import { timerChip } from '../timers/timers';
import type { SidebarRow } from './legacy';
import { modelPlan } from './row-chips';
import type { Attrs, LedPlan, ModelPlan } from './row-plan';
import { ageLabel, epochFromIso } from './row-text';

export type BodyTone = 'ok' | 'warn' | 'info' | 'muted' | 'dim' | 'bad' | 'ctx4' | 'ctx5';

export interface BodyFlag {
    kind: 'permission' | 'host' | 'exited' | 'update' | 'context';
    tone: BodyTone;
    text: string;
}

export interface LivePart {
    kind: 'agents' | 'shells' | 'timers';
    attrs: Attrs;
    svg: string;
    count: string;
    unit: string;
}

export interface RowBodyPlan {
    mode: 'cozy' | 'detailed';
    rankTag: string | null;
    right: { text: string; tone: BodyTone | null; kind: 'state' } | null;
    flagTone: BodyTone | null;
    model: ModelPlan | null;
    modelName: string;
    effort: string;
    live: LivePart[];
    noLiveWork: boolean;
    ended: { text: string; tone: BodyTone; dead: boolean } | null;
    flags: BodyFlag[];
    when: string;
}

const STATE_WORDS: Record<InnerState, { key: string; tone: BodyTone }> = {
    working: { key: 'session.status.working', tone: 'ok' },
    'waiting-permission': { key: 'opscenter.session.mark.waiting', tone: 'warn' },
    'waiting-input': { key: 'opscenter.session.mark.waiting', tone: 'warn' },
    notice: { key: 'opscenter.session.mark.notice', tone: 'info' },
    idle: { key: 'opscenter.session.mark.idle', tone: 'muted' },
    done: { key: 'session.summary.bucket.done', tone: 'ok' },
    dead: { key: 'opscenter.session.mark.dead', tone: 'dim' },
    disconnected: { key: 'sidebar.row.state.disconnected', tone: 'bad' },
    limit: { key: 'session.status.usage_limit', tone: 'bad' },
    asleep: { key: 'session.asleep.label', tone: 'muted' },
    'asleep-unread': { key: 'session.asleep.label', tone: 'muted' },
    unknown: { key: 'opscenter.session.mark.not_measured', tone: 'muted' },
};

export function stateWord(led: LedPlan): { text: string; tone: BodyTone } {
    const inner = ledStateFor({
        activity_status: normalizeStatus(led.status),
        unread: led.unread,
        startup_gate: led.startupGate,
        transport: led.transport,
        host_offline: led.hostOffline,
        usage_limit: led.usageLimit,
    }).inner;
    const w = STATE_WORDS[inner] ?? STATE_WORDS.unknown;
    return { text: t(w.key), tone: w.tone };
}

function num(v: unknown): number | null {
    return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function context(r: SidebarRow): { pct: number; scale: number } | null {
    const raw = num(r.running_context_used_pct);
    if (raw === null) return null;
    const pct = Math.min(100, Math.max(0, raw));
    const scale = scaleStep(pct) as number | null;
    return scale === null ? null : { pct, scale };
}

function contextTone(scale: number): BodyTone | null {
    if (scale >= 5) return 'ctx5';
    return scale === 4 ? 'ctx4' : null;
}

function liveParts(r: SidebarRow, mode: 'cozy' | 'detailed'): LivePart[] {
    const out: LivePart[] = [];
    const words = mode === 'detailed';
    const shown = (kind: IconKind) => iconVisible(mode, kind);
    const running = num(r.subagents_running);
    if (running !== null && running > 0 && shown('agents')) {
        const total = Math.max(running, num(r.subagents_total) ?? running);
        out.push({
            kind: 'agents',
            attrs: {
                type: 'button',
                class: 'session-row-live__part',
                'data-live': 'agents',
                ...(r.session_id ? { 'data-subagents-session-id': String(r.session_id), 'data-subagents-session': r.name } : {}),
                tabindex: '-1',
                'aria-haspopup': r.session_id ? 'dialog' : undefined,
                'aria-label': t('sidebar.row.agents_icon.title', { count: running, total }),
            },
            svg: glyphSvg('users', 11),
            count: t('sidebar.row.live.agents_count', { running, total }),
            unit: words ? t('sidebar.row.live.agents_unit', { count: total }) : '',
        });
    }
    const open = num(r.background_open);
    if (open !== null && open > 0 && shown('shells')) {
        const n = Math.floor(open);
        out.push({
            kind: 'shells',
            attrs: { class: 'session-row-live__part', 'data-live': 'shells', role: 'img', 'aria-label': t('sidebar.row.shells_icon.title', { count: n }) },
            svg: glyphSvg('terminal', 11),
            count: String(n),
            unit: words ? t('sidebar.row.live.shells_unit', { count: n }) : '',
        });
    } else if (typeof r.parked_summary === 'string' && r.parked_summary && shown('shells')) {
        out.push({
            kind: 'shells',
            attrs: { class: 'session-row-live__part', 'data-live': 'shells', role: 'img', title: r.parked_summary, 'aria-label': r.parked_summary },
            svg: glyphSvg('terminal', 11),
            count: '',
            unit: '',
        });
    }
    const timer = timerChip(r as Parameters<typeof timerChip>[0], Date.now());
    if (timer && shown('timers')) {
        out.push({
            kind: 'timers',
            attrs: {
                type: 'button',
                class: 'session-row-live__part',
                'data-live': 'timers',
                ...(r.session_id ? { 'data-timers-session-id': String(r.session_id), 'data-timers-session': r.name } : {}),
                tabindex: '-1',
                'aria-haspopup': r.session_id ? 'dialog' : undefined,
                'aria-label': timer.title,
            },
            svg: glyphSvg('clock', 11),
            count: timer.text,
            unit: '',
        });
    }
    return out;
}

function measuredIdle(r: SidebarRow): boolean {
    return num(r.subagents_running) === 0 && num(r.background_open) === 0
        && !((num(r.timers_live) ?? 0) > 0) && r.workflow_active !== true && !r.parked_summary;
}

export function rowFlags(r: SidebarRow, led: LedPlan): BodyFlag[] {
    const out: BodyFlag[] = [];
    const status = normalizeStatus(led.status);
    if (status === 'question') out.push({ kind: 'permission', tone: 'warn', text: t('session.status.question') });
    if (led.hostOffline) out.push({ kind: 'host', tone: 'bad', text: t('session.status.host_offline', { host: led.hostOffline }) });
    if (status === 'dead') out.push({ kind: 'exited', tone: 'dim', text: exitedText(r) });
    const upd = r.agent_update as { running?: unknown; installed?: unknown; ready?: unknown } | null | undefined;
    if (upd && upd.ready === true && typeof upd.running === 'string' && typeof upd.installed === 'string') {
        out.push({ kind: 'update', tone: 'info', text: t('sidebar.row.flag.update_ready', { from: upd.running, to: upd.installed }) });
    }
    const ctx = context(r);
    const ctxTone = ctx ? contextTone(ctx.scale) : null;
    if (ctx && ctxTone) out.push({ kind: 'context', tone: ctxTone, text: t('sidebar.row.flag.context_full', { percent: Math.round(ctx.pct) }) });
    return out;
}

function exitedText(r: SidebarRow): string {
    const epoch = epochFromIso(r.last_work_at);
    return epoch === null ? t('sidebar.row.exited_unknown') : t('sidebar.row.exited', { age: ageLabel(epoch, ' ago') });
}

export function asleepText(r: SidebarRow): string {
    const epoch = epochFromIso(r.last_work_at);
    return epoch === null ? t('session.asleep.label') : t('sidebar.row.asleep_worked', { age: ageLabel(epoch, ' ago') });
}

export function rowBodyPlan(r: SidebarRow, mode: string, led: LedPlan | null): RowBodyPlan | null {
    if ((mode !== 'cozy' && mode !== 'detailed') || !led) return null;
    const status = normalizeStatus(led.status);
    const asleep = status === 'asleep' || !!r.asleep;
    const dead = status === 'dead';
    const epoch = epochFromIso(r.last_work_at);
    const model = modelPlan(r);
    const live = asleep || dead ? [] : liveParts(r, mode);
    const body: RowBodyPlan = {
        mode,
        rankTag: null,
        right: null,
        flagTone: null,
        model: null,
        modelName: '',
        effort: '',
        live,
        noLiveWork: !asleep && !dead && live.length === 0 && measuredIdle(r),
        ended: asleep ? { text: asleepText(r), tone: 'muted', dead: false }
            : dead ? { text: exitedText(r), tone: 'dim', dead: true } : null,
        flags: [],
        when: epoch === null ? '' : ageLabel(epoch, ' ago'),
    };
    if (mode === 'cozy') {
        if (!asleep && !dead && model) {
            body.model = model;
            body.modelName = String(r.running_model).trim().replace(/^claude-/, '');
            body.effort = typeof r.running_model_effort === 'string' ? r.running_model_effort.trim() : '';
        }
        return body;
    }
    const word = stateWord(led);
    body.right = asleep ? null : { text: word.text, tone: word.tone, kind: 'state' };
    body.flags = asleep ? [] : rowFlags(r, led);
    body.flagTone = body.flags[0]?.tone ?? null;
    return body;
}
