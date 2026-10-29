
import { createEffect, readVar, rgbTriple } from '../_shared/effects-base.js';

const BUFFER_SCALE = 0.5;

const BANKS_DESKTOP = 6;
const BANKS_MOBILE = 4;

function makeBank(i, tints) {
    return {
        bx: 0.12 + Math.random() * 0.76,
        by: 0.12 + Math.random() * 0.76,
        ax: 0.06 + Math.random() * 0.14,
        ay: 0.04 + Math.random() * 0.1,
        px: 40000 + Math.random() * 70000,
        py: 47000 + Math.random() * 63000,
        phx: Math.random() * Math.PI * 2,
        phy: Math.random() * Math.PI * 2,
        r: 0.3 + Math.random() * 0.28,
        alpha: 0.05 + Math.random() * 0.035,
        tint: tints[i % tints.length],
    };
}

function setup(_ctx, env) {
    const bg = readVar('--color-bg-page', '#04080a');
    const tints = [
        rgbTriple(readVar('--color-accent', '#4a8472'), '74, 132, 114'),
        rgbTriple(readVar('--color-info', '#498397'), '73, 131, 151'),
        rgbTriple(readVar('--color-success', '#6e9a78'), '110, 154, 120'),
    ];

    const count = env.isMobile ? BANKS_MOBILE : BANKS_DESKTOP;
    const banks = new Array(count);
    for (let i = 0; i < count; i++) banks[i] = makeBank(i, tints);

    const bw = Math.max(1, Math.floor(env.width * BUFFER_SCALE));
    const bh = Math.max(1, Math.floor(env.height * BUFFER_SCALE));
    const buffer = document.createElement('canvas');
    buffer.width = bw;
    buffer.height = bh;
    const bctx = buffer.getContext('2d');

    return { banks, buffer, bctx, bw, bh, bg };
}

function renderField(state, t) {
    const { bctx, bw, bh, banks, bg } = state;
    bctx.fillStyle = bg;
    bctx.fillRect(0, 0, bw, bh);

    const maxEdge = Math.max(bw, bh);
    for (let i = 0; i < banks.length; i++) {
        const b = banks[i];
        const cx = (b.bx + b.ax * Math.sin((t / b.px) * Math.PI * 2 + b.phx)) * bw;
        const cy = (b.by + b.ay * Math.sin((t / b.py) * Math.PI * 2 + b.phy)) * bh;
        const r = b.r * maxEdge;

        const grad = bctx.createRadialGradient(cx, cy, 0, cx, cy, r);
        grad.addColorStop(0, `rgba(${b.tint}, ${b.alpha})`);
        grad.addColorStop(0.55, `rgba(${b.tint}, ${b.alpha * 0.45})`);
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
    id: 'lovecraft',
    fps: 12,
    fpsMobile: 8,
    background: '#04080a',
    setup,
    draw,
    staticFrame,
});

export const init = effect.init;
export const destroy = effect.destroy;
export const getStatus = effect.getStatus;
export default effect;
