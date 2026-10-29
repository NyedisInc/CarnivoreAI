
export const CTX_STATE_DEFAULTS = Object.freeze({
    globalAlpha: 1,
    globalCompositeOperation: 'source-over',
    fillStyle: '#000000',
    strokeStyle: '#000000',
    lineWidth: 1,
    lineCap: 'butt',
    lineJoin: 'miter',
    miterLimit: 10,
    lineDashOffset: 0,
    shadowBlur: 0,
    shadowColor: 'rgba(0, 0, 0, 0)',
    shadowOffsetX: 0,
    shadowOffsetY: 0,
    font: '10px sans-serif',
    textAlign: 'start',
    textBaseline: 'alphabetic',
    direction: 'inherit',
    filter: 'none',
    imageSmoothingEnabled: true,
    imageSmoothingQuality: 'low',
});

const IDENTITY = [1, 0, 0, 1, 0, 0];

export class FakeCanvasUnsupported extends Error {
    constructor(method, why) {
        super(`fake 2D context cannot answer ${method}(): ${why}`);
        this.name = 'FakeCanvasUnsupported';
        this.method = method;
    }
}

export function matMul(m, n) {
    return [
        m[0] * n[0] + m[2] * n[1],
        m[1] * n[0] + m[3] * n[1],
        m[0] * n[2] + m[2] * n[3],
        m[1] * n[2] + m[3] * n[3],
        m[0] * n[4] + m[2] * n[5] + m[4],
        m[1] * n[4] + m[3] * n[5] + m[5],
    ];
}

const DRAW_OPS = new Set([
    'fillRect', 'strokeRect', 'fill', 'stroke',
    'fillText', 'strokeText', 'drawImage', 'putImageData',
]);

