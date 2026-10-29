
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

import { glyphSvg } from '../../client/js/icons/glyphs.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, '..', '..');
const BUNDLE = path.join(ROOT, 'client', 'dist', 'app.js');

let cached = null;
function bundleSource() {
    if (cached === null) cached = fs.readFileSync(BUNDLE, 'utf8');
    return cached;
}

export function unrefTimer(start) {
    return (...args) => {
        const handle = start(...args);
        if (handle && typeof handle.unref === 'function') handle.unref();
        return handle;
    };
}

export function completeHostGlobals(context) {
    if (!context.window) context.window = context;
    const win = context.window;
    if (!win.console) win.console = context.console || console;
    for (const level of ['log', 'warn', 'error', 'info', 'debug']) {
        if (typeof win.console[level] !== 'function') win.console[level] = () => {};
    }
    for (const [name, impl] of [
        ['queueMicrotask', queueMicrotask],
        ['setTimeout', unrefTimer(setTimeout)],
        ['clearTimeout', clearTimeout],
        ['setInterval', unrefTimer(setInterval)],
        ['clearInterval', clearInterval],
    ]) {
        if (typeof context[name] !== 'function') context[name] = impl;
        if (win !== context && typeof win[name] !== 'function') win[name] = impl;
    }
    if (typeof context.requestAnimationFrame !== 'function') {
        context.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
    }
    for (const name of ['URL', 'URLSearchParams', 'WebSocket', 'AbortController', 'Event', 'CustomEvent',
        'TextEncoder', 'TextDecoder', 'Headers']) {
        const impl = globalThis[name];
        if (typeof context[name] !== 'function' && typeof impl === 'function') context[name] = impl;
        if (win !== context && typeof win[name] !== 'function' && typeof impl === 'function') win[name] = impl;
    }
    if (context.performance === undefined) context.performance = globalThis.performance;
    if (win !== context && win.performance === undefined) win.performance = globalThis.performance;
    if (!context.navigator) context.navigator = { languages: ['en'], language: 'en' };
    if (typeof context.navigator.userAgent !== 'string') context.navigator.userAgent = 'Node.js';
    if (win !== context && !win.navigator) win.navigator = context.navigator;
    if (!context.localStorage) {
        context.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
    }
    if (win !== context && !win.localStorage) win.localStorage = context.localStorage;
    if (!context.location) context.location = new URL('http://localhost/');
    if (win !== context && !win.location) win.location = context.location;
    if (!context.document) {
        context.document = { getElementById: () => null, body: null };
        if (win !== context && !win.document) win.document = context.document;
    }
    const doc = context.document;
    if (doc && typeof doc === 'object') {
        for (const name of ['addEventListener', 'removeEventListener']) {
            if (typeof doc[name] !== 'function') doc[name] = () => {};
        }
        if (typeof doc.dispatchEvent !== 'function') doc.dispatchEvent = () => true;
        if (doc.body && typeof doc.body === 'object' && !doc.body.dataset) doc.body.dataset = {};
        if (!doc.documentElement) {
            doc.documentElement = { hasAttribute: () => false, getAttribute: () => null };
        }
        if (typeof doc.hasFocus !== 'function') doc.hasFocus = () => false;
    }
    if (!context.CloudeGlyphs) context.CloudeGlyphs = { glyphSvg };
    if (win !== context && !win.CloudeGlyphs) win.CloudeGlyphs = context.CloudeGlyphs;
    if (typeof win.addEventListener !== 'function') {
        const listeners = new Map();
        win.addEventListener = (type, fn) => {
            if (!listeners.has(type)) listeners.set(type, new Set());
            listeners.get(type).add(fn);
        };
        win.removeEventListener = (type, fn) => {
            listeners.get(type)?.delete(fn);
        };
        win.dispatchEvent = (event) => {
            for (const fn of listeners.get(event?.type) ?? []) fn(event);
            return true;
        };
    }
    if (typeof win.dispatchEvent !== 'function') win.dispatchEvent = () => true;
    for (const name of ['Element', 'HTMLElement']) {
        if (typeof context[name] !== 'function') context[name] = class {};
        if (win !== context && typeof win[name] !== 'function') win[name] = context[name];
    }
    return win;
}

export function installCloudeWeb(context) {
    const win = completeHostGlobals(context);
    if (win.CloudeWeb) return win.CloudeWeb;
    vm.runInContext(bundleSource(), context);
    return win.CloudeWeb;
}

export function resetSessionStore(cloudeWeb) {
    if (cloudeWeb && cloudeWeb.launchpad && cloudeWeb.launchpad.sessions) {
        cloudeWeb.launchpad.sessions.reset();
    }
}

export function stubPanelMounts(cloudeWeb) {
    const counts = { recent: 0, attribution: 0, projectTree: 0 };
    if (!cloudeWeb || !cloudeWeb.launchpad) return counts;
    cloudeWeb.launchpad.mountRecentSessions = () => { counts.recent++; };
    cloudeWeb.launchpad.mountAttributionPrompt = () => { counts.attribution++; };
    cloudeWeb.launchpad.mountProjectTree = () => { counts.projectTree++; };
    return counts;
}
