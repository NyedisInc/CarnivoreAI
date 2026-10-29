// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import assert from 'node:assert/strict';
import { createI18n } from '../client/js/i18n/runtime.js';
import {
    COST_BRIGHT_DECIMALS,
    COST_DECIMALS,
    SCALE_STOPS,
    WINDOW_SCALE_STOPS,
    accountLabels,
    compactContextTokens,
    compactTokens,
    contextLabels,
    pairText,
    resetAriaLabel,
    resetDuration,
    resetParts,
    resetText,
    scaleStep,
    scaleStepFor,
    splitAmountText,
    usagePanelLabels,
    windowLabels,
} from '../client/js/labels/usage-panel.js';

let failures = 0;
let passes = 0;
const queue = [];

/** Queue one named assertion block. Inputs: name, fn. Output: void. */
function test(name, fn) {
    queue.push([name, fn]);
}

/** Run every queued test in order. Inputs: none. Output: Promise<void>. */
async function runQueue() {
    for (const [name, fn] of queue) {
        try {
            await fn();
            passes++;
            console.log(`ok - ${name}`);
        } catch (err) {
            failures++;
            console.error(`NOT OK - ${name}`);
            console.error(err && err.stack ? err.stack : err);
        }
    }
}

const i18n = createI18n({ locale: 'en' });
const t = (key, params) => i18n.t(key, params);

function row(rows, key) {
    return rows.find((r) => r.key === key);
}

const NOW = Date.parse('2026-09-21T12:00:00Z');

function fromNow(ms) {
    return new Date(NOW + ms).toISOString();
}

test('the cost split keeps the cents bright and dims only past them', () => {
    assert.deepEqual(splitAmountText('$123.4567'), { lead: '$123.45', dim: '67' });

    const split = splitAmountText('$0.1234');
    assert.deepEqual(split, { lead: '$0.12', dim: '34' });
    assert.equal(split.lead + split.dim, '$0.1234');
});

test('the cost split is paint only and loses not one character', () => {
    for (const text of ['$0.0001', '$12.5000', '$1,234.5678', '$0.0000']) {
        const parts = splitAmountText(text);
        assert.ok(parts, `${text} should split`);
        assert.equal(parts.lead + parts.dim, text, `${text} must round trip`);
        assert.equal(parts.dim.length, COST_DECIMALS - COST_BRIGHT_DECIMALS);
        assert.equal(parts.lead.at(-3), '.', `${text} keeps the cents bright`);
    }
});

test('a fraction that is only cents, or shorter, refuses the split', () => {
    assert.equal(splitAmountText('$12.50'), null);
    assert.equal(splitAmountText('$0.00'), null);
    assert.equal(splitAmountText('$12.5'), null);
    assert.deepEqual(splitAmountText('$1.234'), { lead: '$1.23', dim: '4' });
});

test('a value with no fraction at all refuses the split', () => {
    assert.equal(splitAmountText('not available'), null);
    assert.equal(splitAmountText('$12'), null);
    assert.equal(splitAmountText('$12.'), null);
    assert.equal(splitAmountText('.50'), null);
    assert.equal(splitAmountText('window unknown.'), null);
    assert.equal(splitAmountText(null), null);
    assert.equal(splitAmountText(undefined), null);
});

test('the cost row carries the split, and the unavailable cost does not', () => {
    const ok = usagePanelLabels({ state: 'ok', cost_estimate_usd: 0.1234 }, t);
    const cost = row(ok.rows, 'cost');
    assert.ok(cost.parts, 'a measured cost splits');
    assert.equal(cost.parts.lead + cost.parts.dim, cost.text);
    assert.equal(cost.parts.dim.length, COST_DECIMALS - COST_BRIGHT_DECIMALS);

    const none = usagePanelLabels({ state: 'ok' }, t);
    const missing = row(none.rows, 'cost');
    assert.equal(missing.parts, null, 'an unmeasured cost has nothing to dim');
    assert.equal(missing.text, t('usage.cost.unavailable'));
});

