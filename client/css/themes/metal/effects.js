
import { createEffect, readVar, rgbTriple } from '../_shared/effects-base.js';

const GRAIN_TILE_W = 96;

const GRAIN_LINES = 48;

const GRAIN_ALPHA_MIN = 0.015;
const GRAIN_ALPHA_MAX = 0.04;

const SHEEN_PERIOD_MS = 42000;

const SHEEN_BAND_FRACTION = 0.20;

const SHEEN_ALPHA = 0.06;

function buildGrainPattern(ctx, tint) {
    const tile = document.createElement('canvas');
    tile.width = GRAIN_TILE_W;
    tile.height = 4;
    const tctx = tile.getContext('2d');
    if (!tctx) return null;
    for (let i = 0; i < GRAIN_LINES; i++) {
        const x = Math.random() * GRAIN_TILE_W;
        const alpha = GRAIN_ALPHA_MIN + Math.random() * (GRAIN_ALPHA_MAX - GRAIN_ALPHA_MIN);
        tctx.fillStyle = `rgba(${tint}, ${alpha})`;
        tctx.fillRect(x, 0, 1, 4);
    }
    return ctx.createPattern(tile, 'repeat');
}

function setup(ctx, _env) {
    const bg = readVar('--color-bg-page', '#050303');
    const fg = readVar('--color-fg-muted', '#9c948a');
    return {
        pattern: buildGrainPattern(ctx, rgbTriple(fg, '156, 148, 138')),
        bg,
        sheenTint: rgbTriple(readVar('--color-fg', '#E8E2D6'), '232, 226, 214'),
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

function drawSheen(ctx, env, state, t) {
    const ax = env.width;
    const ay = env.height * 0.35;
    const axisLen = Math.hypot(ax, ay);
    const bandW = axisLen * SHEEN_BAND_FRACTION;
    const travel = axisLen + bandW * 2;
    const center = ((t % SHEEN_PERIOD_MS) / SHEEN_PERIOD_MS) * travel - bandW;

    const clamp01 = (v) => Math.min(1, Math.max(0, v));
    const stopStart = clamp01((center - bandW) / axisLen);
    const stopMid = clamp01(center / axisLen);
    const stopEnd = clamp01((center + bandW) / axisLen);

    const grad = ctx.createLinearGradient(0, env.height * 0.65, ax, ay);
    grad.addColorStop(stopStart, `rgba(${state.sheenTint}, 0)`);
    grad.addColorStop(stopMid, `rgba(${state.sheenTint}, ${SHEEN_ALPHA})`);
    grad.addColorStop(stopEnd, `rgba(${state.sheenTint}, 0)`);
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, env.width, env.height);
}

function draw(ctx, env, state, t) {
    paintBase(ctx, env, state);
    drawSheen(ctx, env, state, t);
}

function staticFrame(ctx, env, state) {
    paintBase(ctx, env, state);
}

const effect = createEffect({
    id: 'metal',
    fps: 14,
    fpsMobile: 8,
    background: '#050303',
    setup,
    draw,
    staticFrame,
});

export const init = effect.init;
export const destroy = effect.destroy;
export const getStatus = effect.getStatus;
export default effect;
