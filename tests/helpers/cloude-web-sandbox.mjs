// and the three

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

import { glyphSvg } from '../../client/js/icons/glyphs.js';
import { createI18n } from '../../client/js/i18n/runtime.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, '..', '..');
const DIST_DIR = path.join(ROOT, 'client', 'dist');
const BUNDLE = path.join(DIST_DIR, 'app.js');

const sourceCache = new Map();
function readDistFile(filePath) {
    let src = sourceCache.get(filePath);
    if (src === undefined) {
        src = fs.readFileSync(filePath, 'utf8');
        sourceCache.set(filePath, src);
    }
    return src;
}

function compileChunkToClassic(src, loadRel) {
    let body = src;
    body = body.replace(
        /(?<=^|[;\n/])\s*import\s*\{([^}]*)\}\s*from\s*["'](\.[^"']+)["'];?/g,
        (_m, names, spec) => {
            const bindings = names
                .split(',')
                .map((s) => s.trim())
                .filter(Boolean)
                .map((s) => {
                    const parts = s.split(/\s+as\s+/);
                    return parts.length === 2 ? `${parts[0].trim()}:${parts[1].trim()}` : s;
                })
                .join(',');
            return `var {${bindings}}=${loadRel}(${JSON.stringify(spec)});`;
        },
    );
    body = body.replace(
        /(?<=^|[;\n/])\s*import\s*\*\s*as\s+(\w+)\s*from\s*["'](\.[^"']+)["'];?/g,
        (_m, alias, spec) => `var ${alias}=${loadRel}(${JSON.stringify(spec)});`,
    );
    body = body.replace(
        /(?<=^|[;\n/])\s*import\s+(\w+)\s*from\s*["'](\.[^"']+)["'];?/g,
        (_m, alias, spec) => `var ${alias}=${loadRel}(${JSON.stringify(spec)}).default;`,
    );
    body = body.replace(
        /(?<=^|[;\n/])\s*import\s*["'](\.[^"']+)["'];?/g,
        (_m, spec) => `${loadRel}(${JSON.stringify(spec)});`,
    );

    let exportReturn = 'return {};';
    const exportRe = /export\s*\{([^}]*)\}\s*;?\s*$/;
    const em = exportRe.exec(body);
    if (em) {
        body = body.slice(0, em.index);
        const props = em[1]
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)
            .map((s) => {
                const parts = s.split(/\s+as\s+/);
                if (parts.length === 2) {
                    const local = parts[0].trim();
                    const exported = parts[1].trim();
                    return `get ${exported}(){return ${local};}`;
                }
                return `get ${s}(){return ${s};}`;
            })
            .join(',');
        exportReturn = `return {${props}};`;
    }

    body = body.replace(
        /typeof document<[`"']u[`"']&&document\.createElement\([`"']link[`"']\)\.relList/g,
        'typeof document<"u"&&typeof document.createElement==="function"&&document.createElement("link").relList',
    );
    body = body.replace(/\bimport\.meta\b/g, '({url:"http://localhost/static/dist/app.js"})');
    body = body.replace(/\bimport\s*\(([^)]+)\)/g, 'Promise.resolve().then(()=>__cloudeEsmLoad($1))');

    return `(function(){\n${body}\n${exportReturn}})()`;
}

function runCodeSplitBundle(context) {
    const modules = Object.create(null);
    const loadModule = (spec) => {
        const rel = spec.replace(/^\.\//, '');
        if (modules[rel]) return modules[rel];
        const filePath = path.join(DIST_DIR, rel);
        const raw = readDistFile(filePath);
        const box = {};
        modules[rel] = box;
        const wrapped = compileChunkToClassic(raw, '__cloudeEsmLoad');
        const exportsObj = vm.runInContext(wrapped, context, { filename: rel });
        if (exportsObj && typeof exportsObj === 'object') {
            Object.defineProperties(box, Object.getOwnPropertyDescriptors(exportsObj));
        }
        return box;
    };
    context.__cloudeEsmLoad = loadModule;
    loadModule('./app.js');
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
    if (!context.CloudeI18n) context.CloudeI18n = createI18n();
    if (win !== context && !win.CloudeI18n) win.CloudeI18n = context.CloudeI18n;
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
    runCodeSplitBundle(context);
    return win.CloudeWeb;
}

export function resetSessionStore(cloudeWeb) {
    if (cloudeWeb && cloudeWeb.launchpad && cloudeWeb.launchpad.sessions) {
        cloudeWeb.launchpad.sessions.reset();
    }
}