test('an absent model or effort says so and never guesses one', () => {
    const unavailable = t('usage.cost.unavailable');
    const blank = usagePanelLabels({ state: 'ok' }, t);
    assert.equal(row(blank.rows, 'model').text, unavailable);
    assert.equal(row(blank.rows, 'model').spans.length, 1);
    const empty = usagePanelLabels({ state: 'ok', model: '', effort: '' }, t);
    assert.equal(row(empty.rows, 'model').text, unavailable);
});

test('one measured half still prints, with the other named as missing', () => {
    const unavailable = t('usage.cost.unavailable');
    assert.equal(pairText('Opus 5', null, t), `Opus 5 / ${unavailable}`);
    assert.equal(pairText(null, 'xhigh', t), `${unavailable} / xhigh`);
    assert.equal(pairText(null, null, t), unavailable);
    assert.equal(pairText('Opus 5', 'xhigh', t), 'Opus 5 / xhigh');
});

test('the vendor name prints, the raw id stays on the title, and the tier rides along', () => {
    const named = usagePanelLabels({
        state: 'ok',
        model: 'claude-opus-5-20260401',
        model_display_name: 'Opus 5',
        model_cost_tier: 4,
        effort: 'xhigh',
    }, t);
    const model = row(named.rows, 'model');
    assert.equal(model.text, 'Opus 5 / xhigh');
    assert.equal(model.spans[0].text, 'Opus 5');
    assert.equal(model.spans[0].tier, 4);
    assert.equal(model.spans[0].title, undefined, 'a model name carries no tooltip (#1209)');
});

test('a model the price table does not carry prints RAW and untinted', () => {
    const wild = usagePanelLabels({
        state: 'ok', model: 'gpt-6-astra', effort: 'medium',
    }, t);
    const model = row(wild.rows, 'model');
    assert.equal(model.spans[0].text, 'gpt-6-astra', 'the raw id, verbatim');
    assert.equal(model.spans[0].tier, null, 'and NO tier, so no tint at all');
    assert.equal(model.text, 'gpt-6-astra / medium');
});

test('a model and an effort are printed verbatim, never translated', () => {
    const pseudo = createI18n({ locale: 'pseudo' });
    const pt = (k, p) => pseudo.t(k, p);
    const marked = usagePanelLabels(
        { state: 'ok', model: 'claude-opus-5', model_display_name: 'Opus 5' },
        pt,
    );
    assert.equal(row(marked.rows, 'model').spans[0].text, 'Opus 5');
    assert.ok(row(marked.rows, 'model').label.includes('⟦'),
        'but the LABEL beside it is copy and is localised');
});

test('an undetermined account still draws its row and says so', () => {
    const group = accountLabels(null, t);
    assert.equal(group.rows.length, 1);
    assert.equal(group.rows[0].text, t('usage.cost.unavailable'));
    const panel = usagePanelLabels({ state: 'ok' }, t);
    assert.ok(row(panel.rows, 'account'), 'the panel always carries the account row');
});

test('a window the provider did not report is omitted, never zeroed', () => {
    const windows = windowLabels({
        name: 'work',
        credential_state: 'ok',
        windows: [
            { kind: 'five_hour', label: '5h', used_pct: 41.4 },
            { kind: 'seven_day', label: '7d', used_pct: null },
            { kind: 'seven_day_opus', label: '7d opus', used_pct: 8 },
        ],
    }, t, NOW);
    assert.deepEqual(windows.map((w) => w.key),
        ['window:five_hour', 'window:seven_day_opus']);
    assert.equal(windows[0].label, '5h', 'the LEDGER names the window, not us');
    assert.equal(windows[0].labelText, '5h:', 'the caption label carries the colon');
    assert.equal(windows[0].meterText, '5h window, 41 percent used');
    assert.equal(windows[0].percentText, '41%');
    assert.equal(windows[0].scale, 1, '41 percent burnt is the first band');
    assert.equal(windows[0].resetDuration, 'unknown', 'no resets_at on this fixture');
    assert.equal(windows[0].resetAria, 'reset unknown');
});

