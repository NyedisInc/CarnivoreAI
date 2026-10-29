/* failed to load */
import { ledHtml, ledStateFor, normalizeInner, normalizeOuter } from './led';

export const STATUS_LABELS: Record<string, string> = {
    dead: 'dead - process exited',
    question: 'your turn - the agent needs your permission',
    notice: 'your turn - the agent wants your attention',
    working_subagent: 'working - a subagent is active',
    working: 'working',
    finished_unread: 'done - unread',
    idle: 'idle - read, nothing running',
    stopped: 'ended - the session is no longer running',
    asleep: 'asleep - stopped to free memory, wake it from the session menu',
    unknown: 'not measured',
    running: 'working',
};

export const HOST_OFFLINE_SUFFIX = ' offline';

export const ASLEEP_UNREAD_LABEL = 'asleep, flagged unread - wake it to follow up';

export const SOURCE_SUFFIX: Record<string, string> = {
    registry: "via the agent's own session record",
    pane: 'via the pane',
    transcript: 'via transcript',
    seed_row: 'via the session record',
    tmux: 'via tmux',
    // server stopped
    hook: 'via hooks',
};

/* no string layer */
export const ACTIVITY_HINT_SUFFIX: Record<string, string> = {
    shell: 'shell still running',
    codex_interrupted: 'interrupted, at the prompt',
    codex_turn_failed: 'last turn failed',
};

export const STATUS_DOT_CLASS: Record<string, string> = {
    dead: 'dead',
    question: 'question',
    notice: 'notice',
    working_subagent: 'working-subagent',
    working: 'working',
    finished_unread: 'finished-unread',
    idle: 'idle',
    stopped: 'stopped',
    asleep: 'asleep',
    unknown: 'unknown',
    running: 'working',
};

export function normalizeStatus(status: unknown): string {
    return Object.prototype.hasOwnProperty.call(STATUS_LABELS, status as string)
        ? (status as string)
        : 'unknown';
}

function questionLabel(status: unknown, activityHint: unknown): string {
    if (normalizeStatus(status) !== 'question' || typeof activityHint !== 'string') return '';
    if (activityHint === 'question') return 'your turn - question waiting';
    const m = /^question:(\d+)\/(\d+)$/.exec(activityHint);
    return m ? `your turn - question ${m[1]} of ${m[2]} waiting` : '';
}

export function labelWithSource(
    status: unknown,
    statusSource: unknown,
    activityHint?: unknown,
    parkedSummary?: unknown,
): string {
    const label =
        questionLabel(status, activityHint) || (STATUS_LABELS[normalizeStatus(status)] as string);
    const suffix = Object.prototype.hasOwnProperty.call(
        SOURCE_SUFFIX,
        statusSource as string,
    )
        ? (SOURCE_SUFFIX[statusSource as string] as string)
        : '';
    const hint = Object.prototype.hasOwnProperty.call(
        ACTIVITY_HINT_SUFFIX,
        activityHint as string,
    )
        ? (ACTIVITY_HINT_SUFFIX[activityHint as string] as string)
        : '';
    const head = suffix ? `${label} (${suffix})` : label;
    const withHint = hint ? `${head}, ${hint}` : head;
    return typeof parkedSummary === 'string' && parkedSummary
        ? `${withHint} - ${parkedSummary}`
        : withHint;
}

export function statusTitle(
    status: unknown,
    statusSource: unknown,
    activityHint: unknown,
    unread: unknown,
    parkedSummary?: unknown,
    hostOffline?: unknown,
    usageLimit?: unknown,
): string {
    if (normalizeStatus(status) === 'asleep' && unread) return ASLEEP_UNREAD_LABEL;
    if (typeof hostOffline === 'string' && hostOffline && normalizeStatus(status) !== 'asleep') {
        return `${hostOffline}${HOST_OFFLINE_SUFFIX}`;
    }
    const key = normalizeStatus(status);
    if (typeof usageLimit === 'string' && usageLimit && key !== 'asleep' && key !== 'dead' && key !== 'stopped') {
        return usageLimit;
    }
    return labelWithSource(status, statusSource, activityHint, parkedSummary);
}

export interface StatusSignals {
    unread?: boolean | null | undefined;
    startup_gate?: string | null | undefined;
    status_source?: string | null | undefined;
    activity_hint?: string | null | undefined;
    parked_summary?: string | null | undefined;
    transport?: string | null | undefined;
    host_offline?: string | null | undefined;
    usage_limit?: string | null | undefined;
    size?: string | null | undefined;
}

export function ledHtmlForStatus(
    status?: unknown,
    signals?: StatusSignals | null,
): string {
    const key = normalizeStatus(status);
    const s: StatusSignals = signals || {};
    const label = statusTitle(key, s.status_source, s.activity_hint, s.unread, s.parked_summary, s.host_offline, s.usage_limit);
    const cssClass = STATUS_DOT_CLASS[key] as string;
    const led = ledStateFor({
        activity_status: key,
        unread: s.unread,
        startup_gate: s.startup_gate,
        transport: s.transport,
        host_offline: s.host_offline,
        usage_limit: s.usage_limit,
    });
    return ledHtml({
        inner: led.inner,
        outer: led.outer,
        size: s.size,
        title: label,
        extraClass: `status-dot status-dot--${cssClass}`,
    });
}

/* could not */
export function ledAttrsForStatus(
    status?: unknown,
    signals?: StatusSignals | null,
): Record<string, string> {
    const key = normalizeStatus(status);
    const s: StatusSignals = signals || {};
    const label = statusTitle(key, s.status_source, s.activity_hint, s.unread, s.parked_summary, s.host_offline, s.usage_limit);
    const led = ledStateFor({
        activity_status: key,
        unread: s.unread,
        startup_gate: s.startup_gate,
        transport: s.transport,
        host_offline: s.host_offline,
        usage_limit: s.usage_limit,
    });
    return {
        class: `status-dot status-dot--${STATUS_DOT_CLASS[key] as string} status-led`,
        'data-inner': normalizeInner(led.inner),
        'data-outer': normalizeOuter(led.outer),
        role: 'img',
        title: label,
        'aria-label': label,
    };
}

export function labelFor(status: unknown): string {
    return STATUS_LABELS[normalizeStatus(status)] as string;
}
