
import assert from 'node:assert/strict';
import { createFakeCtx, FakeCanvasUnsupported, matMul } from './helpers/fake-canvas-2d.mjs';

let failures = 0;
let passes = 0;

/**
 * Run one named assertion, recording the outcome.
 * @param {string} name Test name shown in the output
 * @param {function(): void} fn Body; throws to fail
 * @returns {void}
 */
function test(name, fn) {
    try {
        fn();
        passes++;
        console.log('ok - ' + name);
    } catch (err) {
        failures++;
        console.error('NOT OK - ' + name);
        console.error(err && err.stack ? err.stack : err);
    }
}

test('fake ctx: restore() actually rolls back style and alpha', () => {
    const ctx = createFakeCtx();
    ctx.fillStyle = '#111111';
    ctx.strokeStyle = '#222222';
    ctx.globalAlpha = 0.25;
    ctx.lineWidth = 3;

    ctx.save();
    ctx.fillStyle = '#aaaaaa';
    ctx.strokeStyle = '#bbbbbb';
    ctx.globalAlpha = 0.9;
    ctx.lineWidth = 12;
    assert.equal(ctx.fillStyle, '#aaaaaa');
    assert.equal(ctx.globalAlpha, 0.9);

    ctx.restore();
    assert.equal(ctx.fillStyle, '#111111', 'fillStyle must be restored');
    assert.equal(ctx.strokeStyle, '#222222', 'strokeStyle must be restored');
    assert.equal(ctx.globalAlpha, 0.25, 'globalAlpha must be restored');
    assert.equal(ctx.lineWidth, 3, 'lineWidth must be restored');
});

test('fake ctx: restore() actually rolls back the transform', () => {
    const ctx = createFakeCtx();
    ctx.translate(10, 20);
    const before = ctx.getTransform();
    assert.deepEqual([before.e, before.f], [10, 20]);

    ctx.save();
    ctx.translate(5, 5);
    ctx.scale(2, 2);
    ctx.rotate(Math.PI / 2);
    const inner = ctx.getTransform();
    assert.notDeepEqual([inner.a, inner.e, inner.f], [before.a, before.e, before.f]);

    ctx.restore();
    const after = ctx.getTransform();
    assert.deepEqual(
        [after.a, after.b, after.c, after.d, after.e, after.f],
        [before.a, before.b, before.c, before.d, before.e, before.f],
        'the transform must be restored, not left at the inner value',
    );
});

test('fake ctx: nested save/restore unwinds in order and tracks depth', () => {
    const ctx = createFakeCtx();
    ctx.fillStyle = 'base';
    assert.equal(ctx.stackDepth, 1);

    ctx.save(); ctx.fillStyle = 'one';
    ctx.save(); ctx.fillStyle = 'two';
    ctx.save(); ctx.fillStyle = 'three';
    assert.equal(ctx.stackDepth, 4);

    ctx.restore(); assert.equal(ctx.fillStyle, 'two');
    ctx.restore(); assert.equal(ctx.fillStyle, 'one');
    ctx.restore(); assert.equal(ctx.fillStyle, 'base');
    assert.equal(ctx.stackDepth, 1);
    assert.equal(ctx.unbalancedRestores, 0);
});

test('fake ctx: save() copies lineDash by value, not by reference', () => {
    const ctx = createFakeCtx();
    ctx.setLineDash([1, 2]);
    ctx.save();
    ctx.setLineDash([9, 9, 9]);
    assert.deepEqual(ctx.getLineDash(), [9, 9, 9]);
    ctx.restore();
    assert.deepEqual(ctx.getLineDash(), [1, 2], 'the outer dash pattern must survive');
});

test('fake ctx: an unbalanced restore() is a no-op but is COUNTED', () => {
    const ctx = createFakeCtx();
    ctx.fillStyle = 'base';
    ctx.restore();
    assert.equal(ctx.fillStyle, 'base');
    assert.equal(ctx.stackDepth, 1);
    assert.equal(ctx.unbalancedRestores, 1);
});

test('fake ctx: the draw stream is recorded and drawCalls counts marks only', () => {
    const ctx = createFakeCtx();
    ctx.beginPath();
    ctx.arc(1, 2, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.clearRect(0, 0, 10, 10);
    ctx.fillRect(0, 0, 1, 1);

    assert.deepEqual(
        ctx.ops.map((o) => o.method),
        ['beginPath', 'arc', 'fill', 'clearRect', 'fillRect'],
        'every call must land in the ops stream in order',
    );
    assert.deepEqual(ctx.ops[1].args, [1, 2, 3, 0, Math.PI * 2], 'args must be captured');
    assert.equal(ctx.drawCalls, 2);
    assert.equal(ctx.countOf('arc'), 1);
});

test('fake ctx: the methods three effect authors had to work around all exist', () => {
    const ctx = createFakeCtx();
    const required = [
        'save', 'restore', 'rotate', 'translate', 'scale', 'beginPath', 'arc',
        'stroke', 'fill', 'moveTo', 'lineTo', 'closePath', 'clip', 'rect',
        'ellipse', 'setTransform', 'resetTransform', 'getTransform',
        'strokeRect', 'clearRect', 'setLineDash', 'getLineDash', 'measureText',
        'bezierCurveTo', 'quadraticCurveTo', 'arcTo', 'createConicGradient',
    ];
    const missing = required.filter((m) => typeof ctx[m] !== 'function');
    assert.deepEqual(missing, [], `the double is missing: ${missing.join(', ')}`);
});

test('fake ctx: unanswerable calls throw rather than inventing a value', () => {
    const ctx = createFakeCtx();
    for (const m of ['getImageData', 'isPointInPath', 'isPointInStroke']) {
        assert.throws(() => ctx[m](0, 0, 1, 1), FakeCanvasUnsupported,
            `${m}() must refuse rather than return fiction`);
    }
    assert.equal(ctx.measureText('abc').approximate, true);
});

test('fake ctx: matMul composes transforms the way canvas does', () => {
    const t = matMul([1, 0, 0, 1, 10, 0], [2, 0, 0, 2, 0, 0]);
    assert.deepEqual(t, [2, 0, 0, 2, 10, 0]);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) {
    console.error('FAILURES');
    process.exit(1);
}
console.log('ALL PASS');
