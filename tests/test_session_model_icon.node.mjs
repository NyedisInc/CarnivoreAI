
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function loadIcon() {
    const src = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'session-model-icon.js'), 'utf8');
    const ctx = { window: {}, console: { log() {} } };
    vm.createContext(ctx);
    vm.runInContext(src, ctx);
    return ctx.window.SessionModelIcon;
}

function loadFamilyIcon() {
    const src = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'agent-family-icon.js'), 'utf8');
    const ctx = { window: {}, console: { log() {} } };
    vm.createContext(ctx);
    vm.runInContext(src, ctx);
    return ctx.window.AgentFamilyIcon;
}

const Icon = loadIcon();
const FamilyIcon = loadFamilyIcon();
let failures = 0;
let passes = 0;

function test(name, fn) {
    try {
        fn();
        passes++;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures++;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.stack ? err.stack : err);
    }
}


test('every one of the five tiers reaches the stylesheet as its own value', () => {
    for (let t = 1; t <= 5; t++) {
        const html = Icon.html('some-model', t, 'high', null);
        assert.ok(html.includes(`data-model-tier="${t}"`), `tier ${t}`);
    }
});

test('the owner\'s two named models land on the tiers he named', () => {
    assert.ok(Icon.html('claude-opus-5', 4, 'high', null).includes('data-model-tier="4"'));
    assert.ok(Icon.html('claude-fable-5-1', 5, 'high', null).includes('data-model-tier="5"'));
});


test('the priciest model at the highest effort is topped', () => {
    assert.equal(Icon.isTopped(5, 'xhigh'), true);
    assert.equal(Icon.isTopped(5, 'max'), true);
});

test('the priciest model at ORDINARY effort is not topped', () => {
    assert.equal(Icon.isTopped(5, 'high'), false);
    assert.equal(Icon.isTopped(5, 'medium'), false);
});

test('a cheaper model at the highest effort is not topped', () => {
    assert.equal(Icon.isTopped(4, 'max'), false);
    assert.equal(Icon.isTopped(1, 'xhigh'), false);
});

test('NEITHER HALF MAY BE UNKNOWN: a null tier or effort is never topped', () => {
    assert.equal(Icon.isTopped(null, 'max'), false);
    assert.equal(Icon.isTopped(undefined, 'xhigh'), false);
    assert.equal(Icon.isTopped(5, null), false);
    assert.equal(Icon.isTopped(5, undefined), false);
    assert.equal(Icon.isTopped(null, null), false);
});

test('the sparkle element is drawn for the topped state and for nothing else', () => {
    const topped = Icon.html('claude-fable-5-1', 5, 'xhigh', null);
    assert.ok(topped.includes('session-sidebar-row-model__spark'));
    assert.ok(topped.includes('data-model-top="1"'));

    const plain = Icon.html('claude-fable-5-1', 5, 'high', null);
    assert.ok(!plain.includes('session-sidebar-row-model__spark'),
        'an ordinary row must emit no sparkle node at all');
    assert.ok(!plain.includes('data-model-top'));
});


test('an UNKNOWN MODEL draws no robot rather than a meaningless one', () => {
    assert.equal(Icon.html(null, null, null, null), '');
    assert.equal(Icon.html('', 3, 'high', null), '');
    assert.equal(Icon.html('   ', 3, 'high', null), '');
});

test('an UNPRICED model still draws a robot, just untinted', () => {
    const html = Icon.html('brand-new-model', null, 'high', null);
    assert.ok(html.includes('session-sidebar-row-model'), 'the robot is drawn');
    assert.ok(html.includes('data-model-tier=""'), 'and carries no tier to tint by');
});

test('a tier outside the five steps never reaches the stylesheet', () => {
    for (const bad of [0, 6, -1, 99, 2.7, NaN, Infinity, '5', true, {}]) {
        const html = Icon.html('m', bad, 'high', null);
        assert.ok(html.includes('data-model-tier=""'),
            `tier ${String(bad)} must not be emitted as a real step`);
    }
});

test('effort matching is case and whitespace tolerant', () => {
    assert.equal(Icon.isTopped(5, ' XHigh '), true);
    assert.equal(Icon.isTopped(5, 'MAX'), true);
});


