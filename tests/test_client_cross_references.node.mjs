import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const exists = (rel) => fs.existsSync(path.join(ROOT, rel));

const code = (src) =>
    src.split('\n').filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n');

function clientScripts() {
    return walk('client/js', ['.js']);
}

function walk(rel, exts) {
    const out = [];
    const dir = path.join(ROOT, rel);
    if (!fs.existsSync(dir)) return out;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const child = `${rel}/${entry.name}`;
        if (entry.isDirectory()) out.push(...walk(child, exts));
        else if (exts.some((e) => entry.name.endsWith(e))) out.push(child);
    }
    return out;
}

function providerBlob() {
    const files = [
        ...clientScripts(),
        ...walk('web/src', ['.ts', '.svelte']),
        'client/index.html',
    ];
    if (exists('client/dist/app.js')) files.push('client/dist/app.js');
    files.push(...walk('client/vendor', ['.js']));
    return files.map(read).join('\n');
}

function aliasedGlobalPublications(source) {
    const found = new Set();
    const text = code(source);
    for (const binding of text.matchAll(/\bconst\s+([A-Za-z_$][\w$]*)\s*=\s*globalThis\s+as\b/g)) {
        const alias = binding[1];
        const writes = text.slice(binding.index + binding[0].length);
        const escaped = alias.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        for (const write of writes.matchAll(new RegExp(`\\b${escaped}\\.([A-Z][A-Za-z0-9_]*)\\s*=(?!=)`, 'g'))) {
            found.add(write[1]);
        }
    }
    return found;
}


const AMBIENT = new Set([
    'Terminal', 'FitAddon', 'WebglAddon', 'Unicode11Addon', 'SearchAddon',
    'CustomEvent', 'Promise', 'Event', 'Error', 'Math', 'JSON', 'Date', 'Object',
    'Array', 'String', 'Number', 'Boolean', 'Map', 'Set', 'WeakMap', 'WeakSet',
    'RegExp', 'Symbol', 'URL', 'URLSearchParams', 'WebSocket', 'Blob', 'File',
    'FileReader', 'FormData', 'Headers', 'Request', 'Response', 'AbortController',
    'TextEncoder', 'TextDecoder', 'Intl', 'Notification', 'MutationObserver',
    'ResizeObserver', 'IntersectionObserver', 'DOMParser', 'XMLHttpRequest',
    'Image', 'Audio', 'Worker', 'BroadcastChannel', 'Proxy', 'Reflect', 'BigInt',
    'ArrayBuffer', 'Uint8Array', 'Int8Array', 'Float32Array', 'Element',
    'HTMLElement', 'Node', 'Document', 'Window', 'Storage', 'History', 'Location',
    'Text', 'EventTarget', 'DataTransfer', 'Range', 'Selection', 'Clipboard',
    'ClipboardItem', 'Option', 'MediaQueryList', 'CSS', 'Intersection',
    'AudioContext', 'OfflineAudioContext', 'SpeechSynthesisUtterance',
]);

const OPTIONAL_GLOBALS = new Set([
    'ArchiveProjectOverlay',
    'TerminalInputFocus',
]);

test('every window.X a client script reads is published by something', () => {
    const blob = providerBlob();
    const published = new Set();
    for (const m of blob.matchAll(
        /(?:window|globalThis|global|root)\s*\.\s*([A-Z][A-Za-z0-9_]*)\s*=(?!=)/g,
    )) published.add(m[1]);
    for (const m of blob.matchAll(/\bpage\(\)\s*\.\s*([A-Z][A-Za-z0-9_]*)\s*=(?!=)/g)) {
        published.add(m[1]);
    }
    for (const rel of walk('web/src', ['.ts', '.svelte'])) {
        for (const name of aliasedGlobalPublications(read(rel))) published.add(name);
    }

    const missing = [];
    let checked = 0;
    for (const rel of clientScripts()) {
        for (const m of code(read(rel)).matchAll(
            /\b(?:window|globalThis|global)\s*\.\s*([A-Z][A-Za-z0-9_]*)\b/g,
        )) {
            if (AMBIENT.has(m[1]) || OPTIONAL_GLOBALS.has(m[1])) continue;
            checked += 1;
            if (!published.has(m[1])) missing.push(`${rel} -> window.${m[1]}`);
        }
    }

    assert.ok(checked > 500,
        `only ${checked} global reads seen; the matcher has probably stopped matching`);
    assert.deepEqual([...new Set(missing)], [],
        'a client script reads a global nothing publishes. It will not throw at '
        + 'import; it throws when the line runs, or silently does nothing');
});

