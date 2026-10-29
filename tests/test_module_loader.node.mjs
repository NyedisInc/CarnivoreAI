// ----------------------------------------------------------------------

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const SRC = fs.readFileSync(path.join(ROOT, 'client', 'js', 'module-loader.js'), 'utf8');

function makeFakeScript() {
    const listeners = { load: [], error: [] };
    return {
        tagName: 'SCRIPT',
        async: true,
        _srcHistory: [],
        _src: null,
        get src() { return this._src; },
        set src(v) { this._src = v; this._srcHistory.push(v); },
        parentNode: null,
        get nextSibling() {
            const kids = this.parentNode ? this.parentNode.children : [];
            return kids[kids.indexOf(this) + 1] || null;
        },
        addEventListener(type, cb) { listeners[type].push(cb); },
        removeEventListener(type, cb) {
            listeners[type] = listeners[type].filter((f) => f !== cb);
        },
        _fireLoad() { listeners.load.slice().forEach((cb) => cb()); },
        _fireError() { listeners.error.slice().forEach((cb) => cb()); },
    };
}

function makeFakeDocument() {
    const created = [];
    const doc = {
        head: {
            children: [],
            appendChild(el) { created.push(el); el.parentNode = this; this.children.push(el); },
            insertBefore(el, ref) {
                created.push(el);
                el.parentNode = this;
                const at = ref ? this.children.indexOf(ref) : -1;
                if (at === -1) this.children.push(el); else this.children.splice(at, 0, el);
            },
            removeChild(el) { this.children = this.children.filter((c) => c !== el); el.parentNode = null; },
        },
        createElement(tag) {
            assert.equal(tag, 'script', 'module-loader.js must only create <script> elements');
            return makeFakeScript();
        },
    };
    return { doc, created };
}

function loadModuleLoader() {
    const { doc, created } = makeFakeDocument();
    const sandbox = {
        window: {},
        document: doc,
        console: { log() {}, warn() {}, error() {}, debug() {} },
        setTimeout,
        clearTimeout,
        Promise,
    };
    sandbox.window.window = sandbox.window;
    vm.createContext(sandbox);
    vm.runInContext(SRC, sandbox, { filename: 'module-loader.js' });
    assert.ok(sandbox.window.ModuleLoader, 'module-loader.js must define window.ModuleLoader');
    return { ModuleLoader: sandbox.window.ModuleLoader, created };
}

test('every element is created and appended in document order before any resolves', () => {
    const { ModuleLoader, created } = loadModuleLoader();
    const urls = ['/static/js/a.js', '/static/js/b.js', '/static/js/c.js'];
    ModuleLoader.loadFamily('fam', urls);
    assert.deepEqual(created.map((el) => el._src), urls,
        'elements must be created/appended in the family\'s given order');
    assert.ok(created.every((el) => el.async === false),
        'every element must set async=false so parallel download does not reorder execution');
});

test('execution order is preserved when downloads complete out of order', async () => {
    const { ModuleLoader, created } = loadModuleLoader();
    const urls = ['/static/js/first.js', '/static/js/second.js'];
    const p = ModuleLoader.loadFamily('archive-order-test', urls);
    assert.equal(created.length, 2);
    created[1]._fireLoad();
    created[0]._fireLoad();
    const result = await p;
    assert.equal(result.ok, true);
    assert.deepEqual(created.map((el) => el._src), urls);
});

test('opening a family twice while loading returns the SAME promise and injects nothing twice', async () => {
    const { ModuleLoader, created } = loadModuleLoader();
    const urls = ['/static/js/a.js', '/static/js/b.js'];
    const p1 = ModuleLoader.loadFamily('archive', urls);
    const p2 = ModuleLoader.loadFamily('archive', urls);
    assert.equal(p1, p2, 'a second call while loading must return the identical promise');
    assert.equal(created.length, 2, 'no second set of elements may be created while the first is in flight');
    created.forEach((el) => el._fireLoad());
    await p1;
});

test('a family already loaded resolves immediately with no new DOM work', async () => {
    const { ModuleLoader, created } = loadModuleLoader();
    const urls = ['/static/js/only.js'];
    const p1 = ModuleLoader.loadFamily('config-editor', urls);
    created[0]._fireLoad();
    const first = await p1;
    assert.equal(first.cached, false);
    assert.equal(ModuleLoader.status('config-editor'), ModuleLoader.STATUS_LOADED);

    const before = created.length;
    const second = await ModuleLoader.loadFamily('config-editor', urls);
    assert.equal(second.ok, true);
    assert.equal(second.cached, true);
    assert.equal(created.length, before, 'a loaded family must create no new script elements');
});

