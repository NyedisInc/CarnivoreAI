
import { createEffect, readVar, rgbTriple } from '../_shared/effects-base.js';

const TILE_SIZE = 28;

const STRIPE_PITCH = 8;

const STRIPE_ALPHA = 0.032;

const SWEEP_PERIOD_MS = 34000;

const SWEEP_BAND_FRACTION = 0.22;

const SWEEP_ALPHA = 0.055;

const PULSE_PERIOD_MS = 22000;

const PULSE_ALPHA = 0.05;

function buildHazardPattern(ctx, tint) {
    const tile = document.createElement('canvas');
    tile.width = TILE_SIZE;
    tile.height = TILE_SIZE;
    const tctx = tile.getContext('2d');
    if (!tctx) return null;
    tctx.fillStyle = `rgba(${tint}, ${STRIPE_ALPHA})`;
    const stripeW = 3;
    for (let y = 0; y < TILE_SIZE; y++) {
        for (let x = -TILE_SIZE; x < TILE_SIZE * 2; x += STRIPE_PITCH) {
            tctx.fillRect(x + y, y, stripeW, 1);
        }
    }
    return ctx.createPattern(tile, 'repeat');
}

function setup(ctx, _env) {
    const bg = readVar('--color-bg-page', '#02080a');
    const accent = readVar('--color-accent', '#33ff66');
    const warning = readVar('--color-warning', '#ffd700');
    const accentTint = rgbTriple(accent, '51, 255, 102');
    return {
        pattern: buildHazardPattern(ctx, accentTint),
        bg,
        sweepTint: accentTint,
        panelTint: rgbTriple(warning, '255, 215, 0'),
    };
}

function paintBase(ctx, env, state) {
    ctx.fillStyle = state.bg;
    ctx.fillRect(0, 0, env.width, env.height);
    if (state.pattern) {
        ctx.fillStyle = state.pattern;
        ctx.fillRect(0, 0, env.width, env.height);
    }
}

function drawPanelPulse(ctx, env, state, t) {
    const phase = (t % PULSE_PERIOD_MS) / PULSE_PERIOD_MS;
    const alpha = PULSE_ALPHA * (0.4 + 0.6 * (0.5 + 0.5 * Math.sin(phase * Math.PI * 2)));
    const cx = env.width * 0.86;
    const cy = env.height * 0.14;
    const r = Math.max(env.width, env.height) * 0.22;
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
    grad.addColorStop(0, `rgba(${state.panelTint}, ${alpha})`);
    grad.addColorStop(1, `rgba(${state.panelTint}, 0)`);
    ctx.fillStyle = grad;
    ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
}

function draw(ctx, env, state, t) {
    paintBase(ctx, env, state);

    const bandW = env.width * SWEEP_BAND_FRACTION;
    const travel = env.width + bandW;
    const x = ((t % SWEEP_PERIOD_MS) / SWEEP_PERIOD_MS) * travel - bandW;

    const grad = ctx.createLinearGradient(x, 0, x + bandW, 0);
    grad.addColorStop(0, `rgba(${state.sweepTint}, 0)`);
    grad.addColorStop(0.5, `rgba(${state.sweepTint}, ${SWEEP_ALPHA})`);
    grad.addColorStop(1, `rgba(${state.sweepTint}, 0)`);
    ctx.fillStyle = grad;
    ctx.fillRect(x, 0, bandW, env.height);

    drawPanelPulse(ctx, env, state, t);
}

function staticFrame(ctx, env, state) {
    paintBase(ctx, env, state);
    drawPanelPulse(ctx, env, state, PULSE_PERIOD_MS / 4);
}

const effect = createEffect({
    id: 'alien',
    fps: 14,
    fpsMobile: 8,
    background: '#02080a',
    setup,
    draw,
    staticFrame,
});

export const init = effect.init;
export const destroy = effect.destroy;
export const getStatus = effect.getStatus;
export default effect;
