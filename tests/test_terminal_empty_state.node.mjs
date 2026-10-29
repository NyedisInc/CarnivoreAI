// the empty page

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

import { installCloudeWeb } from './helpers/cloude-web-sandbox.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const EMPTY = 'terminal-screen--empty';

function js(relative) {
    return fs.readFileSync(path.join(ROOT, 'client', 'js', relative), 'utf8');
}

function makeEl() {
    const classes = new Set();
    return {
        classes,
        hidden: false,
        textContent: '',
        dataset: {},
        style: { setProperty() {}, removeProperty() {} },
        classList: {
            add(c) { classes.add(c); },
            remove(c) { classes.delete(c); },
            contains(c) { return classes.has(c); },
            toggle(c, on) { if (on) classes.add(c); else classes.delete(c); },
        },
        setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
        appendChild() {}, removeChild() {}, addEventListener() {}, removeEventListener() {},
        querySelector() { return null; }, querySelectorAll() { return []; },
    };
}

function load(opts = {}) {
    const calls = {
        connect: 0, reconnect: 0, pause: 0, sockets: 0, pushed: [], replaced: [],
        active: [], sidebarShow: 0, applied: [], scopes: [], clearSession: 0,
        opened: 0, closed: 0, begin: [], header: [], sidebarOpen: [],
    };
    const els = {};
    const el = (id) => (els[id] ||= makeEl());
    const screen = el('terminal-screen');
    screen.classes.add('screen');
    const doc = {
        title: '', body: makeEl(), documentElement: makeEl(), readyState: 'complete',
        getElementById: el,
        querySelector: (s) => el('sel:' + s),
        querySelectorAll: (s) => (s === '.screen' ? [screen, el('launchpad-screen')] : []),
        createElement: makeEl,
        addEventListener() {},
    };
    el('launchpad-screen').classes.add('screen');
    const listeners = new Map();
    const timers = opts.timers || [];
    const location = { pathname: opts.pathname || '/', search: '', hash: '' };
    const sandbox = {
        console: { log() {}, warn() {}, error() {} },
        document: doc,
        localStorage: { getItem: () => 'claude', setItem() {}, removeItem() {} },
        setTimeout: (fn) => { timers.push(fn); return timers.length; },
        clearTimeout() {}, setInterval: () => 0, clearInterval() {},
        addEventListener(type, fn) {
            if (!listeners.has(type)) listeners.set(type, []);
            listeners.get(type).push(fn);
        },
        removeEventListener() {},
        dispatchEvent(ev) { for (const fn of listeners.get(ev.type) || []) fn(ev); return true; },
        CustomEvent: class { constructor(type) { this.type = type; } },
        location,
        history: {
            pushState(_s, _t, p) { calls.pushed.push(p); location.pathname = p; },
            replaceState(_s, _t, p) { calls.replaced.push(p); location.pathname = p; },
        },
        fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
        // the empty page
        WebSocket: class { constructor() { calls.sockets += 1; } },
        matchMedia: () => ({ matches: true, addEventListener() {} }),
        MutationObserver: undefined,
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    sandbox.Themes = {
        getStoredThemeId: () => 'claude',
        clearSession() { calls.clearSession += 1; },
        setActiveSession(n) { calls.scopes.push(n); },
        applyTheme(id) { calls.applied.push(id); return true; },
        applySessionScope() {},
    };
    sandbox.Auth = { isAuthenticated: () => true };
    vm.runInContext(js('navigation-generation.js'), sandbox);
    const realBegin = sandbox.NavigationGeneration.begin;
    sandbox.NavigationGeneration.begin = (why) => { calls.begin.push(why); return realBegin(why); };
    vm.runInContext(js('theme-navigation.js'), sandbox);
    vm.runInContext(js('router.js'), sandbox);
    vm.runInContext(js('i18n/tr.js'), sandbox);
    vm.runInContext(js('terminal-empty-entry.js'), sandbox);
    vm.runInContext(js('app-boot-complete.js'), sandbox);
    vm.runInContext(js('terminal-grid-host.js'), sandbox);
    sandbox.Router.init = () => {};
    vm.runInContext(js('app-screen-entry.js'), sandbox);
    vm.runInContext(js('app.js'), sandbox);
    const app = sandbox.App;
    sandbox.ScreenChrome = { apply() {} };
    sandbox.TerminalController = {
        term: {},
        pauseForHome() { calls.pause += 1; },
        connectToSession() { calls.connect += 1; return Promise.resolve(); },
        reconnectToExistingSession() { calls.reconnect += 1; return Promise.resolve(); },
    };
    sandbox.SessionSidebar = {
        isOpen: !!opts.sidebarOpen,
        show() { calls.sidebarShow += 1; },
        open(o) { this.isOpen = true; calls.sidebarOpen.push(o ? o.persist : undefined); },
        setActiveSession(id, name) { calls.active.push([id, name]); },
    };
    sandbox.CloudeWeb = {
        openTerminalEmpty() { calls.opened += 1; screen.classList.add(EMPTY); return true; },
        closeTerminalEmpty() { calls.closed += 1; screen.classList.remove(EMPTY); return true; },
    };
    sandbox.setHeaderIdentity = (o) => calls.header.push(o.title);
    app.logoutBtn = makeEl();
    app.settingsBtn = makeEl();
    app.configEditorBtn = makeEl();
    app._placeStatusLight = () => {};
    app.currentScreen = opts.currentScreen === undefined ? 'launchpad' : opts.currentScreen;
    return { app, ctx: sandbox, calls, screen, listeners, timers };
}

test('from home: the terminal page with the empty marker, and nothing attached', () => {
    const { app, ctx, calls, screen } = load();
    assert.equal(ctx.TerminalEmptyEntry.show(), true);
    assert.ok(screen.classList.contains('active'), 'the terminal screen is not active');
    assert.ok(screen.classList.contains(EMPTY), 'the empty marker is missing');
    assert.equal(calls.opened, 1, 'the panel was not mounted');
    assert.equal(app.currentScreen, 'terminal');
    assert.equal(calls.connect + calls.reconnect, 0, 'the empty page attached a session');
    assert.equal(calls.sockets, 0, 'the empty page opened a socket');
    assert.deepEqual(calls.pushed, ['/session'], 'the address bar does not say /session');
    assert.deepEqual(calls.active.at(-1), [null, null], 'the drawer still marks a session active');
    assert.ok(calls.sidebarShow >= 1, 'the agents drawer was not shown');
    assert.deepEqual(calls.begin, ['terminal-empty'], 'no navigation was declared');
    assert.equal(calls.header.at(-1), 'terminal.empty.header');
    assert.deepEqual(calls.sidebarOpen, [false],
        'the empty page did not force the drawer open without persisting');
    assert.equal(ctx.SessionSidebar.isOpen, true, 'the drawer is not open on the empty page');
});

test('the drawer opens even when the user had it stored closed, on any width', () => {
    const { ctx, calls } = load();
    assert.equal(ctx.SessionSidebar.isOpen, false, 'test setup: expected the drawer closed before show()');
    ctx.TerminalEmptyEntry.show();
    assert.equal(ctx.SessionSidebar.isOpen, true, 'the empty page left the drawer closed');
    assert.deepEqual(calls.sidebarOpen, [false],
        'forcing the drawer open must not write the stored preference');
});

test('the drawer is not re-opened, or its preference touched, when it was already open', () => {
    const { ctx, calls } = load({ sidebarOpen: true });
    ctx.TerminalEmptyEntry.show();
    assert.equal(ctx.SessionSidebar.isOpen, true);
    assert.deepEqual(calls.sidebarOpen, [], 'open() was called again on an already-open drawer');
});

test('a cold load of /session is rewritten to /#sessions and never shows the empty page', () => {
    const { ctx, calls, screen, timers } = load({ pathname: '/session', currentScreen: null });
    ctx.CloudeWeb.openSessionsScreen = () => { calls.sessionsView = (calls.sessionsView || 0) + 1; return true; };
    ctx.Router.init = undefined;
    vm.runInContext(js('router.js'), ctx);
    ctx.Router.init();
    assert.deepEqual(calls.replaced, ['/#sessions'], 'the bare route was not rewritten to the sessions view');
    ctx.AppBootComplete.announce();
    while (timers.length) timers.shift()();
    assert.ok(!screen.classList.contains(EMPTY), 'the empty terminal page was shown for /session');
    assert.equal(calls.opened, 0, 'the empty panel was mounted');
    assert.equal(calls.sessionsView || 0, 0);
});

test('NEGATIVE CONTROL: entering a real session never force-opens the drawer', async () => {
    const { app, calls } = load();
    await app.returnToExistingTerminal({ tmux_session: 'cloude_api', session: { id: 's1' } });
    assert.deepEqual(calls.sidebarOpen, [],
        'a real session entry called SessionSidebar.open(), which only the empty page should do');
});

test('a previous session\'s theme is not left painted', () => {
    const { app, ctx, calls } = load();
    app.returnToExistingTerminal({ tmux_session: 'cloude_api', pinned_theme: 'matrix', session: { id: 's1' } });
    const cleared = calls.clearSession;
    ctx.TerminalEmptyEntry.show();
    assert.equal(calls.clearSession, cleared + 1, 'the session theme scope was not dropped');
    assert.equal(calls.scopes.at(-1), null, 'a session theme scope is still set');
    assert.equal(calls.applied.at(-1), 'claude', 'the page is not the global theme');
    assert.equal(calls.pause, 1, 'the live pane\'s socket was not paused on the way in');
});

test('the cell grid stays unmounted while the page is empty', () => {
    const { ctx } = load();
    ctx.TerminalEmptyEntry.show();
    assert.equal(ctx.TerminalGridHost.onTerminal(), false,
        'the grid host would mount cells, and their viewer sockets, on the empty page');
});

test('Back or Forward onto an old /session entry goes home and opens the sessions view', () => {
    const { app, ctx, calls, screen, listeners } = load({ pathname: '/session', currentScreen: 'terminal' });
    let home = 0;
    app.showLaunchpad = () => { home += 1; };
    ctx.CloudeWeb.openSessionsScreen = () => { calls.sessionsView = (calls.sessionsView || 0) + 1; return true; };
    ctx.Router.init = undefined;
    vm.runInContext(js('router.js'), ctx);
    ctx.Router.init();
    calls.replaced.length = 0;
    ctx.location.pathname = '/session';
    for (const fn of listeners.get('popstate') || []) fn({});
    assert.deepEqual(calls.replaced, ['/#sessions']);
    assert.equal(home, 1, 'popstate onto /session did not go home');
    assert.equal(calls.sessionsView, 1, 'popstate onto /session did not open the sessions view');
    assert.ok(!screen.classList.contains(EMPTY), 'the empty terminal page was shown');
});

test('a popstate whose hash names a menu page is the page shell\'s, the router does not navigate', () => {
    const { app, ctx, calls, listeners } = load({ pathname: '/session', currentScreen: 'terminal' });
    let home = 0;
    app.showLaunchpad = () => { home += 1; };
    ctx.CloudeWeb.openSessionsScreen = () => { calls.sessionsView = (calls.sessionsView || 0) + 1; return true; };
    ctx.CloudeWeb.namesMenuPage = (hash) => hash === '#projects/c/5';
    ctx.Router.init = undefined;
    vm.runInContext(js('router.js'), ctx);
    ctx.Router.init();
    calls.replaced.length = 0;
    ctx.location.pathname = '/session';
    ctx.location.hash = '#projects/c/5';
    for (const fn of listeners.get('popstate') || []) fn({});
    assert.deepEqual(calls.replaced, []);
    assert.equal(home, 0, 'a company hash popstate took the menu page down to the launcher');
    assert.equal(calls.sessionsView || 0, 0);
});

test('NEGATIVE CONTROL: a named /session/<name> is still a session deep link, not the sessions view', () => {
    const { ctx, calls } = load({ pathname: '/session/cloude_api', currentScreen: null });
    ctx.CloudeWeb.openSessionsScreen = () => { calls.sessionsView = (calls.sessionsView || 0) + 1; return true; };
    ctx.Router.init = undefined;
    vm.runInContext(js('router.js'), ctx);
    ctx.Router.init();
    assert.ok(!calls.replaced.includes('/#sessions'), 'a named session link was sent to the sessions view');
    assert.equal(calls.sessionsView || 0, 0);
});

test('NEGATIVE CONTROL: a session picked from the drawer still attaches and clears the page', async () => {
    const { app, ctx, calls, screen } = load();
    ctx.TerminalEmptyEntry.show();
    await app.returnToExistingTerminal({ tmux_session: 'cloude_api', session: { id: 's1' } });
    assert.equal(calls.reconnect, 1, 'the session did not attach');
    assert.ok(!screen.classList.contains(EMPTY), 'the empty marker outlived the session entry');
    assert.ok(calls.closed >= 1, 'hideAllScreens did not close the empty panel');
    assert.equal(ctx.TerminalGridHost.onTerminal(), true, 'the grid would not come back');
});

test('the committed bundle publishes a closer that clears the marker, and hideAllScreens calls it', () => {
    const screen = makeEl();
    screen.setAttribute('id', 'terminal-screen');
    for (const cls of ['screen', 'active', EMPTY]) screen.classList.add(cls);
    const context = vm.createContext({
        document: {
            getElementById: (id) => (id === 'terminal-screen' ? screen : null),
            querySelector: () => null,
            querySelectorAll: () => [],
            createElement: makeEl,
            addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
        },
    });
    const web = installCloudeWeb(context);
    assert.equal(typeof web.openTerminalEmpty, 'function');
    assert.equal(typeof web.closeTerminalEmpty, 'function');
    assert.equal(web.closeTerminalEmpty(), true);
    assert.ok(!screen.classList.contains(EMPTY), 'the real closer left the marker on');
    assert.equal(web.closeTerminalEmpty(), false, 'a second close claimed to close something');
    assert.match(js('app.js'), /\['closeCatalogScreen'(?:, '\w+')*, 'closeTerminalEmpty'\]/,
        'App.hideAllScreens() no longer closes the empty terminal page, or closeTerminalEmpty is no longer called last');
});
