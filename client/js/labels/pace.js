
export const PACE_MIN_ELAPSED_PCT = 5;

export const PACE_YOUNG_WINDOW_JUDGED_USED_PCT = 25;

export const PACE_OVERRUN_PROJECTION_PCT = 120;

const HOUR_SECONDS = 3600;
const DAY_SECONDS = 24 * HOUR_SECONDS;

const FIVE_HOUR_KINDS = new Set(['five_hour', '5h']);
const SEVEN_DAY_PREFIX = 'seven_day';

function finite(value) {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function windowLengthSeconds(window) {
    if (!window) return null;
    const stated = finite(window.window_seconds);
    if (stated !== null && stated > 0) return stated;
    const kind = typeof window.kind === 'string' ? window.kind : '';
    const label = typeof window.label === 'string' ? window.label.trim().toLowerCase() : '';
    if (FIVE_HOUR_KINDS.has(kind) || FIVE_HOUR_KINDS.has(label)) return 5 * HOUR_SECONDS;
    if (kind.startsWith(SEVEN_DAY_PREFIX) || label === '7d') return 7 * DAY_SECONDS;
    return null;
}

export function elapsedPct(window, nowMs) {
    if (!window || finite(nowMs) === null) return null;
    const length = windowLengthSeconds(window);
    if (length === null) return null;
    const raw = typeof window.resets_at === 'string' ? Date.parse(window.resets_at) : NaN;
    if (!Number.isFinite(raw)) return null;
    const remaining = (raw - nowMs) / 1000;
    if (remaining <= 0) return null;
    const fraction = 1 - remaining / length;
    return Math.min(100, Math.max(0, fraction * 100));
}

export function paceState(usedPct, elapsed) {
    const used = finite(usedPct);
    const gone = finite(elapsed);
    if (used === null || gone === null) return null;
    if (used >= 100) return 'over';
    if (gone < PACE_MIN_ELAPSED_PCT && used < PACE_YOUNG_WINDOW_JUDGED_USED_PCT) return 'on';
    if (used <= gone) return 'on';
    const projected = (used / gone) * 100;
    return projected >= PACE_OVERRUN_PROJECTION_PCT ? 'over' : 'ahead';
}

export function paceOf(window, nowMs, absoluteStep) {
    const elapsed = elapsedPct(window, nowMs);
    const state = paceState(window ? window.used_pct : null, elapsed);
    return { elapsedPct: elapsed, state, scale: finite(absoluteStep) };
}