test('NEGATIVE CONTROL: an unpublished global really is reported', () => {
    const sample = code("window.NoSuchModuleHere.doThing();");
    const hits = [...sample.matchAll(
        /\b(?:window|globalThis|global)\s*\.\s*([A-Z][A-Za-z0-9_]*)\b/g,
    )].map((m) => m[1]);
    assert.deepEqual(hits, ['NoSuchModuleHere']);
    assert.ok(!AMBIENT.has('NoSuchModuleHere'));
    assert.deepEqual([...aliasedGlobalPublications('const host = {}; host.NoSuchModuleHere = true;')], []);
    assert.deepEqual([...aliasedGlobalPublications('const host = globalThis as unknown as {}; host.Real = true;')], ['Real']);
    assert.deepEqual([...aliasedGlobalPublications('const host = globalThis as unknown as {}; other.NoSuchModuleHere = true;')], []);
});


const KNOWN_ABSENT_IDS = new Set([
    'detachSessionBtn',
]);

test('every DOM id a client script looks up is emitted somewhere', () => {
    const blob = providerBlob();
    const emitted = new Set();
    for (const m of blob.matchAll(/\bid\s*=\s*"([A-Za-z0-9_\-]+)"/g)) emitted.add(m[1]);
    for (const m of blob.matchAll(/\bid\s*=\s*'([A-Za-z0-9_\-]+)'/g)) emitted.add(m[1]);
    for (const m of blob.matchAll(/\.id\s*=\s*['"]([A-Za-z0-9_\-]+)['"]/g)) emitted.add(m[1]);
    for (const m of blob.matchAll(
        /setAttribute\(\s*['"]id['"]\s*,\s*['"]([A-Za-z0-9_\-]+)['"]/g,
    )) emitted.add(m[1]);

    const missing = [];
    let checked = 0;
    for (const rel of clientScripts()) {
        const src = code(read(rel));
        const reads = [
            ...src.matchAll(/getElementById\(\s*['"]([A-Za-z0-9_\-]+)['"]/g),
            ...src.matchAll(/querySelector(?:All)?\(\s*['"]#([A-Za-z0-9_\-]+)['"]/g),
        ];
        for (const m of reads) {
            checked += 1;
            if (emitted.has(m[1]) || KNOWN_ABSENT_IDS.has(m[1])) continue;
            missing.push(`${rel} -> #${m[1]}`);
        }
    }

    assert.ok(checked > 50,
        `only ${checked} id reads seen; the matcher has probably stopped matching`);
    assert.deepEqual([...new Set(missing)], [],
        'a client script looks up an id nothing emits. getElementById returns '
        + 'null, the guard in front of it swallows that, and the feature is '
        + 'simply absent with nothing reporting it');
});

test('the known-absent id list has not started hiding live breakage', () => {
    const blob = providerBlob();
    for (const id of KNOWN_ABSENT_IDS) {
        const emitted = new RegExp(`\\bid\\s*=\\s*["']${id}["']`).test(blob);
        assert.ok(!emitted,
            `#${id} is emitted now, so remove it from KNOWN_ABSENT_IDS - an `
            + 'exemption for a reference that works is an exemption that will '
            + 'outlive the next time it stops working');
    }
    const readers = clientScripts().map(read).join('\n');
    for (const id of KNOWN_ABSENT_IDS) {
        assert.ok(readers.includes(id),
            `#${id} is no longer read by any client script; drop the exemption`);
    }
});


test('every data-attribute a client script reads is written somewhere', () => {
    const blob = providerBlob();
    const written = new Set();
    for (const m of blob.matchAll(/\bdata-([a-z0-9\-]+)\s*=/g)) written.add(m[1]);
    for (const m of blob.matchAll(/\bdata-([a-z0-9\-]+)[\s'">]/g)) written.add(m[1]);
    for (const m of blob.matchAll(/dataset\s*\.\s*([A-Za-z0-9_]+)\s*=(?!=)/g)) {
        written.add(m[1].replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`));
    }
    const camel = (d) => d.split('-').map(
        (p, i) => (i === 0 ? p : p.charAt(0).toUpperCase() + p.slice(1)),
    ).join('');
    const writtenCamel = new Set([...written].map(camel));

    const OPT_IN_ATTRS = new Set(['keep-open']);

    const missing = [];
    let checked = 0;
    for (const rel of clientScripts()) {
        const src = code(read(rel));
        for (const m of src.matchAll(/\[data-([a-z0-9\-]+)[\]=~^*$|]/g)) {
            if (OPT_IN_ATTRS.has(m[1])) continue;
            checked += 1;
            if (!written.has(m[1])) missing.push(`${rel} -> [data-${m[1]}]`);
        }
        for (const m of src.matchAll(/getAttribute\(\s*['"]data-([a-z0-9\-]+)['"]/g)) {
            checked += 1;
            if (!written.has(m[1])) missing.push(`${rel} -> data-${m[1]}`);
        }
        for (const m of src.matchAll(/\.dataset\s*\.\s*([A-Za-z0-9_]+)\b(?!\s*=)/g)) {
            checked += 1;
            if (!writtenCamel.has(m[1])) missing.push(`${rel} -> dataset.${m[1]}`);
        }
    }

    assert.ok(checked > 30,
        `only ${checked} data-attribute reads seen; the matcher has probably stopped`);
    assert.deepEqual([...new Set(missing)], [],
        'a client script reads a data-attribute nothing writes. This is the '
        + 'data-row-status shape exactly: the read returns null, every suite '
        + 'still passes, and the behaviour behind it is gone');
});

test('THE ROW-STATUS PRECEDENT, asserted writer-against-reader', () => {
    const menu = read('web/src/lib/item-menu/row-context.ts');
    const clicks = code(read('web/src/lib/drawer/restart-click.ts'));

    const stamped = [...menu.matchAll(/'(data-row-menu[a-z\-]*)="'|\['(data-row-menu[a-z\-]*)'\]\s*=(?!=)|^\s*'(data-row-menu[a-z\-]*)':/gm)]
        .map((m) => m[1] || m[2] || m[3]);
    const triggerAttr = /TRIGGER_ATTR\s*=\s*'([a-z\-]+)'/.exec(menu);
    assert.ok(triggerAttr, 'row-context.ts must define TRIGGER_ATTR');
    stamped.push(triggerAttr[1]);
    assert.ok(stamped.includes('data-row-menu-status'),
        'triggerSpec (web/src/lib/item-menu/row-context.ts) must stamp the status attribute on the trigger');
    assert.equal(triggerAttr[1], 'data-row-menu',
        'the selector key the reader hardcodes is `data-row-menu`; if the '
        + 'constant moves, the querySelector in web/src/lib/drawer/restart-click.ts '
        + 'stops matching and every restart silently reports unknown');

    assert.match(clicks, /querySelector\(\s*`?\[data-row-menu="/,
        'web/src/lib/drawer/restart-click.ts must resolve the TRIGGER by name. '
        + 'Pointing this at the row instead is the defect: the row does not '
        + 'carry the status, so runRestart silently receives null');
    const asked = [...clicks.matchAll(/getAttribute\('(data-row-menu[a-z\-]*)'\)/g)]
        .map((m) => m[1]);
    assert.ok(asked.includes('data-row-menu-status'),
        `the reader asks for ${JSON.stringify(asked)}, which the trigger does not stamp`);

    for (const attr of asked) {
        assert.ok(stamped.includes(attr),
            `web/src/lib/drawer/restart-click.ts reads ${attr}, which row-context.ts `
            + `never stamps. Stamped: ${JSON.stringify(stamped)}`);
    }
});

test('NEGATIVE CONTROL: writer and reader disagreeing really is caught', () => {
    const stamped = ['data-row-menu', 'data-row-menu-status'];
    const asked = ['data-row-status'];
    assert.ok(!asked.every((a) => stamped.includes(a)),
        'the old spelling must not compare equal to the new one');
    assert.ok(stamped.length > 0 && asked.length > 0,
        'and neither side may be empty, or the check proves nothing');
});

// ---------------------------------------------------------------------
// the home screen
// ---------------------------------------------------------------------
test('index.html loads no retired supersede module', () => {
    const indexHtml = read(path.join('client', 'index.html'));
    assert.ok(!/session-supersede\.js/.test(indexHtml),
        'index.html still loads the supersede module');
    assert.ok(
        !fs.existsSync(path.join(ROOT, 'client', 'js', 'session-supersede.js')),
        'client/js/session-supersede.js still exists');
});

test('NEGATIVE CONTROL: a script index.html DOES load is seen', () => {
    const indexHtml = read(path.join('client', 'index.html'));
    assert.ok(/app\.js/.test(indexHtml),
        'the scanner cannot see a script tag at all, so the claim above is vacuous');
    assert.ok(
        fs.existsSync(path.join(ROOT, 'client', 'js', 'app.js')),
        'the existence check answers false for a file that is present');
});