test('a failed resource is retried with a FRESH element at the same position, and only that resource', async () => {
    const { ModuleLoader, created } = loadModuleLoader();
    const urls = ['/static/js/flaky.js', '/static/js/steady.js'];
    const p = ModuleLoader.loadFamily('retry-test', urls, { maxRetries: 2, retryDelayMs: 1 });
    assert.equal(created.length, 2, 'both elements are created up front, not one at a time');
    const head = created[0].parentNode;

    created[1]._fireLoad();
    created[0]._fireError();

    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.equal(created.length, 3, 'the retry creates exactly one new element');
    const retry = created[2];
    assert.ok(retry !== created[0], 'a retry must not reuse the element that already started');
    assert.equal(created[0]._srcHistory.length, 1, 'the failed element\'s src is never reassigned');
    assert.ok(retry._src.includes('_retry=1'), 'the retry carries a cache-busting marker');
    assert.deepEqual(head.children.map((c) => c._src.replace(/\?.*/, '')), urls, 'the retry sits where the failed element stood');
    retry._fireLoad();

    const result = await p;
    assert.equal(result.ok, true, 'the family must still succeed once the retried resource loads');
});

test('a family retry re-requests only the urls that failed, never one that already ran', async () => {
    const { ModuleLoader, created } = loadModuleLoader();
    const urls = ['/static/js/ran.js', '/static/js/dies.js'];
    const p1 = ModuleLoader.loadFamily('partial', urls, { maxRetries: 0, retryDelayMs: 1 });
    created[0]._fireLoad();
    created[1]._fireError();
    await assert.rejects(p1);
    const p2 = ModuleLoader.loadFamily('partial', urls, { maxRetries: 0, retryDelayMs: 1 });
    assert.equal(created.length, 3, 'only the failed url gets a new element');
    assert.ok(created[2]._src.startsWith('/static/js/dies.js'));
    created[2]._fireLoad();
    assert.equal((await p2).ok, true);
});

test('a family exhausts retries and REJECTS, naming the url that never loaded', async () => {
    const { ModuleLoader, created } = loadModuleLoader();
    const urls = ['/static/js/never-arrives.js', '/static/js/fine.js'];
    const p = ModuleLoader.loadFamily('doomed', urls, { maxRetries: 2, retryDelayMs: 1 });

    created[1]._fireLoad();

    created[0]._fireError();
    await new Promise((resolve) => setTimeout(resolve, 20));
    created[2]._fireError();
    await new Promise((resolve) => setTimeout(resolve, 30));
    created[3]._fireError();

    await assert.rejects(
        p,
        (err) => {
            assert.match(err.message, /doomed/, 'the rejection must name the family');
            assert.match(err.message, /never-arrives\.js/, 'the rejection must name the failed URL');
            return true;
        },
    );
    assert.equal(ModuleLoader.status('doomed'), ModuleLoader.STATUS_FAILED);
});

test('a family that failed is retried FRESH on the next call, not remembered as permanently failed', async () => {
    const { ModuleLoader, created } = loadModuleLoader();
    const urls = ['/static/js/sometimes.js'];
    const p1 = ModuleLoader.loadFamily('flaky-family', urls, { maxRetries: 0, retryDelayMs: 1 });
    created[0]._fireError();
    await assert.rejects(p1);
    assert.equal(ModuleLoader.status('flaky-family'), ModuleLoader.STATUS_FAILED);

    const p2 = ModuleLoader.loadFamily('flaky-family', urls, { maxRetries: 0, retryDelayMs: 1 });
    assert.notEqual(p1, p2, 'a failed family must start a genuinely new attempt, not replay the rejected promise');
    assert.equal(created.length, 2, 'the fresh attempt creates its own element rather than reusing the failed one');
    created[1]._fireLoad();
    const result = await p2;
    assert.equal(result.ok, true);
    assert.equal(ModuleLoader.status('flaky-family'), ModuleLoader.STATUS_LOADED);
});

test('status() reports unloaded for a family never requested', () => {
    const { ModuleLoader } = loadModuleLoader();
    assert.equal(ModuleLoader.status('never-asked-for'), ModuleLoader.STATUS_UNLOADED);
});
