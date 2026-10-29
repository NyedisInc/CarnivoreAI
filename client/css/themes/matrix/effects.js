
import { createEffect } from '../_shared/effects-base.js';

const GLYPHS = (() => {
    const out = [];
    for (let cp = 0x30a0; cp <= 0x30ff; cp++) out.push(String.fromCharCode(cp));
    for (let i = 0; i < 10; i++) out.push(String(i));
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('').forEach((c) => out.push(c));
    return out;
})();

function pickGlyph() {
    return GLYPHS[(Math.random() * GLYPHS.length) | 0];
}

function setup(ctx, env) {
    const fontSize = env.width < 768 ? 13 : 16;
    const colCount = Math.max(1, Math.floor(env.width / fontSize));
    const columns = new Array(colCount);
    for (let i = 0; i < colCount; i++) {
        columns[i] = Math.random() * (env.height / fontSize);
    }
    ctx.font = `${fontSize}px "SF Mono", "Menlo", monospace`;
    ctx.textBaseline = 'top';
    return { fontSize, colCount, columns };
}

function draw(ctx, env, state) {
    const { fontSize, colCount, columns } = state;

    ctx.fillStyle = 'rgba(0, 0, 0, 0.06)';
    ctx.fillRect(0, 0, env.width, env.height);

    ctx.fillStyle = '#00ff41';
    for (let i = 0; i < colCount; i++) {
        const x = i * fontSize;
        const y = columns[i] * fontSize;
        const glyph = pickGlyph();
        if (Math.random() < 0.015) {
            ctx.fillStyle = '#ccffcc';
            ctx.fillText(glyph, x, y);
            ctx.fillStyle = '#00ff41';
        } else {
            ctx.fillText(glyph, x, y);
        }
        columns[i]++;
        if (y > env.height && Math.random() > 0.975) {
            columns[i] = 0;
        }
    }
}

const effect = createEffect({
    id: 'matrix',
    canvasId: 'matrix-rain',
    fps: 30,
    fpsMobile: 15,
    background: '#000000',
    setup,
    draw,
    // nothing at all
});

export const init = effect.init;
export const destroy = effect.destroy;
export const getStatus = effect.getStatus;
export default effect;
