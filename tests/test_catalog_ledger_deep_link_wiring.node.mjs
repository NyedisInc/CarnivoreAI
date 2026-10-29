// agrees with whatever it was built to agree with.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

import { installCloudeWeb } from './helpers/cloude-web-sandbox.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

function read(relative) {
    return fs.readFileSync(path.join(ROOT, relative), 'utf8');
}

test('the committed bundle contains hashchange', () => {
    const bundle = read('client/dist/app.js');
    assert.ok(
        bundle.includes('hashchange'),
        'client/dist/app.js has no hashchange listener - the #catalog and '
        + '#ledger hash routes are not wired on a real boot. Run `npm run '
        + 'build` from web/ and commit the result.',
    );
});

test('booting the bundle with no document at all registers twenty-two hashchange listeners', () => {
    const context = vm.createContext({});
    const calls = [];
    context.window = context;
    context.addEventListener = (type, fn) => calls.push(type) || fn;
    context.removeEventListener = () => {};
    context.dispatchEvent = () => true;

    const web = installCloudeWeb(context);

    assert.equal(typeof web.openCatalogScreen, 'function');
    assert.equal(typeof web.closeLedgerScreen, 'function');
    assert.ok(
        calls.includes('hashchange'),
        `window.addEventListener was never called with 'hashchange' during boot. Calls seen: ${JSON.stringify(calls)}`,
    );
    assert.equal(
        calls.filter((type) => type === 'hashchange').length,
        22,
        'expected exactly twenty-two hashchange listeners - #catalog, #ledger, '
        + '#themes, #browser/<id>, #blueprints, #plugins, #skills, #widgets, '
        + '#settings, #account, docs, keys, changelog, projects and '
        + 'sessions, plus the swarm, huddle agent, huddle settings and dashboards pages, plus the mods (#1466) and automations (#1490) pages, plus the pack, logs and war room pages less skills and projects, plus the deep search link opener (#1807) - to be installed at boot',
    );
});
