
import { createEffect, readVar, rgbTriple } from '../_shared/effects-base.js';

const DRIFT_PERIOD_MS = 68000;

const BREATHE_PERIOD_MS = 31000;

const DRIFT_FRACTION = 0.34;

const BAND_WIDTH_FRACTION = 0.28;

const ALPHA_MIN = 0.012;
const ALPHA_MAX = 0.04;

function setup(_ctx, _env) {
    const bg = readVar('--color-bg-page', '#000000');
    const tint = rgbTriple(readVar('--color-accent', '#ffcc00'), '255, 204, 0');
    return { bg, tint };
}

function draw(ctx, env, state, t) {
    ctx.fillStyle = state.bg;
    ctx.fillRect(0, 0, env.width, env.height);

    const drift = Math.sin((t / DRIFT_PERIOD_MS) * Math.PI * 2);
    const cx = env.width * (0.5 + drift * DRIFT_FRACTION);
    const bandW = env.width * BAND_WIDTH_FRACTION;

    const breathe = (Math.sin((t / BREATHE_PERIOD_MS) * Math.PI * 2) + 1) / 2;
    const alpha = ALPHA_MIN + (ALPHA_MAX - ALPHA_MIN) * breathe;

    const grad = ctx.createLinearGradient(cx - bandW, 0, cx + bandW, 0);
    grad.addColorStop(0, `rgba(${state.tint}, 0)`);
    grad.addColorStop(0.5, `rgba(${state.tint}, ${alpha})`);
    grad.addColorStop(1, `rgba(${state.tint}, 0)`);
    ctx.fillStyle = grad;
    ctx.fillRect(cx - bandW, 0, bandW * 2, env.height);
}

function staticFrame(ctx, env, state) {
    draw(ctx, env, state, 0);
}

const effect = createEffect({
    id: 'hermes',
    fps: 14,
    fpsMobile: 10,
    background: '#000000',
    setup,
    draw,
    staticFrame,
});

export const init = effect.init;
export const destroy = effect.destroy;
export const getStatus = effect.getStatus;
export default effect;