test('a window with a known reset carries its pace, and the bar colours by usage alone', () => {
    const at = (hours) => new Date(NOW + hours * 3600_000).toISOString();
    const windows = windowLabels({
        name: 'work',
        credential_state: 'ok',
        windows: [
            { kind: 'five_hour', label: '5h', used_pct: 32, resets_at: at(2) },
            { kind: 'five_hour', label: '5h ahead', used_pct: 34, resets_at: at(3.4) },
            { kind: 'five_hour', label: '5h over', used_pct: 64, resets_at: at(3.4) },
            { kind: 'seven_day', label: '7d', used_pct: 52, resets_at: at(24) },
            { kind: 'seven_day_opus', label: '7d opus', used_pct: 92, resets_at: at(1) },
            { kind: 'seven_day_sonnet', label: '7d sonnet', used_pct: 55, resets_at: null },
        ],
    }, t, NOW);
    assert.deepEqual(windows.map((w) => w.scale), [1, 1, 3, 2, 5, 2]);
    assert.deepEqual(windows.map((w) => w.paceState), ['on', 'ahead', 'over', 'on', 'on', null]);
    assert.equal(Math.round(windows[0].paceElapsedPct), 60);
    assert.equal(windows[0].paceState, 'on');
    assert.equal(windows[0].meterText,
        '5h window, 32 percent used, 60 percent of the window elapsed, on pace');
    assert.equal(windows[1].paceState, 'ahead');
    assert.equal(windows[2].paceState, 'over');
    assert.match(windows[2].meterText, /on track to run out before the reset$/);
    assert.equal(windows[5].paceElapsedPct, null, 'an unknown reset draws no pace, never a guess');
    assert.equal(windows[5].meterText, '7d sonnet window, 55 percent used');
});

test('an unhealthy login is a state on a row, not a missing row', () => {
    const expired = accountLabels({
        name: 'work', credential_state: 'expired', windows: [],
    }, t);
    assert.equal(row(expired.rows, 'login').text, t('usage.account.credential.expired'));
    const quiet = accountLabels({
        name: 'work', credential_state: 'ok', windows: [],
    }, t);
    assert.equal(row(quiet.rows, 'limits').text, t('usage.cost.unavailable'));
    const odd = accountLabels({
        name: 'work', credential_state: 'teapot', windows: [],
    }, t);
    assert.equal(row(odd.rows, 'login').text, t('usage.cost.unavailable'));
});

test('the limits row appears only when there is no bar to read instead', () => {
    const bars = accountLabels({
        name: 'work',
        credential_state: 'ok',
        windows: [{ kind: 'five_hour', label: '5h', used_pct: 10 }],
    }, t);
    assert.equal(row(bars.rows, 'limits'), undefined);
    assert.deepEqual(bars.rows.map((r) => r.key), ['account']);
});

test('the context bar measures what is SPENT, not what is left', () => {
    const ctx = contextLabels({
        context_remaining_pct: 43,
        context_used_tokens: 570000,
        context_window_tokens: 1000000,
    }, t);
    assert.equal(ctx.percentText, '57%', '100 minus the remaining 43');
    assert.equal(ctx.filled, 11, 'and the bar is 57 percent of 20 segments');
    assert.equal(ctx.scale, 3, '57 percent used is the third step');
    assert.ok(ctx.meterText.includes('used'), ctx.meterText);
    assert.equal(ctx.detail, '570,000 / 1,000,000');
    assert.equal(ctx.compactDetail, '570k/1M', 'the same fact, in the foot bar\'s compact form');
    assert.equal(ctx.title, 'context');
});

