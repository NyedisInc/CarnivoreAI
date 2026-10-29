
import { createEffect, readVar, rgbTriple } from '../_shared/effects-base.js';

const BREATHE_PERIOD_MS = 42000;

const DRIFT_PERIOD_MS = 97000;

const ALPHA_MIN = 0.015;
const ALPHA_MAX = 0.05;

const RADIUS_FRACTION = 0.55;

const DRIFT_FRACTION = 0.06;

function setup(_ctx, _env) {
    const bg = readVar('--color-bg-page', '#0a0a0a');
    const tint = rgbTriple(readVar('--color-accent', '#d77757'), '215, 119, 87');
    return { bg, tint };
}

function draw(ctx, env, state, t) {
    ctx.fillStyle = state.bg;
    ctx.fillRect(0, 0, env.width, env.height);

    const breathe = (Math.sin((t / BREATHE_PERIOD_MS) * Math.PI * 2) + 1) / 2;
    const alpha = ALPHA_MIN + (ALPHA_MAX - ALPHA_MIN) * breathe;

    const driftX = Math.sin((t / DRIFT_PERIOD_MS) * Math.PI * 2) * DRIFT_FRACTION;
    const driftY = Math.cos((t / (DRIFT_PERIOD_MS * 1.3)) * Math.PI * 2) * DRIFT_FRACTION;
    const cx = env.width * (0.5 + driftX);
    const cy = env.height * (0.46 + driftY);
    const r = Math.max(env.width, env.height) * RADIUS_FRACTION;

    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
    grad.addColorStop(0, `rgba(${state.tint}, ${alpha})`);
    grad.addColorStop(0.6, `rgba(${state.tint}, ${alpha * 0.4})`);
    grad.addColorStop(1, `rgba(${state.tint}, 0)`);
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, env.width, env.height);
}

function staticFrame(ctx, env, state) {
    draw(ctx, env, state, BREATHE_PERIOD_MS / 4);
}

const effect = createEffect({
    id: 'claude',
    fps: 15,
    fpsMobile: 10,
    background: '#0a0a0a',
    setup,
    draw,
    staticFrame,
});

export const init = effect.init;
export const destroy = effect.destroy;
export const getStatus = effect.getStatus;
export default effect;
