
import { paceOf } from './pace.js';

export const USAGE_PANEL_KEYS = {
    title: 'usage.tokens.title',
    modelEffort: 'usage.tokens.model_effort',
    tokens: 'usage.tokens.in_out',
    pairSeparator: 'usage.tokens.pair_separator',
    countSeparator: 'usage.tokens.count_separator',
    cost: 'usage.tokens.cost',
    costValue: 'usage.cost.value',
    costUnavailable: 'usage.cost.unavailable',
    contextTitle: 'usage.context.title',
    contextCaptionLabel: 'usage.context.caption_label',
    percent: 'usage.context.percent',
    used: 'usage.context.used',
    compact: 'usage.context.compact',
    windowUnknown: 'usage.context.window_unknown',
    meter: 'usage.context.meter',
    absent: 'usage.state.absent',
    unchecked: 'usage.state.unchecked',
    accountName: 'usage.account.name',
    accountLimits: 'usage.account.limits',
    accountLogin: 'usage.account.login',
    windowMeter: 'usage.window.meter',
    windowMeterPace: 'usage.window.meter_pace',
    paceOn: 'usage.pace.on',
    paceAhead: 'usage.pace.ahead',
    paceOver: 'usage.pace.over',
    windowCaptionLabel: 'usage.window.caption_label',
    resetMinutes: 'usage.window.reset_minutes',
    resetHours: 'usage.window.reset_hours',
    resetDays: 'usage.window.reset_days',
    resetDue: 'usage.window.reset_due',
    resetUnknown: 'usage.window.reset_unknown',
    durationMinutes: 'usage.window.duration_minutes',
    durationHours: 'usage.window.duration_hours',
    durationDays: 'usage.window.duration_days',
    durationDue: 'usage.window.duration_due',
    durationUnknown: 'usage.window.duration_unknown',
    resetAria: 'usage.window.reset_aria',
};

export const CREDENTIAL_STATE_KEYS = {
    expired: 'usage.account.credential.expired',
    missing: 'usage.account.credential.missing',
    refused: 'usage.account.credential.refused',
    rate_limited: 'usage.account.credential.rate_limited',
    error: 'usage.account.credential.error',
    unknown: 'usage.account.credential.unknown',
};

export const CONTEXT_SEGMENTS = 20;

export const SCALE_STOPS = [25, 50, 80, 95];

export const WINDOW_SCALE_STOPS = [50, 60, 75, 90];

export function windowMeterText(label, pct, pace, t) {
    const percent = Math.round(pct);
    if (!pace || pace.elapsedPct === null || pace.state === null) {
        return t(USAGE_PANEL_KEYS.windowMeter, { label, percent });
    }
    const words = pace.state === 'over' ? USAGE_PANEL_KEYS.paceOver
        : pace.state === 'ahead' ? USAGE_PANEL_KEYS.paceAhead : USAGE_PANEL_KEYS.paceOn;
    return t(USAGE_PANEL_KEYS.windowMeterPace, {
        label, percent, elapsed: Math.round(pace.elapsedPct), pace: t(words),
    });
}

export const COST_DECIMALS = 4;

const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

