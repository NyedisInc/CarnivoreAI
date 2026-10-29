
import { createEffect } from '../_shared/effects-base.js';

function makeStreak(width, height, seed) {
    const len = 40 + Math.random() * 60;
    return {
        x: Math.random() * width,
        y: seed ? Math.random() * height : -len - Math.random() * height * 0.5,
        len,
        w: Math.random() < 0.7 ? 1 : 2,
        speed: 6 + Math.random() * 8,
        alpha: 0.18 + Math.random() * 0.42,
    };
}

function setup(_ctx, env) {
    const density = env.isMobile ? 40 : 80;
    const streaks = new Array(density);
    for (let i = 0; i < density; i++) {
        streaks[i] = makeStreak(env.width, env.height, true);
    }
    return { streaks };
}

function draw(ctx, env, state) {
    const { streaks } = state;
    const w = env.width;
    const h = env.height;

    ctx.fillStyle = 'rgba(10, 14, 26, 0.35)';
    ctx.fillRect(0, 0, w, h);

    for (let i = 0; i < streaks.length; i++) {
        const s = streaks[i];
        const grad = ctx.createLinearGradient(s.x, s.y, s.x, s.y + s.len);
        grad.addColorStop(0, 'rgba(0, 80, 140, 0)');
        grad.addColorStop(0.6, `rgba(0, 140, 200, ${s.alpha * 0.55})`);
        grad.addColorStop(1, `rgba(0, 212, 255, ${s.alpha})`);
        ctx.fillStyle = grad;
        ctx.fillRect(s.x, s.y, s.w, s.len);

        s.y += s.speed;
        if (s.y > h + 8) {
            streaks[i] = makeStreak(w, h, false);
        }
    }
}

const effect = createEffect({
    id: 'blade_runner',
    canvasId: 'blade-runner-rain',
    fps: 30,
    fpsMobile: 15,
    background: '#0a0e1a',
    setup,
    draw,
    // nothing at all
});

export const init = effect.init;
export const destroy = effect.destroy;
export const getStatus = effect.getStatus;
export default effect;
