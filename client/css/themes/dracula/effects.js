
import { createEffect, readVar, rgbTriple } from '../_shared/effects-base.js';

const HUE_CYCLE_MS = 90000;

const BREATHE_PERIOD_MS = 34000;

const PEAK_ALPHA = 0.05;

function lerpTriple(a, b, f) {
    const pa = a.split(',').map(Number);
    const pb = b.split(',').map(Number);
    const out = pa.map((v, i) => Math.round(v + (pb[i] - v) * f));
    return out.join(', ');
}

function setup(_ctx, _env) {
    const bg = readVar('--color-bg-page', '#1e1f29');
    const hues = [
        rgbTriple(readVar('--color-accent', '#bd93f9'), '189, 147, 249'),
        rgbTriple(readVar('--color-accent-strong', '#ff95d2'), '255, 149, 210'),
        rgbTriple(readVar('--color-info', '#8be9fd'), '139, 233, 253'),
        rgbTriple(readVar('--color-success', '#50fa7b'), '80, 250, 123'),
    ];
    return { bg, hues };
}

function currentHue(hues, t, offset) {
    const frac = (((t / HUE_CYCLE_MS) + offset) % 1 + 1) % 1;
    const scaled = frac * hues.length;
    const i = Math.floor(scaled) % hues.length;
    const j = (i + 1) % hues.length;
    return lerpTriple(hues[i], hues[j], scaled - Math.floor(scaled));
}

function drawBlooms(ctx, env, state, t) {
    const maxEdge = Math.max(env.width, env.height);
    const spots = [
        { cx: env.width * 0.88, cy: env.height * 0.10, base: 0.30, hueOffset: 0, phase: 0 },
        { cx: env.width * 0.10, cy: env.height * 0.92, base: 0.26, hueOffset: 0.5, phase: Math.PI },
    ];
    for (const s of spots) {
        const tint = currentHue(state.hues, t, s.hueOffset);
        const breathe = (t / BREATHE_PERIOD_MS) * Math.PI * 2 + s.phase;
        const level = 0.55 + 0.45 * Math.sin(breathe);
        const alpha = PEAK_ALPHA * level;
        const r = maxEdge * s.base * (0.9 + 0.1 * level);
        const grad = ctx.createRadialGradient(s.cx, s.cy, 0, s.cx, s.cy, r);
        grad.addColorStop(0, `rgba(${tint}, ${alpha})`);
        grad.addColorStop(1, `rgba(${tint}, 0)`);
        ctx.fillStyle = grad;
        ctx.fillRect(s.cx - r, s.cy - r, r * 2, r * 2);
    }
}

function draw(ctx, env, state, t) {
    ctx.fillStyle = state.bg;
    ctx.fillRect(0, 0, env.width, env.height);
    drawBlooms(ctx, env, state, t);
}

function staticFrame(ctx, env, state) {
    ctx.fillStyle = state.bg;
    ctx.fillRect(0, 0, env.width, env.height);
    drawBlooms(ctx, env, state, 0);
}

const effect = createEffect({
    id: 'dracula',
    fps: 12,
    fpsMobile: 8,
    background: '#1e1f29',
    setup,
    draw,
    staticFrame,
});

export const init = effect.init;
export const destroy = effect.destroy;
export const getStatus = effect.getStatus;
export default effect;
