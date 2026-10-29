
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, '..');
const read = (...p) => fs.readFileSync(path.join(root, ...p), 'utf8');

const attachSrc = read('client', 'js', 'attachment-toast.js');
const toastSrc = read('client', 'js', 'toast.js');
// issue #55 split ToastManager's class body across three files that each
// extend ToastManager.prototype (client/js/api-toasts.js's pattern for
const toastGroupingSrc = read('client', 'js', 'toast-grouping.js');
const toastRenderSrc = read('client', 'js', 'toast-render.js');
const toastLifecycleSrc = read('client', 'js', 'toast-lifecycle.js');
const inputKindSrc = read('client', 'js', 'terminal-input-kind.js');
const sessionLabelSrc = read('client', 'js', 'session-label.js');
const summarySrc = read('client', 'js', 'session-status-summary.js');
const toastGroupSrc = read('client', 'js', 'toast-session-group.js');

let failures = 0;
let passes = 0;
const queue = [];

function test(name, fn) {
    queue.push([name, fn]);
}

async function runQueue() {
    for (const [name, fn] of queue) {
        try {
            await fn();
            passes++;
            console.log(`ok - ${name}`);
        } catch (err) {
            failures++;
            console.error(`NOT OK - ${name}`);
            console.error(err && err.stack ? err.stack : err);
        }
    }
}


