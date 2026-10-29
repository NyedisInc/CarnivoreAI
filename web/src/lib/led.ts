
export const INNER_STATES = Object.freeze([
    'working',
    'waiting-permission',
    'waiting-input',
    'notice',
    'idle',
    'done',
    'dead',
    'disconnected',
    'asleep',
    'asleep-unread',
    'limit',
    'unknown',
] as const);

export const OUTER_STATES = Object.freeze([
    'active',
    'steady',
    'unread',
    'off',
    'dim',
] as const);

export type InnerState = (typeof INNER_STATES)[number];

export type OuterState = (typeof OUTER_STATES)[number];

const INNER_FALLBACK: InnerState = 'unknown';

const OUTER_FALLBACK: OuterState = 'dim';

export const INNER_LABELS: Readonly<Record<InnerState, string>> = Object.freeze({
    working: 'working',
    'waiting-permission': 'stopped - waiting on your permission',
    'waiting-input': 'stopped - waiting on you',
    notice: 'still working - wants your attention',
    idle: 'idle - already read',
    done: 'done',
    dead: 'dead - the process exited',
    disconnected: 'disconnected - no live connection to this session',
    asleep: 'asleep - stopped to free memory, wake it from the session menu',
    'asleep-unread': 'asleep, flagged unread - wake it to follow up',
    limit: 'over limit',
    unknown: 'status not measured',
});

const OUTER_LABELS: Readonly<Record<OuterState, string>> = Object.freeze({
    active: '',
    steady: '',
    unread: 'unread',
    off: '',
    dim: '',
});

export function escapeAttr(value: unknown): string {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

export function normalizeInner(inner: unknown): InnerState {
    return (INNER_STATES as readonly string[]).indexOf(inner as string) >= 0
        ? (inner as InnerState)
        : INNER_FALLBACK;
}

export function normalizeOuter(outer: unknown): OuterState {
    return (OUTER_STATES as readonly string[]).indexOf(outer as string) >= 0
        ? (outer as OuterState)
        : OUTER_FALLBACK;
}

export function ledLabel(inner: InnerState, outer: OuterState): string {
    const head = INNER_LABELS[inner];
    const tail = OUTER_LABELS[outer];
    return tail ? head + ', ' + tail : head;
}

export interface LedHtmlOptions {
    inner?: unknown;
    outer?: unknown;
    size?: unknown;
    title?: unknown;
    extraClass?: unknown;
}

export interface LedState {
    inner: InnerState;
    outer: OuterState;
}

/* aria-label="working" box-shadow title="working" */
export function ledHtml(opts?: LedHtmlOptions | null): string {
    const o: LedHtmlOptions = opts || {};
    const inner = normalizeInner(o.inner);
    const outer = normalizeOuter(o.outer);
    const label = o.title == null ? ledLabel(inner, outer) : String(o.title);
    const size =
        typeof o.size === 'string' && /^[0-9]+(\.[0-9]+)?(px|rem|em)$/.test(o.size)
            ? o.size
            : '';
    const styleAttr = size ? ` style="--led-size: ${escapeAttr(size)}"` : '';
    const extra =
        typeof o.extraClass === 'string' && /^[A-Za-z0-9 _-]+$/.test(o.extraClass)
            ? o.extraClass.trim() + ' '
            : '';
    return (
        `<span class="${escapeAttr(extra)}status-led" data-inner="${escapeAttr(inner)}" ` +
        `data-outer="${escapeAttr(outer)}" role="img" ` +
        `title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}"` +
        `${styleAttr}></span>`
    );
}

export interface LedSignals {
    activity_status?: string | null | undefined;
    unread?: boolean | null | undefined;
    startup_gate?: string | null | undefined;
    transport?: string | null | undefined;
    host_offline?: string | null | undefined;
    usage_limit?: string | null | undefined;
}

/* label: ' */
export function hostOffline(row: object | null | undefined): string | null {
    const r = row as { host_key?: string | null; host_label?: string | null; host_state?: string | null } | null | undefined;
    if (!r || !r.host_key || r.host_key === 'local') return null;
    return (r.host_state || 'up') === 'up' ? null : r.host_label || r.host_key;
}

const LIMIT_MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

export function usageLimitLabel(row: object | null | undefined): string | null {
    const u = (row as { usage_limit?: { resets_at?: unknown } | null } | null | undefined)?.usage_limit;
    if (!u || typeof u !== 'object') return null;
    const at = typeof u.resets_at === 'string' ? new Date(u.resets_at) : null;
    if (!at || isNaN(at.getTime())) return 'over limit';
    const h = at.getHours();
    const m = at.getMinutes();
    const clock = `${h % 12 || 12}${m ? ':' + (m < 10 ? '0' : '') + m : ''}${h < 12 ? 'am' : 'pm'}`;
    return `over limit, resets ${LIMIT_MONTHS[at.getMonth()]} ${at.getDate()} ${clock}`;
}

export function ledStateFor(signals?: LedSignals | null): LedState {
    const s: LedSignals = signals || {};
    const status = s.activity_status;
    const unread = !!s.unread;
    const gate = s.startup_gate;

    if (status === 'asleep') {
        return { inner: unread ? 'asleep-unread' : 'asleep', outer: 'off' };
    }

    if (s.transport === 'disconnected' || s.host_offline) {
        return { inner: 'disconnected', outer: 'off' };
    }

    if (status === 'dead' || status === 'stopped') {
        return { inner: 'dead', outer: 'off' };
    }

    if (s.usage_limit) {
        return { inner: 'limit', outer: 'off' };
    }

    if (gate === 'awaiting_startup_prompt') {
        return { inner: 'waiting-input', outer: 'active' };
    }

    if (status === 'question') {
        return { inner: 'waiting-permission', outer: 'active' };
    }

    if (status === 'notice') {
        return { inner: 'notice', outer: 'active' };
    }

    if (status === 'working' || status === 'working_subagent' || status === 'running') {
        return { inner: 'working', outer: 'active' };
    }

    if (status === 'finished_unread') {
        return { inner: 'done', outer: 'unread' };
    }

    if (status === 'idle') {
        return unread
            ? { inner: 'done', outer: 'unread' }
            : { inner: 'idle', outer: 'steady' };
    }

    return { inner: 'unknown', outer: 'dim' };
}
