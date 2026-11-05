import { onEventFrame } from '../../cplugs/sdk/terminal';
import { t } from '../i18n/index.svelte';
import type { BadgeItem } from './slot';

export const BELL_LIGHT_MS = 1500;

export interface Progress { state: string; percent: number | null }

interface ProgressFrame { type?: string; session_id?: string; state?: string | null; percent?: number | null }

const STATES = new Set(['normal', 'error', 'indeterminate', 'paused']);
const TONE: Record<string, string | undefined> = { error: 'bad', paused: 'warn' };

let bars = $state<Record<string, Progress>>({});
let lit = $state<Record<string, true>>({});
const timers = new Map<string, ReturnType<typeof setTimeout>>();
let subscribed = false;
let repaintQueued = false;

function repaintSoon(): void {
    if (repaintQueued) return;
    repaintQueued = true;
    queueMicrotask(() => {
        repaintQueued = false;
        (globalThis as { SessionSidebar?: { repaint?(): void } }).SessionSidebar?.repaint?.();
    });
}

export function applyProgress(frame: ProgressFrame): void {
    const id = frame.session_id;
    if (!id) return;
    const next = { ...bars };
    if (frame.state && STATES.has(frame.state)) {
        const pct = typeof frame.percent === 'number' ? Math.max(0, Math.min(100, Math.round(frame.percent))) : null;
        next[id] = { state: frame.state, percent: pct };
    } else if (id in next) {
        delete next[id];
    } else {
        return;
    }
    bars = next;
    repaintSoon();
}

export function applyBell(frame: { session_id?: string }): void {
    const id = frame.session_id;
    if (!id) return;
    const old = timers.get(id);
    if (old) clearTimeout(old);
    if (!lit[id]) {
        lit = { ...lit, [id]: true };
        repaintSoon();
    }
    timers.set(id, setTimeout(() => {
        timers.delete(id);
        const next = { ...lit };
        delete next[id];
        lit = next;
        repaintSoon();
    }, BELL_LIGHT_MS));
}

function ensureSubscribed(): void {
    if (subscribed) return;
    const host = (globalThis as { AppEvents?: { subscribe?: unknown } }).AppEvents;
    if (!host || typeof host.subscribe !== 'function') return;
    subscribed = true;
    onEventFrame<ProgressFrame>('session.progress', applyProgress);
    onEventFrame<{ type?: string; session_id?: string }>('session.bell', applyBell);
}

function rowId(row: Record<string, unknown>): string | null {
    const top = row.session_id;
    if (typeof top === 'string' && top) return top;
    const inner = (row.session as { id?: unknown } | undefined)?.id;
    return typeof inner === 'string' && inner ? inner : null;
}

export function progressFor(sessionId: string | null | undefined): Progress | null {
    ensureSubscribed();
    return sessionId ? bars[sessionId] ?? null : null;
}

export function bellLit(sessionId: string | null | undefined): boolean {
    ensureSubscribed();
    return !!sessionId && lit[sessionId] === true;
}

export function progressLabel(p: Progress): { text: string; title: string } {
    const text = p.percent !== null && p.state !== 'indeterminate'
        ? t('session.progress.percent', { percent: String(p.percent) })
        : t(`session.progress.state.${p.state}`);
    return { text, title: `${t('session.progress.title')}: ${t(`session.progress.state.${p.state}`)}${p.state !== 'indeterminate' && p.percent !== null ? ` ${text}` : ''}` };
}

export function progressBadges(row: Record<string, unknown>): BadgeItem[] {
    const p = progressFor(rowId(row));
    if (!p) return [];
    const { text, title } = progressLabel(p);
    const striped = p.state === 'indeterminate' || p.percent === null;
    return [{ kind: 'progress', key: 'bar', text, title, tone: striped ? 'stripe' : TONE[p.state], pct: striped ? 100 : p.percent ?? 0 }];
}
