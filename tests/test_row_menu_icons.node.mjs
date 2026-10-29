import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { glyphSvg, GLYPHS as SHARED_GLYPHS } from '../client/js/icons/glyphs.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const clientJs = (f) => fs.readFileSync(path.join(__dirname, '..', 'client', 'js', f), 'utf8');

let passes = 0;
let failures = 0;
const queue = [];
const test = (name, fn) => queue.push([name, fn]);

function load(withBridge) {
    const context = { console };
    context.globalThis = context;
    context.window = context;
    if (withBridge) context.CloudeGlyphs = { glyphSvg };
    vm.createContext(context);
    vm.runInContext(clientJs('session-row-menu-icons.js'), context);
    return context.SessionRowMenuIcons;
}

test('the share item borrows the SHARED telescope, byte for byte', () => {
    const icons = load(true);
    const borrowed = icons.svg('share-read-only', 14);
    assert.ok(borrowed.length > 0, 'the share item drew no icon at all');
    assert.equal(
        borrowed,
        glyphSvg('telescope', 14),
        'the menu drew something OTHER than the shared telescope',
    );
});

test('and it is genuinely the telescope, not an empty shell', () => {
    const icons = load(true);
    const borrowed = icons.svg('share-read-only', 14);
    assert.ok(borrowed.includes('<path'), `no path element in: ${borrowed}`);
    const shared = SHARED_GLYPHS.telescope;
    assert.ok(Array.isArray(shared) && shared.length > 0, 'the shared telescope is empty');
    for (const element of shared) {
        if (!element.d) continue;
        assert.ok(
            borrowed.includes(element.d),
            `a path of the shared telescope is missing from the menu icon: ${element.d}`,
        );
    }
});

test('it is drawn at the MENU size, not the glyph table default', () => {
    const icons = load(true);
    assert.ok(icons.svg('share-read-only', 14).includes('width="14"'), 'not 14px');
    assert.ok(glyphSvg('telescope').includes('width="16"'), 'the shared default moved off 16');
});

test('the path is NOT duplicated into this module', () => {
    const src = clientJs('session-row-menu-icons.js');
    for (const element of SHARED_GLYPHS.telescope) {
        if (!element.d) continue;
        assert.ok(
            !src.includes(element.d),
            'a shared telescope path was copied into the row menu icon table',
        );
    }
});

test('a missing glyph bridge costs the icon, never the menu', () => {
    const icons = load(false);
    assert.equal(icons.svg('share-read-only', 14), '', 'expected a silent blank');
});

test('the locally drawn glyphs still work, at the size asked for', () => {
    const icons = load(true);
    for (const id of ['rename', 'fork', 'mute', 'restart', 'close']) {
        const out = icons.svg(id, 14);
        assert.ok(out.includes('<path'), `${id} drew nothing`);
        assert.ok(out.includes('width="14"'), `${id} ignored the size`);
        assert.ok(out.includes('aria-hidden="true"'), `${id} lost its aria-hidden`);
    }
});

test('an unknown id is a blank, not a throw', () => {
    const icons = load(true);
    assert.equal(icons.svg('no-such-item', 14), '');
});

test('the menu hides the icon WRAPPER, so a borrowed mark is hidden too', () => {
    const menu = fs.readFileSync(path.join(__dirname, '..', 'web', 'src', 'lib', 'drawer-tabs', 'CascadeMenu.svelte'), 'utf8');
    const at = menu.indexOf('<span class="acm-icon" aria-hidden="true">{@html node.glyphHtml}');
    assert.ok(at > 0, 'the icon span no longer carries aria-hidden');
});

test('the id the menu looks up is the id the plugin contributes', () => {
    const contribution = fs.readFileSync(
        path.join(__dirname, '..', 'web', 'src', 'cplugs', 'share', 'index.ts'),
        'utf8',
    );
    const match = contribution.match(/ACTION_ID = '([^']+)'/);
    assert.ok(match, 'could not read ACTION_ID from the contribution');
    const icons = load(true);
    assert.ok(
        icons.svg(match[1], 14).length > 0,
        `the menu has no icon for the contributed id "${match[1]}"`,
    );
});

for (const [name, fn] of queue) {
    try { await fn(); console.log(`ok - ${name}`); passes++; }
    catch (err) { console.log(`NOT OK - ${name}`); console.error(err.message); failures++; }
}
console.log(`\n${passes} passed, ${failures} failed`);
if (failures === 0) console.log('ALL PASS');
process.exit(failures === 0 ? 0 : 1);