export function createFakeCtx(canvasEl = null) {
    const stack = [{
        ...CTX_STATE_DEFAULTS,
        transform: IDENTITY.slice(),
        lineDash: [],
    }];
    const top = () => stack[stack.length - 1];

    const ctx = {
        canvas: canvasEl,
        drawCalls: 0,
        ops: [],
        unbalancedRestores: 0,
        get stackDepth() { return stack.length; },
        countOf(method) {
            let n = 0;
            for (const op of this.ops) if (op.method === method) n++;
            return n;
        },
        stateSnapshot() {
            return { ...top(), transform: top().transform.slice(), lineDash: top().lineDash.slice() };
        },
    };

    for (const key of Object.keys(CTX_STATE_DEFAULTS)) {
        Object.defineProperty(ctx, key, {
            enumerable: true,
            configurable: true,
            get() { return top()[key]; },
            set(v) { top()[key] = v; },
        });
    }

    const rec = (method, args) => {
        ctx.ops.push({ method, args: Array.prototype.slice.call(args) });
        if (DRAW_OPS.has(method)) ctx.drawCalls++;
    };

    const makeGradient = (kind, args) => {
        const stops = [];
        rec(kind, args);
        return {
            kind,
            stops,
            addColorStop(offset, color) { stops.push({ offset, color }); },
        };
    };

    Object.assign(ctx, {
        save() {
            rec('save', arguments);
            stack.push({
                ...top(),
                transform: top().transform.slice(),
                lineDash: top().lineDash.slice(),
            });
        },
        restore() {
            rec('restore', arguments);
            if (stack.length === 1) { ctx.unbalancedRestores++; return; }
            stack.pop();
        },
        reset() {
            rec('reset', arguments);
            stack.length = 0;
            stack.push({ ...CTX_STATE_DEFAULTS, transform: IDENTITY.slice(), lineDash: [] });
        },

        translate(x, y) {
            rec('translate', arguments);
            top().transform = matMul(top().transform, [1, 0, 0, 1, x, y]);
        },
        scale(x, y) {
            rec('scale', arguments);
            top().transform = matMul(top().transform, [x, 0, 0, y, 0, 0]);
        },
        rotate(rad) {
            rec('rotate', arguments);
            const c = Math.cos(rad);
            const s = Math.sin(rad);
            top().transform = matMul(top().transform, [c, s, -s, c, 0, 0]);
        },
        transform(a, b, c, d, e, f) {
            rec('transform', arguments);
            top().transform = matMul(top().transform, [a, b, c, d, e, f]);
        },
        setTransform(a, b, c, d, e, f) {
            rec('setTransform', arguments);
            if (a && typeof a === 'object') {
                top().transform = [a.a, a.b, a.c, a.d, a.e, a.f].map((n) => (typeof n === 'number' ? n : 0));
                return;
            }
            top().transform = [a, b, c, d, e, f].map((n) => (typeof n === 'number' ? n : 0));
        },
        resetTransform() {
            rec('resetTransform', arguments);
            top().transform = IDENTITY.slice();
        },
        getTransform() {
            const t = top().transform;
            return { a: t[0], b: t[1], c: t[2], d: t[3], e: t[4], f: t[5] };
        },

        beginPath() { rec('beginPath', arguments); },
        closePath() { rec('closePath', arguments); },
        moveTo() { rec('moveTo', arguments); },
        lineTo() { rec('lineTo', arguments); },
        bezierCurveTo() { rec('bezierCurveTo', arguments); },
        quadraticCurveTo() { rec('quadraticCurveTo', arguments); },
        arc() { rec('arc', arguments); },
        arcTo() { rec('arcTo', arguments); },
        ellipse() { rec('ellipse', arguments); },
        rect() { rec('rect', arguments); },
        roundRect() { rec('roundRect', arguments); },

        fill() { rec('fill', arguments); },
        stroke() { rec('stroke', arguments); },
        clip() { rec('clip', arguments); },
        fillRect() { rec('fillRect', arguments); },
        strokeRect() { rec('strokeRect', arguments); },
        clearRect() { rec('clearRect', arguments); },
        fillText() { rec('fillText', arguments); },
        strokeText() { rec('strokeText', arguments); },
        drawImage() { rec('drawImage', arguments); },
        putImageData() { rec('putImageData', arguments); },

        setLineDash(segments) {
            rec('setLineDash', arguments);
            top().lineDash = Array.isArray(segments) ? segments.slice() : [];
        },
        getLineDash() { return top().lineDash.slice(); },

        createLinearGradient() { return makeGradient('createLinearGradient', arguments); },
        createRadialGradient() { return makeGradient('createRadialGradient', arguments); },
        createConicGradient() { return makeGradient('createConicGradient', arguments); },
        createPattern() {
            rec('createPattern', arguments);
            return { setTransform() {} };
        },
        createImageData(w, h) {
            rec('createImageData', arguments);
            const width = Math.max(0, Math.round(Number(w) || 0));
            const height = Math.max(0, Math.round(Number(h) || 0));
            return { width, height, data: new Uint8ClampedArray(width * height * 4) };
        },

        measureText(text) {
            rec('measureText', arguments);
            const s = String(text ?? '');
            const m = /(\d+(?:\.\d+)?)px/.exec(String(top().font));
            const size = m ? parseFloat(m[1]) : 10;
            const width = s.length * size * 0.6;
            return {
                width,
                actualBoundingBoxLeft: 0,
                actualBoundingBoxRight: width,
                actualBoundingBoxAscent: size * 0.8,
                actualBoundingBoxDescent: size * 0.2,
                approximate: true,
            };
        },

        getImageData() {
            throw new FakeCanvasUnsupported(
                'getImageData',
                'nothing is rasterised, so read-back cannot report what was drawn',
            );
        },
        isPointInPath() {
            throw new FakeCanvasUnsupported(
                'isPointInPath',
                'no geometry is evaluated, so any boolean would be fiction',
            );
        },
        isPointInStroke() {
            throw new FakeCanvasUnsupported(
                'isPointInStroke',
                'no geometry is evaluated, so any boolean would be fiction',
            );
        },
    });

    return ctx;
}
