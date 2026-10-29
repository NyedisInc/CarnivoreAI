
const MARK_OPS = [
    'fillRect', 'strokeRect', 'fill', 'stroke', 'fillText', 'strokeText',
    'drawImage', 'putImageData',
];

const STROKE_OPS = new Set(['strokeRect', 'stroke', 'strokeText']);

export function styleAlpha(style) {
    if (style == null) return 0;
    if (typeof style === 'object') {
        if (Array.isArray(style.stops)) {
            if (style.stops.length === 0) return 0;
            return Math.max(...style.stops.map((s) => styleAlpha(s && s.color)));
        }
        return 1;
    }
    const s = String(style).trim();
    const fn = s.match(/^(?:rgba|hsla)\(([^)]*)\)$/i);
    if (fn) {
        const parts = fn[1].split(/[,/]/).map((x) => x.trim()).filter(Boolean);
        if (parts.length >= 4) {
            const a = parseFloat(parts[3]);
            return Number.isFinite(a) ? Math.max(0, Math.min(1, a)) : 1;
        }
        return 1;
    }
    const hex = s.match(/^#([0-9a-f]{3,8})$/i);
    if (hex) {
        const h = hex[1];
        if (h.length === 8) return parseInt(h.slice(6, 8), 16) / 255;
        if (h.length === 4) return parseInt(h[3] + h[3], 16) / 255;
        return 1;
    }
    if (s === 'transparent') return 0;
    return 1;
}

function coverage(name, args, ctx) {
    if (name !== 'fillRect' && name !== 'strokeRect') return NaN;
    const el = ctx.canvas;
    if (!el || !el.width || !el.height) return NaN;
    const [, , w, h] = args;
    if (typeof w !== 'number' || typeof h !== 'number') return NaN;
    const m = typeof ctx.getTransform === 'function' ? ctx.getTransform() : null;
    const sx = m ? Math.hypot(m.a, m.b) : 1;
    const sy = m ? Math.hypot(m.c, m.d) : 1;
    return Math.abs(w * sx * h * sy) / (el.width * el.height);
}

export function trackInk(ctx, clearCoverage = 0.9) {
    const samples = [];
    for (const name of MARK_OPS) {
        const original = ctx[name];
        if (typeof original !== 'function') continue;
        ctx[name] = function instrumented(...args) {
            const source = STROKE_OPS.has(name) ? ctx.strokeStyle : ctx.fillStyle;
            const ga = typeof ctx.globalAlpha === 'number' ? ctx.globalAlpha : 1;
            const cov = coverage(name, args, ctx);
            samples.push({
                name,
                alpha: ga * styleAlpha(source),
                isClear: Number.isFinite(cov)
                    && cov >= clearCoverage
                    && (ga * styleAlpha(source)) >= 0.99,
            });
            return original.apply(this, args);
        };
    }
    const decorative = () => samples.filter((s) => !s.isClear);
    return {
        peak: () => (samples.length ? Math.max(...samples.map((s) => s.alpha)) : 0),
        peakDecorative: () => {
            const d = decorative();
            return d.length ? Math.max(...d.map((s) => s.alpha)) : 0;
        },
        decorativeCount: () => decorative().length,
        samples: () => samples.slice(),
    };
}