test('a hostile model name cannot escape the attribute it lands in', () => {
    const html = Icon.html('a" onmouseover=alert(1) x="b', 3, 'high', null);
    assert.ok(!html.includes('a" onmouseover'),
        'the raw quote must not close the attribute');
    assert.ok(html.includes('&quot; onmouseover'), 'it is escaped instead');
});

test('a hostile effort string cannot escape either', () => {
    const html = Icon.html('m', 3, 'high" onload="x', null);
    assert.ok(!html.includes('high" onload'), 'the raw quote must not escape');
    assert.ok(html.includes('&quot; onload'));
});


test('the robot SVG renders at the provider mark\'s default size', () => {
    const providerSvg = FamilyIcon.svg('claude');
    const providerSize = providerSvg.match(/width="(\d+)"/);
    assert.ok(providerSize, 'provider svg must carry a numeric width');

    const robotHtml = Icon.html('claude-opus-5', 4, 'high', null);
    const robotSize = robotHtml.match(/<svg width="(\d+)" height="(\d+)"/);
    assert.ok(robotSize, 'robot svg must carry a numeric width/height');

    assert.equal(robotSize[1], providerSize[1],
        'robot svg width must equal the provider mark\'s default size');
    assert.equal(robotSize[2], providerSize[1],
        'robot svg height must equal the provider mark\'s default size');
});

test('the robot\'s SLOT (.session-sidebar-row-model) is the same box as ' +
    'the provider mark\'s slot (.session-sidebar-row-provider)', () => {
    const css = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'css', 'session-sidebar-row-controls.css'),
        'utf8');

    const providerBlock = css.match(/\.session-sidebar-row-provider\s*\{([^}]*)\}/);
    const modelBlock = css.match(/\.session-sidebar-row-model\s*\{([^}]*)\}/);
    assert.ok(providerBlock, 'provider slot rule must exist');
    assert.ok(modelBlock, 'model slot rule must exist');

    const providerWidth = providerBlock[1].match(/width:\s*(\d+)px/);
    const providerHeight = providerBlock[1].match(/height:\s*(\d+)px/);
    const modelWidth = modelBlock[1].match(/width:\s*(\d+)px/);
    const modelHeight = modelBlock[1].match(/height:\s*(\d+)px/);
    assert.ok(providerWidth && providerHeight, 'provider slot must set width and height');
    assert.ok(modelWidth && modelHeight, 'model slot must set width and height');

    assert.equal(modelWidth[1], providerWidth[1],
        'the model slot must be as wide as the provider slot');
    assert.equal(modelHeight[1], providerHeight[1],
        'the model slot must be as tall as the provider slot');
});

function loadIconWithEffort() {
    const ctx = { window: {}, console: { log() {} } };
    vm.createContext(ctx);
    for (const name of ['effort-level.js', 'session-model-icon.js']) {
        vm.runInContext(fs.readFileSync(
            path.join(__dirname, '..', 'client', 'js', name), 'utf8'), ctx);
    }
    return ctx.window.SessionModelIcon;
}

test('the robot shimmers only at xhigh, max and ultracode (issue #852)', () => {
    const I = loadIconWithEffort();
    const cls = (effort) => {
        const m = I.html('claude-opus-5', 3, effort).match(/^<span class="([^"]*)"/);
        assert.ok(m, 'the robot renders');
        return m[1];
    };
    assert.equal(cls('xhigh'), 'session-sidebar-row-model effort-level effort--xhigh');
    assert.equal(cls('max'), 'session-sidebar-row-model effort-level effort--max');
    assert.equal(cls(' ULTRACODE '), 'session-sidebar-row-model effort-level effort--ultracode');
    for (const effort of ['low', 'medium', 'high', null, undefined, '', 'auto']) {
        assert.equal(cls(effort), 'session-sidebar-row-model', String(effort));
    }
});

test('index.html loads effort-level.js before the robot, and its sheet after the sidebar sheets', () => {
    const html = fs.readFileSync(path.join(__dirname, '..', 'client', 'index.html'), 'utf8');
    const script = html.indexOf('/static/js/effort-level.js');
    const robot = html.indexOf('/static/js/session-model-icon.js');
    assert.ok(script > 0 && script < robot, `${script} < ${robot}`);
    const sheet = html.indexOf('/static/css/effort-level.css');
    const tint = html.indexOf('/static/css/session-sidebar-row-controls.css');
    assert.ok(tint > 0 && sheet > tint, 'the effort colour must outrank the tier tint');
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
