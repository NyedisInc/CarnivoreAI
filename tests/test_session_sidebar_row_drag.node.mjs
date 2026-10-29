
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function readClientJs(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'js', name), 'utf8');
}

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


function el(tag, attrs, parent) {
    const node = {
        tagName: tag.toUpperCase(),
        attrs: attrs || {},
        parent: parent || null,
        dataset: {},
        classList: { add() {}, remove() {}, contains() { return false; } },
        children: [],
        listeners: {},
        hasAttribute(name) { return name in this.attrs; },
        getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; },
        setAttribute(name, value) { this.attrs[name] = String(value); },
        addEventListener(type, fn) { this.listeners[type] = fn; },
        getBoundingClientRect() { return { top: 0, height: 20, bottom: 20 }; },
        querySelectorAll() { return []; },
        focus() {},
        setPointerCapture() {},
        matchesOne(sel) {
            const trimmed = sel.trim();
            if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
                return trimmed.slice(1, -1) in this.attrs;
            }
            if (trimmed.startsWith('.')) {
                return (this.attrs.class || '').split(/\s+/).includes(trimmed.slice(1));
            }
            return this.tagName === trimmed.toUpperCase();
        },
        closest(selector) {
            const parts = selector.split(',');
            let node2 = this;
            while (node2) {
                for (const part of parts) {
                    if (node2.matchesOne(part)) return node2;
                }
                node2 = node2.parent;
            }
            return null;
        },
    };
    if (parent) parent.children.push(node);
    return node;
}

function sandbox() {
    const list = el('div', { class: 'session-sidebar-list' }, null);
    const row = el('div', { class: 'session-sidebar-row' }, list);
    row.dataset.name = 'cloude_alpha';
    const main = el('div', { class: 'session-sidebar-row-main' }, row);
    const provider = el('span', { 'data-grip-session': 'cloude_alpha' }, main);
    const name = el('span', { class: 'session-sidebar-row-name' }, main);
    const pin = el('button', { 'data-pin-session': 'cloude_alpha' }, main);
    const kebab = el('button', { class: 'session-row-menu-trigger' }, main);

    list.querySelectorAll = () => [row];

    const win = {
        SessionSidebar: {
            listEl: list,
            setDragging() {},
            repaint() {},
        },
        getSelection() { return { removeAllRanges() {} }; },
    };
    win.window = win;
    const docHandlers = {};
    const doc = {
        addEventListener(type, fn) { docHandlers[type] = fn; },
        getElementById() { return null; },
    };
    const ctx = { window: win, document: doc, console };
    vm.createContext(ctx);
    vm.runInContext(readClientJs('session-sidebar-reorder.js'), ctx);
    vm.runInContext(readClientJs('session-sidebar-row-drag.js'), ctx);
    ctx.window.SessionSidebarRowDrag.init();
    assert.equal(typeof docHandlers.pointermove, 'function',
        'the module must have bound pointermove to the document');
    assert.equal(typeof docHandlers.pointerup, 'function',
        'the module must have bound pointerup to the document');
    return { ctx, row, pin, kebab, provider, name, list, docHandlers };
}

function pointer(target, y, opts) {
    const o = opts || {};
    return {
        target,
        clientX: o.x === undefined ? 100 : o.x,
        clientY: y,
        button: o.button === undefined ? 0 : o.button,
        pointerType: o.pointerType || 'mouse',
        pointerId: o.pointerId === undefined ? 1 : o.pointerId,
        cancelable: true,
        preventDefault() { this.defaultPrevented = true; },
        stopPropagation() { this.propagationStopped = true; },
        defaultPrevented: false,
        propagationStopped: false,
    };
}

function document_move(s, y) {
    s.docHandlers.pointermove(pointer(s.name, y));
}

function document_up(s, y) {
    s.docHandlers.pointerup(pointer(s.name, y));
}


test('a mouse press anywhere on the row arms a drag', () => {
    const s = sandbox();
    s.list.listeners.pointerdown(pointer(s.name, 100));
    assert.equal(s.ctx.window.SessionSidebarRowDrag.isDragging(), false,
        'a press alone must not be a drag - the slop has not been travelled');
    assert.equal(s.ctx.window.SessionSidebarReorder.tookClick(), false,
        'and it must not have claimed the click that a plain click would send');
});

test('a mouse press on the PIN arms nothing', () => {
    const s = sandbox();
    const ev = pointer(s.pin, 100);
    s.list.listeners.pointerdown(ev);
    assert.equal(ev.defaultPrevented, false,
        'the pin owns its own pointer - the drag must not touch its event');
    document_move(s, 200);
    assert.equal(s.ctx.window.SessionSidebarRowDrag.isDragging(), false);
});

