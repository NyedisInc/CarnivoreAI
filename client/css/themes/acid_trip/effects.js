
import { createEffect, readVar, rgbTriple } from '../_shared/effects-base.js';

const BUFFER_SCALE = 0.5;

const BLOBS_DESKTOP = 5;
const BLOBS_MOBILE = 3;

function makeBlob(i, tints) {
    return {
        bx: 0.1 + Math.random() * 0.8,
        by: 0.1 + Math.random() * 0.8,
        ax: 0.08 + Math.random() * 0.16,
        ay: 0.06 + Math.random() * 0.14,
        px: 26000 + Math.random() * 19000,
        py: 31000 + Math.random() * 21000,
        phx: Math.random() * Math.PI * 2,
        phy: Math.random() * Math.PI * 2,
        r: 0.26 + Math.random() * 0.22,
        alpha: 0.035 + Math.random() * 0.02,
        tint: tints[i % tints.length],
    };
}

function setup(_ctx, env) {
    const bg = readVar('--color-bg-page', '#0e0420');
    const tints = [
        rgbTriple(readVar('--color-fg', '#FFEE00'), '255, 238, 0'),
        rgbTriple(readVar('--color-border', '#FF00C8'), '255, 0, 200'),
        rgbTriple(readVar('--color-accent', '#00FFE0'), '0, 255, 224'),
        rgbTriple(readVar('--color-success', '#00FF40'), '0, 255, 64'),
    ];

    const count = env.isMobile ? BLOBS_MOBILE : BLOBS_DESKTOP;
    const blobs = new Array(count);
    for (let i = 0; i < count; i++) blobs[i] = makeBlob(i, tints);

    const bw = Math.max(1, Math.floor(env.width * BUFFER_SCALE));
    const bh = Math.max(1, Math.floor(env.height * BUFFER_SCALE));
    const buffer = document.createElement('canvas');
    buffer.width = bw;
    buffer.height = bh;
    const bctx = buffer.getContext('2d');

    return { blobs, buffer, bctx, bw, bh, bg };
}

function renderField(state, t) {
    const { bctx, bw, bh, blobs, bg } = state;
    bctx.fillStyle = bg;
    bctx.fillRect(0, 0, bw, bh);

    const maxEdge = Math.max(bw, bh);
    for (let i = 0; i < blobs.length; i++) {
        const b = blobs[i];
        const cx = (b.bx + b.ax * Math.sin((t / b.px) * Math.PI * 2 + b.phx)) * bw;
        const cy = (b.by + b.ay * Math.sin((t / b.py) * Math.PI * 2 + b.phy)) * bh;
        const r = b.r * maxEdge;

        const grad = bctx.createRadialGradient(cx, cy, 0, cx, cy, r);
        grad.addColorStop(0, `rgba(${b.tint}, ${b.alpha})`);
        grad.addColorStop(0.5, `rgba(${b.tint}, ${b.alpha * 0.4})`);
        grad.addColorStop(1, `rgba(${b.tint}, 0)`);
        bctx.fillStyle = grad;
        bctx.fillRect(cx - r, cy - r, r * 2, r * 2);
    }
}

function draw(ctx, env, state, t) {
    if (!state.bctx) {
        ctx.fillStyle = state.bg;
        ctx.fillRect(0, 0, env.width, env.height);
        return;
    }
    renderField(state, t);
    ctx.drawImage(state.buffer, 0, 0, env.width, env.height);
}

function staticFrame(ctx, env, state) {
    draw(ctx, env, state, 0);
}

const effect = createEffect({
    id: 'acid_trip',
    fps: 14,
    fpsMobile: 10,
    background: '#0e0420',
    setup,
    draw,
    staticFrame,
});

export const init = effect.init;
export const destroy = effect.destroy;
export const getStatus = effect.getStatus;
export default effect;
