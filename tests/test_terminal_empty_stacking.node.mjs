
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

function read(relative) {
    return fs.readFileSync(path.join(ROOT, relative), 'utf8');
}

function zIndexOf(css, selector) {
    const rule = new RegExp(`${selector}\\s*\\{([^}]*)\\}`).exec(css);
    assert.ok(rule, `no rule found for ${selector}`);
    const z = /z-index:\s*(-?\d+)/.exec(rule[1]);
    assert.ok(z, `rule for ${selector} carries no numeric z-index`);
    return Number(z[1]);
}

test('the no-session panel paints under the header and the agents drawer', () => {
    const bundle = read('client/dist/app.css');
    const panel = zIndexOf(bundle, '\\.terminal-empty\\.svelte-[a-z0-9]+');
    const sidebar = read('client/css/session-sidebar.css');
    const backdrop = zIndexOf(sidebar, '\\n\\.session-sidebar-backdrop');
    const drawer = zIndexOf(sidebar, '\\n\\.session-sidebar-panel');
    const header = zIndexOf(read('client/css/styles.css'), '\\n\\.header');
    assert.ok(panel > 10, `panel z-index ${panel} must clear xterm's layers (10)`);
    assert.ok(panel < header, `panel z-index ${panel} must sit under the header (${header})`);
    assert.ok(panel < backdrop, `panel z-index ${panel} must sit under the drawer backdrop (${backdrop})`);
    assert.ok(panel < drawer, `panel z-index ${panel} must sit under the drawer (${drawer})`);
});

test('the terminal container is not a stacking context', () => {
    const rule = /\n\.terminal-container\s*\{([^}]*)\}/.exec(read('client/css/styles.css'));
    assert.ok(rule, 'no .terminal-container rule');
    const body = rule[1].replace(/\/\*[\s\S]*?\*\//g, '');
    assert.doesNotMatch(body, /z-index|isolation|transform|contain:/);
});

test('the empty state hides the phone key bar', () => {
    const sheet = read('client/css/terminal-empty.css').replace(/\/\*[\s\S]*?\*\//g, '');
    const rule = /body:has\(#terminal-screen\.terminal-screen--empty\.active\)\s*:is\(([^)]*)\)\s*\{([^}]*)\}/.exec(sheet);
    assert.ok(rule, 'no empty-state hide rule');
    assert.match(rule[1], /#terminal-key-bar\b/);
    assert.match(rule[2], /display:\s*none/);
});