test('a mouse press on the KEBAB arms nothing', () => {
    const s = sandbox();
    s.list.listeners.pointerdown(pointer(s.kebab, 100));
    document_move(s, 200);
    assert.equal(s.ctx.window.SessionSidebarRowDrag.isDragging(), false);
});

test('a RIGHT click arms nothing - that gesture opens the row menu', () => {
    const s = sandbox();
    s.list.listeners.pointerdown(pointer(s.name, 100, { button: 2 }));
    document_move(s, 200);
    assert.equal(s.ctx.window.SessionSidebarRowDrag.isDragging(), false);
});

test('a TOUCH away from the provider mark arms nothing, so the list scrolls', () => {
    const s = sandbox();
    s.list.listeners.pointerdown(pointer(s.name, 100, { pointerType: 'touch' }));
    document_move(s, 200);
    assert.equal(s.ctx.window.SessionSidebarRowDrag.isDragging(), false,
        'a finger on the row body must pan the list, never reorder it');
});

test('a TOUCH on the provider mark DOES arm a drag - it is the handle', () => {
    const s = sandbox();
    const ev = pointer(s.provider, 100, { pointerType: 'touch' });
    s.list.listeners.pointerdown(ev);
    assert.equal(ev.defaultPrevented, true,
        'the handle suppresses the browser default so the pan does not win');
    document_move(s, 200);
    assert.equal(s.ctx.window.SessionSidebarRowDrag.isDragging(), true);
});


test('a touch threshold is larger than a mouse one, and both are reachable', () => {
    const s = sandbox();
    const d = s.ctx.window.SessionSidebarRowDrag;
    assert.ok(d.slop('touch') > d.slop('mouse'),
        'a finger jitters further than a mouse and must not trip the same wire');
    assert.ok(d.slop('touch') > 10,
        'it must clear the 10px the long-press gesture treats as a scroll, or a'
        + ' movement that cancels the menu would start a drag in the same breath');
    assert.ok(d.slop('touch') < 40,
        'and it must stay small enough that a deliberate reorder is still reachable');
});

test('a TAP on the provider mark with finger jitter still reaches the click', () => {
    const s = sandbox();
    const d = s.ctx.window.SessionSidebarRowDrag;
    s.list.listeners.pointerdown(pointer(s.provider, 100, { pointerType: 'touch' }));
    document_move(s, 106);
    document_up(s, 106);
    assert.equal(d.isDragging(), false, 'six pixels of jitter is a tap, not a drag');
    assert.equal(s.ctx.window.SessionSidebarReorder.tookClick(), false,
        'and the click must reach the switch handler, or nothing happens when you tap');
});

test('a real touch DRAG on the provider mark still works', () => {
    const s = sandbox();
    s.list.listeners.pointerdown(pointer(s.provider, 100, { pointerType: 'touch' }));
    document_move(s, 140);
    assert.equal(s.ctx.window.SessionSidebarRowDrag.isDragging(), true);
    document_up(s, 140);
    assert.equal(s.ctx.window.SessionSidebarReorder.tookClick(), true,
        'a drag that moved must still claim its click');
});

test('the gesture keeps the threshold it started with', () => {
    const s = sandbox();
    s.list.listeners.pointerdown(pointer(s.provider, 100, { pointerType: 'touch' }));
    s.docHandlers.pointermove(pointer(s.name, 106, { pointerType: 'mouse' }));
    assert.equal(s.ctx.window.SessionSidebarRowDrag.isDragging(), false,
        'the touch threshold recorded at pointerdown is the one that applies');
});


test('a drag released over a PIN neither toggles it nor poisons the next click', () => {
    const s = sandbox();
    const clicks = readClientJs('session-sidebar-clicks.js');
    const claim = clicks.indexOf('SessionSidebarReorder.tookClick()');
    const pin = clicks.indexOf('SessionSidebarReorder.onPinClick(e)');
    const rename = clicks.indexOf('SessionSidebarRename.onListClick(e)');
    const action = clicks.indexOf('ATTR_ACTION');
    assert.ok(claim > 0, 'the router must consult the drag claim at all');
    assert.ok(claim < pin,
        'the claim must be tested before the pin, or a drag released over a pin fires it');
    assert.ok(claim < rename,
        'and before the rename editor, for the same reason');
    assert.ok(claim < action,
        'and before the row actions, which also return early and would strand the claim');
    assert.equal(clicks.split('SessionSidebarReorder.tookClick()').length - 1, 1,
        'the claim is consumed by reading it, so it must be read exactly once');
    assert.equal(typeof s.ctx.window.SessionSidebarReorder.tookClick, 'function');
});