test('an unknown window draws an EMPTY bar with no step and says so', () => {
    const ctx = contextLabels({ context_used_tokens: 400 }, t);
    assert.equal(ctx.filled, 0);
    assert.equal(ctx.scale, null, 'no measurement, no colour');
    assert.equal(ctx.percentText, '');
    assert.equal(ctx.detail, t('usage.context.window_unknown'));
    assert.equal(ctx.compactDetail, t('usage.context.window_unknown'), 'the compact reading degrades the same way');

    const orphan = contextLabels({ context_remaining_pct: 20 }, t);
    assert.equal(orphan.filled, 0, 'no denominator, no fill');
    assert.equal(orphan.scale, null);
    assert.equal(orphan.percentText, '', 'and no number beside the empty bar');
    assert.equal(orphan.detail, t('usage.context.window_unknown'));
});

test('the compact token form truncates at every boundary', () => {
    assert.equal(compactTokens(0), '0');
    assert.equal(compactTokens(999), '999');
    assert.equal(compactTokens(1000), '1k');
    assert.equal(compactTokens(1500), '1k', 'truncated, not rounded to 2k');
    assert.equal(compactTokens(999999), '999k', 'and never rounded up to a million');
    assert.equal(compactTokens(1000000), '1.0M');
    assert.equal(compactTokens(446200000), '446.2M');
    assert.equal(compactTokens(null), null);
    assert.equal(compactTokens(undefined), null);
    assert.equal(compactTokens('1000'), null);
});

test('the foot bar\'s compact context form drops a decimal that says nothing', () => {
    assert.equal(compactContextTokens(447000), '447k', 'below a million matches compactTokens exactly');
    assert.equal(compactContextTokens(999999), '999k');
    assert.equal(compactContextTokens(1000000), '1M', 'an exact million: no manufactured .0');
    assert.equal(compactContextTokens(1200000), '1.2M', 'under ten million: one real decimal digit');
    assert.equal(compactContextTokens(9950000), '10M', 'rounds up to a round ten million: no manufactured .0');
    assert.equal(compactContextTokens(9949999), '9.9M', 'just under the boundary still carries a decimal');
    assert.equal(compactContextTokens(10000000), '10M', 'ten million and up: no decimal at all');
    assert.equal(compactContextTokens(12345678), '12M');
    assert.equal(compactContextTokens(null), null);
    assert.equal(compactContextTokens(undefined), null);
});

test('the tokens row composes all three input surfaces', () => {
    const panel = usagePanelLabels({
        state: 'ok',
        input_tokens: 1000,
        cache_read_input_tokens: 440000,
        cache_creation_input_tokens: 5200000,
        output_tokens: 234000,
    }, t);
    assert.equal(row(panel.rows, 'tokens').text, '5.6M/234k');
    const half = usagePanelLabels({ state: 'ok', input_tokens: 2000 }, t);
    assert.equal(row(half.rows, 'tokens').text, `2k/${t('usage.cost.unavailable')}`);
});

test('the five-stop scale steps at the owner s own thresholds', () => {
    assert.deepEqual(SCALE_STOPS, [25, 50, 80, 95]);
    const pairs = [[0, 1], [24, 1], [25, 2], [49, 2], [50, 3], [79, 3],
        [80, 4], [94, 4], [95, 5], [100, 5]];
    for (const [pct, step] of pairs) {
        assert.equal(scaleStep(pct), step, `${pct} percent should be step ${step}`);
    }
    assert.equal(scaleStep(null), null);
    assert.equal(scaleStep(undefined), null);
});

test('a boundary belongs to the HIGHER band, on any table of stops', () => {
    const stops = [10, 20, 30, 40];
    const pairs = [[0, 1], [9.9, 1], [10, 2], [19.9, 2], [20, 3],
        [29.9, 3], [30, 4], [39.9, 4], [40, 5], [100, 5]];
    for (const [pct, step] of pairs) {
        assert.equal(scaleStepFor(pct, stops), step,
            `${pct} percent should be step ${step}`);
    }
    assert.equal(scaleStepFor(null, stops), null);
    assert.equal(scaleStepFor(undefined, stops), null);
    assert.equal(scaleStepFor(25, SCALE_STOPS), scaleStep(25));
    assert.equal(scaleStepFor(94, SCALE_STOPS), scaleStep(94));
});

