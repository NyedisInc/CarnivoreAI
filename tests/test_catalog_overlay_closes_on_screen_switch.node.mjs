// ----------------------------------------------------------------------
// could not reach

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

import { installCloudeWeb } from './helpers/cloude-web-sandbox.mjs';
import { MiniDocument } from './mini-dom.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

function read(relative) {
    return fs.readFileSync(path.join(ROOT, relative), 'utf8');
}

function realNamespace() {
    return installCloudeWeb(vm.createContext({}));
}

function shippedHideAllScreens() {
    const source = read('client/js/app.js');
    const start = source.indexOf('hideAllScreens() {');
    assert.notEqual(start, -1, 'App.hideAllScreens() is not in client/js/app.js');
    const open = source.indexOf('{', start);
    let depth = 0;
    let end = -1;
    for (let i = open; i < source.length; i += 1) {
        if (source[i] === '{') depth += 1;
        else if (source[i] === '}') {
            depth -= 1;
            if (depth === 0) {
                end = i;
                break;
            }
        }
    }
    assert.notEqual(end, -1, 'unbalanced braces in App.hideAllScreens()');
    const body = source.slice(open + 1, end);
    return vm.runInNewContext(`(function (window, document) {${body}})`);
}

function documentWithScreens() {
    const document = new MiniDocument();
    for (const id of ['auth-screen', 'launchpad-screen', 'archive-screen', 'terminal-screen']) {
        const el = document.createElement('div');
        el.setAttribute('id', id);
        el.classList.add('screen', 'active');
        document.body.appendChild(el);
    }
    for (const id of ['catalog-screen', 'ledger-screen', 'themes-screen']) {
        const overlay = document.createElement('div');
        overlay.setAttribute('id', id);
        document.body.appendChild(overlay);
    }
    return document;
}

function allDeactivated(document) {
    return document
        .querySelectorAll('.screen')
        .every((el) => !el.classList.contains('active'));
}

test('the catalog container is still outside the .screen family, which is why the call exists', () => {
    const tag = read('client/index.html').match(/<div id="catalog-screen"[^>]*>/);
    assert.ok(tag, '#catalog-screen is missing from client/index.html');
    assert.ok(
        !/class\s*=/.test(tag[0]),
        '#catalog-screen has gained a class attribute. If it joined the .screen '
        + 'family, hideAllScreens() reaches it on its own and this whole fix is '
        + 'the wrong shape - but ScreenChrome.apply() keys on three screen names '
        + 'and would need a fourth.',
    );
});

test('the committed bundle publishes closeCatalogScreen on window.CloudeWeb', () => {
    assert.equal(typeof realNamespace().closeCatalogScreen, 'function');
});

test('and with nothing mounted it answers false rather than throwing', () => {
    const web = realNamespace();
    assert.doesNotThrow(() => web.closeCatalogScreen());
    assert.equal(web.closeCatalogScreen(), false);
});

test('hideAllScreens deactivates every screen AND closes the catalog overlay', () => {
    const web = realNamespace();
    let calls = 0;
    const real = web.closeCatalogScreen;
    web.closeCatalogScreen = (...args) => {
        calls += 1;
        return real(...args);
    };
    const document = documentWithScreens();
    shippedHideAllScreens()({ CloudeWeb: web }, document);

    assert.ok(allDeactivated(document), 'hideAllScreens left a .screen active');
    assert.equal(
        calls,
        1,
        'hideAllScreens() did not close the catalog overlay. Without this the '
        + 'overlay stays painted over whatever the app navigates to next.',
    );
});

test('the ledger container is still outside the .screen family, for the same reason', () => {
    const tag = read('client/index.html').match(/<div id="ledger-screen"[^>]*>/);
    assert.ok(tag, '#ledger-screen is missing from client/index.html');
    assert.ok(
        !/class\s*=/.test(tag[0]),
        '#ledger-screen has gained a class attribute. If it joined the .screen '
        + 'family, hideAllScreens() reaches it on its own and the second call '
        + 'below is the wrong shape.',
    );
});

test('the committed bundle publishes closeLedgerScreen on window.CloudeWeb', () => {
    assert.equal(typeof realNamespace().closeLedgerScreen, 'function');
});

test('and with nothing mounted closeLedgerScreen answers false rather than throwing', () => {
    const web = realNamespace();
    assert.doesNotThrow(() => web.closeLedgerScreen());
    assert.equal(web.closeLedgerScreen(), false);
});

test('the themes page container is outside the .screen family too', () => {
    const tag = read('client/index.html').match(/<div id="themes-screen"[^>]*>/);
    assert.ok(tag, '#themes-screen is missing from client/index.html');
    assert.ok(!/class\s*=/.test(tag[0]), '#themes-screen has gained a class attribute.');
});

test('the committed bundle publishes closeThemesScreen, which answers false with nothing mounted', () => {
    const web = realNamespace();
    assert.equal(typeof web.closeThemesScreen, 'function');
    assert.doesNotThrow(() => web.closeThemesScreen());
    assert.equal(web.closeThemesScreen(), false);
});

test('hideAllScreens closes EVERY overlay, not just the first one added', () => {
    const web = realNamespace();
    const calls = { catalog: 0, ledger: 0, themes: 0 };
    const realCatalog = web.closeCatalogScreen;
    const realLedger = web.closeLedgerScreen;
    const realThemes = web.closeThemesScreen;
    web.closeThemesScreen = (...args) => {
        calls.themes += 1;
        return realThemes(...args);
    };
    web.closeCatalogScreen = (...args) => {
        calls.catalog += 1;
        return realCatalog(...args);
    };
    web.closeLedgerScreen = (...args) => {
        calls.ledger += 1;
        return realLedger(...args);
    };
    const document = documentWithScreens();
    shippedHideAllScreens()({ CloudeWeb: web }, document);

    assert.ok(allDeactivated(document), 'hideAllScreens left a .screen active');
    assert.deepEqual(
        calls,
        { catalog: 1, ledger: 1, themes: 1 },
        'hideAllScreens() did not close every overlay. Whichever count is 0 is '
        + 'an overlay that stays painted over whatever the app navigates to.',
    );
});

test('and on a page where the compiled bundle never loaded it still deactivates the screens', () => {
    const document = documentWithScreens();
    assert.doesNotThrow(() => shippedHideAllScreens()({}, document));
    assert.ok(allDeactivated(document));
});