test('a press that never travels does NOT claim the click', () => {
    const s = sandbox();
    s.list.listeners.pointerdown(pointer(s.name, 100));
    document_move(s, 102);
    document_up(s, 102);
    assert.equal(s.ctx.window.SessionSidebarReorder.tookClick(), false,
        'under the slop the row was clicked, not dragged - the switch must happen');
});

test('a press that travels DOES claim the click, exactly once', () => {
    const s = sandbox();
    s.list.listeners.pointerdown(pointer(s.name, 100));
    document_move(s, 140);
    document_up(s, 140);
    assert.equal(s.ctx.window.SessionSidebarReorder.tookClick(), true,
        'the click that ends a drag must not also switch conversations');
    assert.equal(s.ctx.window.SessionSidebarReorder.tookClick(), false,
        'and the claim must be CONSUMED - the next click is a real click');
});

test('a new press clears a claim nothing consumed', () => {
    const s = sandbox();
    s.list.listeners.pointerdown(pointer(s.name, 100));
    document_move(s, 140);
    document_up(s, 140);
    s.list.listeners.pointerdown(pointer(s.name, 100));
    document_up(s, 100);
    assert.equal(s.ctx.window.SessionSidebarReorder.tookClick(), false,
        'a drag that ended without a click must not poison the gesture after it');
});

test('the reorder module still answers for both, so callers keep one address', () => {
    const s = sandbox();
    const r = s.ctx.window.SessionSidebarReorder;
    assert.equal(typeof r.isDragging, 'function');
    assert.equal(typeof r.tookClick, 'function');
    s.list.listeners.pointerdown(pointer(s.name, 100));
    document_move(s, 140);
    assert.equal(r.isDragging(), true,
        'session-sidebar.js polls this one to hold off repainting mid-drag');
});


function handoffSandbox(taken) {
    const s = sandbox();
    s.list.getBoundingClientRect = () => ({ left: 0, right: 300, top: 0, bottom: 400 });
    const calls = [];
    s.ctx.window.CloudeWeb = { tabDrag: { begin(start) { calls.push(start); return taken; } } };
    return Object.assign(s, { calls });
}

test('a drag that leaves the list sideways is handed to the tab strips, and claims the click', () => {
    const s = handoffSandbox(true);
    s.list.listeners.pointerdown(pointer(s.name, 100, { x: 100 }));
    s.docHandlers.pointermove(pointer(s.name, 100, { x: 140 }));
    assert.equal(s.calls.length, 1, 'sideways travel past the slop offers the drag');
    assert.equal(s.calls[0].name, 'cloude_alpha');
    assert.equal(s.ctx.window.SessionSidebarRowDrag.isDragging(), false, 'the drawer let go');
    s.docHandlers.pointermove(pointer(s.name, 300, { x: 600 }));
    assert.equal(s.calls.length, 1, 'once handed off, the drawer sees no more of it');
    assert.equal(s.ctx.window.SessionSidebarReorder.tookClick(), true,
        'the click that ends a handed off drag must not also switch conversations');
});

test('a vertical drag stays the drawer\'s own reorder', () => {
    const s = handoffSandbox(true);
    s.list.listeners.pointerdown(pointer(s.name, 100, { x: 100 }));
    s.docHandlers.pointermove(pointer(s.name, 140, { x: 110 }));
    assert.equal(s.calls.length, 0);
    assert.equal(s.ctx.window.SessionSidebarRowDrag.isDragging(), true);
});

test('a refused handoff (not the terminal page) leaves the drawer drag alone', () => {
    const s = handoffSandbox(false);
    s.list.listeners.pointerdown(pointer(s.name, 100, { x: 100 }));
    s.docHandlers.pointermove(pointer(s.name, 100, { x: 400 }));
    assert.equal(s.calls.length, 1);
    s.docHandlers.pointermove(pointer(s.name, 140, { x: 400 }));
    assert.equal(s.ctx.window.SessionSidebarRowDrag.isDragging(), true, 'still the drawer\'s drag');
});

test('a plain click never offers anything', () => {
    const s = handoffSandbox(true);
    s.list.listeners.pointerdown(pointer(s.name, 100, { x: 100 }));
    s.docHandlers.pointermove(pointer(s.name, 101, { x: 101 }));
    document_up(s, 101);
    assert.equal(s.calls.length, 0);
    assert.equal(s.ctx.window.SessionSidebarReorder.tookClick(), false);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures === 0) console.log('ALL PASS');
process.exit(failures === 0 ? 0 : 1);