test('the window bars step at the owner s own window thresholds', () => {
    assert.deepEqual(WINDOW_SCALE_STOPS, [50, 60, 75, 90]);
    assert.equal(WINDOW_SCALE_STOPS.length, 4, 'four boundaries, five bands');
    assert.notDeepEqual(WINDOW_SCALE_STOPS, SCALE_STOPS);

    const step = (pct) => scaleStepFor(pct, WINDOW_SCALE_STOPS);
    const pairs = [[0, 1], [25, 1], [49.99, 1], [50, 2], [55, 2], [59.99, 2],
        [60, 3], [65, 3], [74.99, 3], [75, 4], [85, 4], [89.99, 4],
        [90, 5], [95, 5], [100, 5]];
    for (const [pct, band] of pairs) {
        assert.equal(step(pct), band, `${pct} percent should be band ${band}`);
    }
    assert.equal(step(null), null, 'no measurement, no colour');
});

test('a reset countdown picks its form at the hour and the day', () => {
    assert.deepEqual(resetParts(fromNow(59 * 60 * 1000 + 29 * 1000), NOW),
        { kind: 'minutes', minutes: 59 });
    assert.deepEqual(resetParts(fromNow(60 * 60 * 1000), NOW),
        { kind: 'hours', hours: 1, minutes: 0 });
    assert.deepEqual(resetParts(fromNow(24 * 3600 * 1000 - 31 * 1000), NOW),
        { kind: 'hours', hours: 23, minutes: 59 });
    const oneDay = resetParts(fromNow(24 * 3600 * 1000), NOW);
    assert.equal(oneDay.kind, 'days');
    assert.equal(oneDay.days, 1);
    assert.equal(oneDay.hours, 0);
    const threeDaysFive = resetParts(fromNow(3 * 24 * 3600 * 1000 + 5 * 3600 * 1000), NOW);
    assert.equal(threeDaysFive.kind, 'days');
    assert.equal(threeDaysFive.days, 3);
    assert.equal(threeDaysFive.hours, 5);
    assert.deepEqual(resetParts(fromNow(-60 * 1000), NOW), { kind: 'due' });
    assert.deepEqual(resetParts(fromNow(0), NOW), { kind: 'due' });
    assert.deepEqual(resetParts(null, NOW), { kind: 'none' });
    assert.deepEqual(resetParts('', NOW), { kind: 'none' });
    assert.deepEqual(resetParts('whenever', NOW), { kind: 'none' });
});

test('a reset a hair off the minute rounds to the minute it means', () => {
    const topOfHour = Date.parse('2026-10-01T05:00:00Z');
    assert.equal(resetParts('2026-10-01T04:59:59.521885Z', NOW).at, topOfHour);
    assert.equal(resetParts('2026-10-01T05:00:00.128Z', NOW).at, topOfHour);
    assert.equal(
        resetParts('2026-10-01T04:59:59.521885Z', NOW).at,
        resetParts('2026-10-01T05:00:00.128Z', NOW).at,
    );
    assert.equal(resetParts('2026-10-01T05:00:29.400Z', NOW).at, topOfHour);
});

test('every reset form is a sentence, and a missing one is not a zero', () => {
    assert.equal(resetText(fromNow(42 * 60 * 1000), t, NOW), 'reset in 42m');
    assert.equal(resetText(fromNow(5 * 3600 * 1000 + 6 * 60 * 1000), t, NOW),
        'reset in 5h 6m');
    assert.equal(resetText(fromNow(-1000), t, NOW), 'reset due');
    assert.equal(resetText(null, t, NOW), 'reset unknown');
    assert.notEqual(resetText(null, t, NOW), resetText(fromNow(0), t, NOW),
        'no stamp and a stamp that has passed are different facts');
    assert.equal(resetText(fromNow(3 * 24 * 3600 * 1000 + 5 * 3600 * 1000), t, NOW),
        'reset in 3d 5h');
    assert.equal(resetText(fromNow(24 * 3600 * 1000), t, NOW), 'reset in 1d 0h');
});

