
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const NAVGEN_SRC = read('client/js/navigation-generation.js');
const ROUTER_SRC = read('client/js/router.js');

function sandbox(pathname, authed = true) {
    const el = () => ({ style: { display: 'none' }, textContent: '', addEventListener() {}, setAttribute() {} });
    const elements = { 'deep-link-error': el(), 'deep-link-error-text': el(), 'deep-link-error-dismiss': el() };
    const queue = [];
    const listeners = {};
    const written = [];
    const w = {
        location: { pathname, search: '' },
        addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); },
        dispatchEvent: () => true,
        Auth: { isAuthenticated: () => authed },
    };
    w.window = w;
    w.history = {
        pushState(_s, _t, p) { written.push(['push', p]); w.location.pathname = p; },
        replaceState(_s, _t, p) { written.push(['replace', p]); w.location.pathname = p; },
    };
    const box = {
        window: w,
        document: { getElementById: (id) => elements[id] || null },
        console: { log() {}, warn() {}, debug() {}, error() {} },
        setTimeout: (fn) => { queue.push(fn); return queue.length; },
        clearTimeout: () => {},
        Promise,
        CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
    };
    w.document = box.document;
    vm.createContext(box);
    vm.runInContext(NAVGEN_SRC, box, { filename: 'navigation-generation.js' });
    vm.runInContext(ROUTER_SRC, box, { filename: 'router.js' });
    return {
        w,
        banner: elements['deep-link-error'],
        written,
        listeners,
        run() { while (queue.length) queue.shift()(); },
    };
}

test('parseLayoutPath: a uuid, a malformed segment, and not a Layout path at all', () => {
    const { w } = sandbox('/');
    assert.deepEqual({ ...w.Router.parseLayoutPath('/layout/5f0c9d2e-1a2b') }, { uuid: '5f0c9d2e-1a2b' });
    assert.deepEqual({ ...w.Router.parseLayoutPath('/layout/..%2Fetc') }, { bad: '../etc' });
    assert.equal(w.Router.parseLayoutPath('/session/api'), null);
    assert.equal(w.Router.parseLayoutPath('/layout/a/b'), null);
});

test('a Layout link, signed in, is handed over at the boot IN PLACE OF home, once (issue #835)', () => {
    const s = sandbox('/layout/5f0c9d2e');
    const opened = [];
    let home = 0;
    s.w.CloudeWeb = { layoutPage: { openFromUrl: (uuid) => opened.push(uuid) } };
    s.w.Router.init();
    s.run();
    assert.deepEqual(opened, []);
    s.w.Router.bootScreen({ showLaunchpad: () => { home += 1; } });
    s.run();
    assert.deepEqual(opened, ['5f0c9d2e']);
    assert.equal(home, 0);
    assert.equal(s.w.LayoutDeepLinkTarget, null);
    assert.equal(s.banner.style.display, 'none');
    s.w.Router.bootScreen({ showLaunchpad: () => { home += 1; } });
    assert.equal(home, 1);
    assert.deepEqual(opened, ['5f0c9d2e']);
});

test('NEGATIVE CONTROL: a load on any other path paints home at the boot', () => {
    const s = sandbox('/');
    let home = 0;
    s.w.Router.init();
    s.run();
    s.w.Router.bootScreen({ showLaunchpad: () => { home += 1; } });
    assert.equal(home, 1);
});

test('NEGATIVE CONTROL: a /session link is not handed to the Layout page', () => {
    const s = sandbox('/session/api');
    const opened = [];
    s.w.CloudeWeb = { layoutPage: { openFromUrl: (uuid) => opened.push(uuid) } };
    s.w.Router.init();
    s.run();
    assert.deepEqual(opened, []);
});

test('signed out, the link waits for the authenticated event, then opens', () => {
    const s = sandbox('/layout/abc-1', false);
    const opened = [];
    s.w.CloudeWeb = { layoutPage: { openFromUrl: (uuid) => opened.push(uuid) } };
    s.w.Router.init();
    s.run();
    assert.deepEqual(opened, []);
    assert.equal(s.w.LayoutDeepLinkTarget, 'abc-1');
    s.listeners.authenticated.forEach((fn) => fn());
    s.run();
    assert.deepEqual(opened, ['abc-1']);
});

test('a malformed Layout link is refused with the banner and the address goes home', () => {
    const s = sandbox('/layout/bad%20id');
    s.w.CloudeWeb = { layoutPage: { openFromUrl: () => assert.fail('must not open') } };
    s.w.Router.init();
    assert.equal(s.banner.style.display, 'flex');
    s.run();
    assert.equal(s.w.location.pathname, '/');
});

test('enterSession keeps the open Layout address when the Layout page answers one', () => {
    const s = sandbox('/');
    const asked = [];
    s.w.CloudeWeb = { layoutPage: { pathFor: (slug) => { asked.push(slug); return slug === 'api' ? '/layout/L1' : null; } } };
    s.w.Router.enterSession('api');
    assert.equal(s.w.location.pathname, '/layout/L1');
    s.w.Router.enterSession('web');
    assert.equal(s.w.location.pathname, '/session/web');
    assert.deepEqual(asked, ['api', 'web']);
});

test('resetToLauncher keeps a Layout link read before the router ran, and resets one being left', () => {
    const s = sandbox('/layout/L1');
    let active = false;
    s.w.CloudeWeb = { layoutPage: { isActive: () => active } };
    s.w.Router.resetToLauncher();
    assert.equal(s.w.location.pathname, '/layout/L1', 'an unopened Layout link survives the boot reset');
    active = true;
    s.w.Router.resetToLauncher();
    assert.equal(s.w.location.pathname, '/', 'leaving an open Layout for home resets the address');
});