class El {
    constructor(tag) {
        this.tagName = String(tag || 'div').toUpperCase();
        this.className = '';
        this.dataset = {};
        this.attributes = {};
        this.childNodes = [];
        this.parentNode = null;
        this.style = { setProperty() {} };
        this.classList = { add: () => {}, remove: () => {} };
        this._text = '';
    }
    get textContent() {
        if (this.childNodes.length === 0) return this._text;
        return this.childNodes.map((c) => c.textContent).join('');
    }
    set textContent(v) {
        this.childNodes = [];
        this._text = String(v == null ? '' : v);
    }
    appendChild(child) {
        this._text = '';
        child.parentNode = this;
        this.childNodes.push(child);
        return child;
    }
    removeChild(child) {
        const i = this.childNodes.indexOf(child);
        if (i !== -1) this.childNodes.splice(i, 1);
        child.parentNode = null;
        return child;
    }
    remove() {
        if (this.parentNode) this.parentNode.removeChild(this);
    }
    setAttribute(k, v) { this.attributes[k] = String(v); }
    getAttribute(k) {
        return Object.prototype.hasOwnProperty.call(this.attributes, k)
            ? this.attributes[k] : null;
    }
    addEventListener() {}
    _all() {
        const out = [];
        for (const c of this.childNodes) { out.push(c); out.push(...c._all()); }
        return out;
    }
    querySelectorAll(sel) {
        const cls = String(sel).replace(/^\./, '');
        return this._all().filter((e) => String(e.className).split(/\s+/).includes(cls));
    }
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

function makeSandbox(opts = {}) {
    const byId = new Map();
    const container = new El('div');
    byId.set('toast-container', container);
    if (opts.headerLabel !== undefined && opts.headerLabel !== '') {
        const h = new El('span');
        h.textContent = opts.headerLabel;
        byId.set('header-title-text', h);
    }
    const acked = [];
    const sandbox = {
        console: { log() {}, warn() {}, error() {} },
        setTimeout, clearTimeout, Promise, Map, Set, Array, Object, JSON,
        Math, Date, String, Number, Boolean,
        document: {
            getElementById: (id) => byId.get(id) || null,
            createElement: (tag) => new El(tag),
            addEventListener() {},
        },
        API: { ackToast: (id, s) => { acked.push([id, s]); return Promise.resolve(); } },
        acked,
        container,
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(inputKindSrc, sandbox);
    vm.runInContext(sessionLabelSrc, sandbox);
    vm.runInContext(summarySrc, sandbox);
    vm.runInContext(toastGroupSrc, sandbox);
    vm.runInContext(toastSrc, sandbox);
    vm.runInContext(toastGroupingSrc, sandbox);
    vm.runInContext(toastRenderSrc, sandbox);
    vm.runInContext(toastLifecycleSrc, sandbox);
    vm.runInContext(attachSrc, sandbox);
    return sandbox;
}

const plain = (o) => ({ ...o });

const termFor = (id) => ({ _sessionId: () => id });


test('a carriage return is a submit and a line feed is not', () => {
    const { AttachmentToast: A } = makeSandbox();
    assert.equal(A.isPromptSubmit('\r'), true);
    assert.equal(A.isPromptSubmit('\n'), false);
    assert.equal(A.isPromptSubmit(''), false);
    assert.equal(A.isPromptSubmit(undefined), false);
    assert.equal(A.isPromptSubmit('hello'), false);
});

test('shift+enter carries a carriage return and is still not a submit', () => {
    const { AttachmentToast: A } = makeSandbox();
    assert.equal(A.isPromptSubmit('\x1b\r'), false);
    assert.equal(A.isPromptSubmit('abc\x1b\r'), false);
    assert.equal(A.isPromptSubmit('\x1b\rline two\r'), true);
});

test('a mouse report carrying 0x0d is not a submit', () => {
    const { AttachmentToast: A } = makeSandbox();
    const x10 = '\x1b[M' + String.fromCharCode(32, 0x0d, 0x2d);
    assert.equal(A.isPromptSubmit(x10), false);
    const sgr = '\x1b[<35;13;13M';
    assert.equal(A.isPromptSubmit(sgr), false);
});


test('the declared mime type outranks the filename', () => {
    const { AttachmentToast: A } = makeSandbox();
    assert.deepEqual(plain(A.thumbSpecFor('', 'image/png')), { image: true, label: 'PNG' });
    assert.deepEqual(plain(A.thumbSpecFor('shot.JPG', '')), { image: true, label: 'JPG' });
    assert.equal(A.thumbSpecFor('', 'image/svg+xml').label, 'SVG');
});

test('a non-image gets a chip and never claims to be previewable', () => {
    const { AttachmentToast: A } = makeSandbox();
    assert.deepEqual(plain(A.thumbSpecFor('spec.pdf', '')), { image: false, label: 'PDF' });
    assert.deepEqual(plain(A.thumbSpecFor('a.tar.gz', '')), { image: false, label: 'GZ' });
    assert.equal(A.thumbSpecFor('notes.txt', 'text/plain').image, false);
    assert.equal(A.thumbSpecFor('archive.zip', 'application/zip').image, false);
    assert.equal(A.thumbSpecFor('', '').image, false);
    assert.equal(A.thumbSpecFor('', '').label, 'FILE');
});

test('an unusable extension degrades to the generic label', () => {
    const { AttachmentToast: A } = makeSandbox();
    assert.equal(A.thumbSpecFor('report.markdown', '').label, 'FILE');
    assert.equal(A.extensionOf('.zshrc'), '');
    assert.equal(A.extensionOf('trailing.'), '');
    assert.equal(A.extensionOf('a.tar.gz'), 'gz');
    assert.equal(A.extensionOf(''), '');
});

test('an svg is an image by type but is not drawn through a canvas', () => {
    const { AttachmentToast: A } = makeSandbox();
    assert.equal(A.thumbSpecFor('logo.svg', '').image, false);
});


test('a toast with a preview renders an img named after the file', () => {
    const s = makeSandbox();
    const card = new El('div');
    s.AttachmentToast.renderThumbs(card, [
        { attachment_name: 'shot.png', thumb_url: 'data:image/webp;base64,AA', thumb_label: 'PNG' },
    ]);
    const img = card.querySelector('toast__thumb-img');
    assert.ok(img, 'an attachment with a preview must render a picture');
    assert.equal(img.getAttribute('src'), 'data:image/webp;base64,AA');
    assert.equal(img.getAttribute('alt'), 'shot.png');
    assert.equal(card.querySelector('toast__thumb-name').textContent, 'shot.png');
});

test('a toast with no preview renders a chip and no img at all', () => {
    const s = makeSandbox();
    const card = new El('div');
    s.AttachmentToast.renderThumbs(card, [
        { attachment_name: 'spec.pdf', thumb_url: null, thumb_label: 'PDF' },
    ]);
    assert.equal(card.querySelector('toast__thumb-img'), null,
        'a file with no preview must not produce an <img> that cannot load');
    const chip = card.querySelector('toast__thumb-ext');
    assert.equal(chip.textContent, 'PDF');
    assert.equal(chip.getAttribute('aria-hidden'), 'true');
    assert.equal(card.querySelector('toast__thumb').dataset.noPreview, '1');
});

test('every member of a coalesced group is drawn, not just the newest', () => {
    const s = makeSandbox();
    const card = new El('div');
    s.AttachmentToast.renderThumbs(card, [
        { attachment_name: 'a.png', thumb_url: 'data:,1' },
        { attachment_name: 'b.pdf', thumb_url: null, thumb_label: 'PDF' },
        { attachment_name: 'c.png', thumb_url: 'data:,2' },
    ]);
    assert.equal(card.querySelectorAll('toast__thumb-row').length, 3);
    assert.equal(card.querySelectorAll('toast__thumb-img').length, 2);
    assert.equal(card.querySelectorAll('toast__thumb-ext').length, 1);
});

test('re-rendering rebuilds the strip instead of appending a second one', () => {
    const s = makeSandbox();
    const card = new El('div');
    const group = [{ attachment_name: 'a.png', thumb_url: 'data:,1' }];
    s.AttachmentToast.renderThumbs(card, group);
    s.AttachmentToast.renderThumbs(card, group);
    s.AttachmentToast.renderThumbs(card, group);
    assert.equal(card.querySelectorAll('toast__thumbs').length, 1,
        'an append-only strip would grow a duplicate row per render');
    assert.equal(card.querySelectorAll('toast__thumb-row').length, 1);
});


function stagedManager(sessionId, opts = {}) {
    const s = makeSandbox(opts);
    const mgr = s.ToastManager;
    mgr._render = () => {};
    mgr._cardFor = () => null;
    s.AttachmentToast.show(termFor(sessionId), {
        blob: { type: 'application/pdf' },
        filename: opts.filename || 'spec.pdf',
    });
    return { s, mgr };
}

test('the receipt is raised as an Attachment toast on the shared manager', () => {
    const { s, mgr } = stagedManager('ses_a');
    const held = [...mgr._byId.values()];
    assert.equal(held.length, 1);
    assert.equal(held[0].kind, 'Attachment');
    assert.equal(held[0].kind, mgr.ATTACHMENT_KIND,
        'the kind must be read off the manager, never re-spelled');
    assert.equal(held[0].title, 'attached');
    assert.equal(held[0].attachment_name, 'spec.pdf');
    assert.equal(held[0].thumb_label, 'PDF');
    assert.equal(held[0].local, true);
    assert.ok(s.container, 'the card goes in the shared toast container');
});

test('typing does NOT clear the receipt', () => {
    const { mgr } = stagedManager('ses_a');
    mgr.dismissForSessionActivity('ses_a');
    assert.equal(mgr._byId.size, 1,
        'clearing on the first keystroke would make it flash and vanish');
});

test('a notification beside it IS cleared by typing', () => {
    const { mgr } = stagedManager('ses_a');
    mgr.add({ id: 'srv1', session_id: 'ses_a', kind: 'Notification', title: 'hi' });
    assert.equal(mgr._byId.size, 2);
    mgr.dismissForSessionActivity('ses_a');
    const left = [...mgr._byId.values()];
    assert.equal(left.length, 1);
    assert.equal(left[0].kind, 'Attachment');
});

test('sending the prompt clears the receipt', () => {
    const { s, mgr } = stagedManager('ses_a');
    const cleared = s.AttachmentToast.noteUserInput('ses_a', '\r');
    assert.equal(cleared, 1);
    assert.equal(mgr._byId.size, 0);
});

test('a newline does not clear it and a submit afterwards does', () => {
    const { s, mgr } = stagedManager('ses_a');
    assert.equal(s.AttachmentToast.noteUserInput('ses_a', '\n'), 0);
    assert.equal(s.AttachmentToast.noteUserInput('ses_a', '\x1b\r'), 0);
    assert.equal(mgr._byId.size, 1, 'composing a multi-line prompt keeps it');
    assert.equal(s.AttachmentToast.noteUserInput('ses_a', '\r'), 1);
    assert.equal(mgr._byId.size, 0);
});

test('sending in one session does not clear another session receipt', () => {
    const { s, mgr } = stagedManager('ses_a');
    s.AttachmentToast.show(termFor('ses_b'), {
        blob: { type: 'application/pdf' }, filename: 'other.pdf',
    });
    assert.equal(mgr._byId.size, 2);
    s.AttachmentToast.noteUserInput('ses_b', '\r');
    const left = [...mgr._byId.values()];
    assert.equal(left.length, 1);
    assert.equal(left[0].session_id, 'ses_a');
});

test('one call with the sent bytes clears a notification and a receipt', () => {
    const { mgr } = stagedManager('ses_a');
    mgr.add({ id: 'srv1', session_id: 'ses_a', kind: 'Notification', title: 'hi' });
    mgr.dismissForSessionActivity('ses_a', '\r');
    assert.equal(mgr._byId.size, 0);
});

test('the same call with a keystroke clears only the notification', () => {
    const { mgr } = stagedManager('ses_a');
    mgr.add({ id: 'srv1', session_id: 'ses_a', kind: 'Notification', title: 'hi' });
    mgr.dismissForSessionActivity('ses_a', 'x');
    const left = [...mgr._byId.values()];
    assert.equal(left.length, 1);
    assert.equal(left[0].kind, 'Attachment');
});

test('a call with no bytes at all leaves the receipt standing', () => {
    const { mgr } = stagedManager('ses_a');
    mgr.dismissForSessionActivity('ses_a');
    assert.equal(mgr._byId.size, 1);
});

test('dismissing a local receipt never POSTs an ack', () => {
    const { s, mgr } = stagedManager('ses_a');
    s.AttachmentToast.noteUserInput('ses_a', '\r');
    assert.deepEqual(s.acked, []);
    mgr.add({ id: 'srv1', session_id: 'ses_a', kind: 'Notification', title: 'hi' });
    mgr.dismiss('srv1');
    assert.deepEqual(s.acked, [['srv1', 'ses_a']]);
});

test('a poll reconcile does not sweep the receipt; sending the prompt still does', () => {
    const { s, mgr } = stagedManager('ses_a');
    const removed = mgr.reconcileOpen([], { since: Date.now() + 5000 });
    assert.equal(removed, 0,
        'the receipt must survive a poll tick, even one whose snapshot '
        + 'instant is later than the card - the exact shape of the bug '
        + 'that swept it within seconds of being staged');
    assert.equal(mgr._byId.size, 1);
    const cleared = s.AttachmentToast.noteUserInput('ses_a', '\r');
    assert.equal(cleared, 1);
    assert.equal(mgr._byId.size, 0);
});

test('two attachments in one session coalesce onto one card', () => {
    const { s, mgr } = stagedManager('ses_a');
    s.AttachmentToast.show(termFor('ses_a'), {
        blob: { type: 'application/pdf' }, filename: 'second.pdf',
    });
    const groups = mgr._groups ? mgr._groups() : null;
    const held = [...mgr._byId.values()];
    assert.equal(held.length, 2, 'both files are still recorded');
    const keys = new Set(held.map((t) => `${t.session_id}|${t.kind}`));
    assert.equal(keys.size, 1, 'they must share one coalesce key, so one card');
    if (groups) {
        const attach = groups.filter((g) => g.toasts[0].kind === 'Attachment');
        assert.equal(attach.length, 1, 'a second attachment must not build a pile');
    }
});

test('the receipt keeps its OWN card beside the session status card', () => {
    const { mgr } = stagedManager('ses_a');
    mgr.add({ id: 'srv1', session_id: 'ses_a', kind: 'Notification',
              title: 'wants your attention', body: 'look' });
    mgr.add({ id: 'srv2', session_id: 'ses_a', kind: 'Stop',
              title: 'Your turn', body: 'done' });
    const groups = mgr._groups();
    assert.equal(groups.length, 2,
        'one status card plus one receipt, never three and never one');
    const kinds = groups.map((g) => g.winner.kind).sort().join(',');
    assert.equal(kinds, 'Attachment,Notification',
        'the two server events share a card; the receipt keeps its own');
});

test('the card is stamped with the session the header is showing', () => {
    const { mgr } = stagedManager('ses_a', { headerLabel: 'cloudecode' });
    assert.equal([...mgr._byId.values()][0].session_label, 'cloudecode');
});

test('with no header the label is null rather than invented', () => {
    const { mgr } = stagedManager('ses_a');
    assert.equal([...mgr._byId.values()][0].session_label, null);
});

test('an updateLocal after the prompt was sent does not resurrect the card', () => {
    const { mgr } = stagedManager('ses_a');
    const id = [...mgr._byId.keys()][0];
    mgr.dismissKindForSession('Attachment', 'ses_a');
    assert.equal(mgr._byId.size, 0);
    assert.equal(mgr.updateLocal(id, { thumb_url: 'data:,late' }), false);
    assert.equal(mgr._byId.size, 0);
});

test('updateLocal refuses a server toast', () => {
    const { mgr } = stagedManager('ses_a');
    mgr.add({ id: 'srv1', session_id: 'ses_a', kind: 'Notification', title: 'hi' });
    assert.equal(mgr.updateLocal('srv1', { body: 'injected' }), false);
    assert.equal(mgr._byId.get('srv1').body, undefined);
});


test('index.html actually loads the module', () => {
    const html = read('client', 'index.html');
    assert.ok(html.includes('/static/js/attachment-toast.js'),
        'the module must be loaded, or none of the above ever runs');
});

test('clipboard.js raises the toast instead of the overlay', () => {
    const src = read('client', 'js', 'clipboard.js');
    assert.ok(src.includes('window.AttachmentToast.show('));
    const i = src.indexOf('AttachmentToast.show(');
    const j = src.indexOf("report(term, globalThis.CloudeTr('terminal.upload.attached'");
    assert.ok(i > 0 && j > i, 'the text overlay must be the else branch');
});

test('terminal.js hands the sent bytes down to the dismissal seam', () => {
    const src = read('client', 'js', 'terminal.js');
    assert.ok(src.includes('dismissForSessionActivity(sessionId, data)'),
        'the bytes must reach the manager, or a submit is indistinguishable'
        + ' from a keystroke and the receipt never clears');
    assert.ok(src.includes('this._noteUserInputToSession(data)'));
    assert.ok(src.includes('this._noteUserInputToSession(keyData)'));
    assert.ok(/this\._sendUserBytes\(bytes\)\)\s*this\._noteUserInputToSession\(\);/.test(src),
        'shift+enter must pass no bytes to the dismissal seam, and must '
        + 'only reach it when the bytes were really delivered');
});

test('toast-lifecycle.js dispatches the receipt clear and keeps the submit test out', () => {
    const src = read('client', 'js', 'toast-lifecycle.js');
    assert.ok(src.includes('AttachmentToast.noteUserInput(sessionId, data)'));
    assert.ok(!src.includes("'\\x1b\\r'"),
        'the submit vocabulary must live in attachment-toast.js alone');
    assert.ok(!toastSrc.includes("'\\x1b\\r'"),
        'the submit vocabulary must live in attachment-toast.js alone');
});

test('nothing in the module dismisses on a timer', () => {
    assert.ok(!/setTimeout|setInterval/.test(attachSrc),
        'the receipt is retired by the prompt being sent, never by a clock');
});

test('the strip has real styles and every colour is a token', () => {
    const css = read('client', 'css', 'toast.css');
    for (const cls of ['.toast__thumbs', '.toast__thumb-row', '.toast__thumb',
        '.toast__thumb-img', '.toast__thumb-ext', '.toast__thumb-name']) {
        assert.ok(css.includes(cls + ' {') || css.includes(cls + ',')
            || css.includes(cls + '\n'), `${cls} must be styled`);
    }
    const block = css.slice(css.indexOf('.toast__thumbs'));
    const declared = block.match(/(?:^|[^-\w])(?:color|background)\s*:\s*([^;]+);/g) || [];
    for (const d of declared) {
        assert.ok(d.includes('var(--'), `hardcoded colour in the strip: ${d.trim()}`);
    }
    assert.ok(/min-height:\s*44px/.test(block), 'rows need a real touch target');
    assert.ok(/max-height:/.test(block) && /overflow-y:\s*auto/.test(block));
});

await runQueue();
console.log(`${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