test('the short duration form carries no "reset"/"reset in" word at all', () => {
    assert.equal(resetDuration(fromNow(53 * 60 * 1000), t, NOW), '53m');
    assert.equal(resetDuration(fromNow(3 * 3600 * 1000 + 53 * 60 * 1000), t, NOW),
        '3h 53m');
    assert.equal(resetDuration(fromNow(4 * 24 * 3600 * 1000 + 3 * 3600 * 1000), t, NOW),
        '4d 3h');
    assert.equal(resetDuration(fromNow(-1000), t, NOW), 'due');
    assert.equal(resetDuration(null, t, NOW), 'unknown');
    for (const s of [resetDuration(fromNow(53 * 60 * 1000), t, NOW),
        resetDuration(fromNow(4 * 24 * 3600 * 1000), t, NOW)]) {
        assert.ok(!/reset/.test(s), `"${s}" still carries the word reset`);
    }
});

test('the reset aria sentence names a duration, or reads its own full sentence', () => {
    assert.equal(resetAriaLabel(fromNow(4 * 24 * 3600 * 1000 + 3 * 3600 * 1000), t, NOW),
        'resets in 4d 3h');
    assert.equal(resetAriaLabel(fromNow(53 * 60 * 1000), t, NOW), 'resets in 53m');
    assert.equal(resetAriaLabel(fromNow(-1000), t, NOW), 'reset due');
    assert.equal(resetAriaLabel(null, t, NOW), 'reset unknown');
});

test('the box is titled with the session name, and falls back when it cannot be', () => {
    const named = usagePanelLabels({ state: 'ok' }, t, { sessionName: 'Atlas-UI' });
    assert.equal(named.title, 'Atlas-UI');
    assert.equal(usagePanelLabels({ state: 'ok' }, t).title, t('usage.tokens.title'));
    assert.equal(usagePanelLabels({ state: 'ok' }, t, { sessionName: '   ' }).title,
        t('usage.tokens.title'), 'whitespace is not a name');
    // could not be read
    const absent = usagePanelLabels({ state: 'absent' }, t, { sessionName: 'argent' });
    assert.equal(absent.title, 'argent');
    assert.equal(absent.message, t('usage.state.absent'));
});

test('NEGATIVE CONTROL: every key these rows print really exists', () => {
    const keys = [
        'usage.tokens.title', 'usage.tokens.model_effort', 'usage.tokens.in_out',
        'usage.tokens.pair_separator', 'usage.tokens.count_separator',
        'usage.tokens.cost',
        'usage.context.title', 'usage.context.meter', 'usage.context.used',
        'usage.context.compact',
        'usage.account.name', 'usage.account.limits',
        'usage.account.login', 'usage.account.credential.expired',
        'usage.account.credential.missing', 'usage.account.credential.refused',
        'usage.account.credential.rate_limited',
        'usage.account.credential.error', 'usage.account.credential.unknown',
        'usage.window.meter', 'usage.window.meter_pace', 'usage.pace.on',
        'usage.pace.ahead', 'usage.pace.over', 'usage.window.reset_minutes',
        'usage.window.reset_hours', 'usage.window.reset_days',
        'usage.window.reset_due', 'usage.window.reset_unknown',
        'usage.window.duration_minutes', 'usage.window.duration_hours',
        'usage.window.duration_days', 'usage.window.duration_due',
        'usage.window.duration_unknown', 'usage.window.reset_aria',
    ];
    for (const key of keys) {
        assert.notEqual(t(key), key, `${key} is missing from the catalog`);
    }
    assert.equal(t('usage.account.nope'), 'usage.account.nope');
});

test('NEGATIVE CONTROL: a key nobody reads any more is gone from the catalog', () => {
    for (const key of ['usage.tokens.total', 'usage.tokens.model',
        'usage.tokens.effort', 'usage.tokens.input', 'usage.tokens.output',
        'usage.tokens.figure', 'usage.account.title']) {
        assert.equal(t(key), key, `${key} still has an entry but no reader`);
    }
});

await runQueue();
console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