export function toNumber(value) {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function sumMeasured(values) {
    let total = null;
    for (const value of values || []) {
        const n = toNumber(value);
        if (n === null) continue;
        total = total === null ? n : total + n;
    }
    return total;
}

export function filledSegments(percent) {
    const pct = toNumber(percent);
    if (pct === null || pct <= 0) return 0;
    if (pct >= 100) return CONTEXT_SEGMENTS;
    const lit = Math.round((pct / 100) * CONTEXT_SEGMENTS);
    return Math.min(CONTEXT_SEGMENTS, Math.max(1, lit));
}

export function scaleStep(percent) {
    return scaleStepFor(percent, SCALE_STOPS);
}

export function scaleStepFor(percent, stops) {
    const pct = toNumber(percent);
    if (pct === null) return null;
    for (let i = 0; i < stops.length; i += 1) {
        if (pct < stops[i]) return i + 1;
    }
    return stops.length + 1;
}

/* anything at all */
export function compactTokens(value) {
    const n = toNumber(value);
    if (n === null || n < 0) return null;
    const whole = Math.floor(n);
    if (whole < 1000) return String(whole);
    if (whole < 1000000) return `${Math.floor(whole / 1000)}k`;
    return `${Math.floor(whole / 1000000)}.${Math.floor((whole % 1000000) / 100000)}M`;
}

/* anything at all nothing at all */
export function compactContextTokens(value) {
    const n = toNumber(value);
    if (n === null || n < 0) return null;
    const whole = Math.floor(n);
    if (whole < 1000000) return compactTokens(whole);
    const millions = whole / 1000000;
    if (millions >= 10) return `${Math.round(millions)}M`;
    const rounded = Math.round(millions * 10) / 10;
    return Number.isInteger(rounded) ? `${rounded}M` : `${rounded.toFixed(1)}M`;
}

export const COST_BRIGHT_DECIMALS = 2;

export function splitAmountText(text) {
    if (typeof text !== 'string') return null;
    const at = text.lastIndexOf('.');
    if (at <= 0 || at === text.length - 1) return null;
    const fraction = text.slice(at + 1);
    if (!/^[0-9]+$/.test(fraction)) return null;
    if (fraction.length <= COST_BRIGHT_DECIMALS) return null;
    const cut = at + 1 + COST_BRIGHT_DECIMALS;
    return { lead: text.slice(0, cut), dim: text.slice(cut) };
}

export function resetParts(resetsAt, nowMs) {
    if (typeof resetsAt !== 'string' || resetsAt === '') return { kind: 'none' };
    const parsed = Date.parse(resetsAt);
    if (!Number.isFinite(parsed)) return { kind: 'none' };
    const at = Math.round(parsed / MINUTE_MS) * MINUTE_MS;
    const now = toNumber(nowMs) === null ? Date.now() : nowMs;
    const delta = at - now;
    if (delta <= 0) return { kind: 'due' };
    const totalMinutes = Math.floor(delta / MINUTE_MS);
    if (delta < HOUR_MS) return { kind: 'minutes', minutes: totalMinutes };
    if (delta < DAY_MS) {
        return {
            kind: 'hours',
            hours: Math.floor(delta / HOUR_MS),
            minutes: totalMinutes % 60,
        };
    }
    const totalHours = Math.floor(delta / HOUR_MS);
    return {
        kind: 'days',
        days: Math.floor(totalHours / 24),
        hours: totalHours % 24,
        at,
    };
}

export function resetText(resetsAt, t, nowMs) {
    const parts = resetParts(resetsAt, nowMs);
    if (parts.kind === 'due') return t(USAGE_PANEL_KEYS.resetDue);
    if (parts.kind === 'minutes') {
        return t(USAGE_PANEL_KEYS.resetMinutes, { count: parts.minutes });
    }
    if (parts.kind === 'hours') {
        return t(USAGE_PANEL_KEYS.resetHours, {
            hours: parts.hours, minutes: parts.minutes,
        });
    }
    if (parts.kind === 'days') {
        return t(USAGE_PANEL_KEYS.resetDays, { days: parts.days, hours: parts.hours });
    }
    return t(USAGE_PANEL_KEYS.resetUnknown);
}

export function resetDuration(resetsAt, t, nowMs) {
    const parts = resetParts(resetsAt, nowMs);
    if (parts.kind === 'due') return t(USAGE_PANEL_KEYS.durationDue);
    if (parts.kind === 'minutes') {
        return t(USAGE_PANEL_KEYS.durationMinutes, { count: parts.minutes });
    }
    if (parts.kind === 'hours') {
        return t(USAGE_PANEL_KEYS.durationHours, {
            hours: parts.hours, minutes: parts.minutes,
        });
    }
    if (parts.kind === 'days') {
        return t(USAGE_PANEL_KEYS.durationDays, { days: parts.days, hours: parts.hours });
    }
    return t(USAGE_PANEL_KEYS.durationUnknown);
}

export function resetAriaLabel(resetsAt, t, nowMs) {
    const parts = resetParts(resetsAt, nowMs);
    if (parts.kind === 'due') return t(USAGE_PANEL_KEYS.resetDue);
    if (parts.kind === 'none') return t(USAGE_PANEL_KEYS.resetUnknown);
    return t(USAGE_PANEL_KEYS.resetAria, { time: resetDuration(resetsAt, t, nowMs) });
}

export function pairText(left, right, t, separatorKey) {
    return pairSpans(left, right, t, separatorKey).map((s) => s.text).join('');
}

export function pairSpans(left, right, t, separatorKey) {
    const unavailable = t(USAGE_PANEL_KEYS.costUnavailable);
    if (left === null && right === null) return [{ text: unavailable }];
    return [
        { text: left === null ? unavailable : left },
        { text: t(separatorKey || USAGE_PANEL_KEYS.pairSeparator) },
        { text: right === null ? unavailable : right },
    ];
}

function cleanText(value) {
    return typeof value === 'string' && value.trim() !== '' ? value : null;
}

/* could not */
export function usagePanelLabels(usage, t, options) {
    const opts = options || {};
    const title = cleanText(opts.sessionName) || t(USAGE_PANEL_KEYS.title);
    const state = usage && typeof usage.state === 'string' ? usage.state : 'unchecked';
    if (state !== 'ok') {
        const key = state === 'absent' ? USAGE_PANEL_KEYS.absent : USAGE_PANEL_KEYS.unchecked;
        return {
            state: state === 'absent' ? 'absent' : 'unchecked',
            title,
            message: t(key),
        };
    }

    const input = sumMeasured([
        usage.input_tokens,
        usage.cache_read_input_tokens,
        usage.cache_creation_input_tokens,
    ]);
    const output = toNumber(usage.output_tokens);
    const cost = toNumber(usage.cost_estimate_usd);
    const unavailable = t(USAGE_PANEL_KEYS.costUnavailable);
    const costText = cost === null
        ? unavailable
        : t(USAGE_PANEL_KEYS.costValue, { amount: cost.toFixed(COST_DECIMALS) });

    const rawModel = cleanText(usage.model);
    const modelText = cleanText(usage.model_display_name) || rawModel;
    const effortText = cleanText(usage.effort);
    const account = accountLabels(usage.account, t);

    const modelSpans = pairSpans(modelText, effortText, t);
    if (modelText !== null) {
        modelSpans[0].tier = toNumber(usage.model_cost_tier);
    }

    const rows = [
        {
            key: 'model',
            label: t(USAGE_PANEL_KEYS.modelEffort),
            text: pairText(modelText, effortText, t),
            spans: modelSpans,
        },
        {
            key: 'tokens',
            label: t(USAGE_PANEL_KEYS.tokens),
            text: pairText(
                compactTokens(input), compactTokens(output), t,
                USAGE_PANEL_KEYS.countSeparator,
            ),
        },
        {
            key: 'cost',
            label: t(USAGE_PANEL_KEYS.cost),
            text: costText,
            parts: cost === null ? null : splitAmountText(costText),
        },
        ...account.rows,
    ];

    return {
        state: 'ok',
        title,
        rows,
        context: contextLabels(usage, t),
        windows: windowLabels(usage.account, t, opts.now),
    };
}

export function accountLabels(account, t) {
    const unavailable = t(USAGE_PANEL_KEYS.costUnavailable);
    const named = account && typeof account === 'object';
    const rows = [{
        key: 'account',
        label: t(USAGE_PANEL_KEYS.accountName),
        text: named && cleanText(account.name) ? account.name : unavailable,
    }];
    if (!named) return { rows };
    const state = typeof account.credential_state === 'string'
        ? account.credential_state
        : '';
    if (state && state !== 'ok') {
        const key = CREDENTIAL_STATE_KEYS[state];
        rows.push({
            key: 'login',
            label: t(USAGE_PANEL_KEYS.accountLogin),
            text: key ? t(key) : unavailable,
        });
    } else if (!readableWindows(account).length) {
        rows.push({
            key: 'limits',
            label: t(USAGE_PANEL_KEYS.accountLimits),
            text: unavailable,
        });
    }
    return { rows };
}

function readableWindows(account) {
    const windows = account && Array.isArray(account.windows) ? account.windows : [];
    return windows.filter((w) => toNumber(w && w.used_pct) !== null);
}

/* label: ' */
export function windowLabels(account, t, nowMs) {
    return readableWindows(account).map((window) => {
        const pct = toNumber(window.used_pct);
        const label = typeof window.label === 'string' && window.label !== ''
            ? window.label
            : String(window.kind);
        const pace = paceOf(window, toNumber(nowMs) === null ? Date.now() : nowMs,
            scaleStepFor(pct, WINDOW_SCALE_STOPS));
        return {
            key: `window:${window.kind}`,
            label,
            labelText: t(USAGE_PANEL_KEYS.windowCaptionLabel, { label }),
            segments: CONTEXT_SEGMENTS,
            filled: filledSegments(pct),
            scale: pace.scale,
            paceElapsedPct: pace.elapsedPct,
            paceState: pace.state,
            percentText: t(USAGE_PANEL_KEYS.percent, { percent: Math.round(pct) }),
            meterText: windowMeterText(label, pct, pace, t),
            // reset in 4d 3h
            resetText: resetText(window.resets_at, t, nowMs),
            resetDuration: resetDuration(window.resets_at, t, nowMs),
            resetAria: resetAriaLabel(window.resets_at, t, nowMs),
        };
    });
}

export function contextLabels(usage, t) {
    const remaining = toNumber(usage && usage.context_remaining_pct);
    const used = toNumber(usage && usage.context_used_tokens);
    const window = toNumber(usage && usage.context_window_tokens);
    const known = window !== null;
    const usedPct = !known || remaining === null ? null : 100 - remaining;
    return {
        title: t(USAGE_PANEL_KEYS.contextTitle),
        captionLabel: t(USAGE_PANEL_KEYS.contextCaptionLabel, {
            label: t(USAGE_PANEL_KEYS.contextTitle),
        }),
        segments: CONTEXT_SEGMENTS,
        filled: filledSegments(usedPct),
        scale: scaleStep(usedPct),
        percentText: usedPct === null
            ? ''
            : t(USAGE_PANEL_KEYS.percent, { percent: Math.round(usedPct) }),
        meterText: usedPct === null
            ? t(USAGE_PANEL_KEYS.windowUnknown)
            : t(USAGE_PANEL_KEYS.meter, { percent: Math.round(usedPct) }),
        detail: known && used !== null
            ? t(USAGE_PANEL_KEYS.used, { used, window })
            : t(USAGE_PANEL_KEYS.windowUnknown),
        compactDetail: known && used !== null
            ? t(USAGE_PANEL_KEYS.compact, {
                used: compactContextTokens(used), window: compactContextTokens(window),
            })
            : t(USAGE_PANEL_KEYS.windowUnknown),
    };
}
