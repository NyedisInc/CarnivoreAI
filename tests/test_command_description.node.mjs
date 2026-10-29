
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let failures = 0;
let passes = 0;

function test(name, fn) {
    try {
        fn();
        passes += 1;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures += 1;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.stack ? err.stack : err);
    }
}

function makeEl(className, dataset = {}) {
    const classes = new Set(String(className).split(' ').filter(Boolean));
    return {
        dataset,
        _children: [],
        _parent: null,
        classList: {
            toggle(name, on) { if (on) classes.add(name); else classes.delete(name); },
            contains(name) { return classes.has(name); },
        },
        querySelector(sel) {
            const want = sel.replace('.', '');
            return this._children.find(c => c._classes.has(want)) || null;
        },
        closest(sel) {
            const want = sel.replace('.', '');
            let node = this;
            while (node) {
                if (node._classes.has(want)) return node;
                node = node._parent;
            }
            return null;
        },
        _classes: classes,
    };
}

function makeItem(command, full, shorten) {
    const item = makeEl('command-item', { command, description: full });
    const desc = makeEl('command-description');
    desc.textContent = shorten(full);
    item._children.push(desc);
    return item;
}

function load() {
    const sandbox = { console: { log() {}, warn() {}, error() {} } };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    for (const file of ['command-description.js', 'slash-command-filter.js']) {
        vm.runInContext(
            fs.readFileSync(path.join(__dirname, '..', 'client', 'js', file), 'utf8'),
            sandbox,
        );
    }
    return sandbox;
}

const w = load();
const CD = w.CommandDescription;

const FULL = 'Restore the conversation and the working tree to an earlier '
    + 'point, undoing edits claude made since then. Select a checkpoint '
    + 'from the list to roll back to.';


test('a description that already fits is left exactly as it is', () => {
    assert.equal(CD.shorten('wipe conversation', 90), 'wipe conversation');
});

test('a long description is cut and the cut is visible', () => {
    const label = CD.shorten(FULL, 90);
    assert.ok(label.length <= 90, `label was ${label.length} chars`);
    assert.ok(label.length < FULL.length, 'label must be shorter than the value');
    assert.ok(label.endsWith('...'), 'the cut must be visible');
});

test('the cut lands on a word boundary, never mid-word', () => {
    const label = CD.shorten(FULL, 90);
    const body = label.slice(0, -3);
    for (const word of body.split(' ')) {
        assert.ok(FULL.split(/\s+/).includes(word), `"${word}" is not a whole source word`);
    }
});

test('shortening never mutates its input', () => {
    const before = FULL;
    CD.shorten(FULL, 40);
    assert.equal(FULL, before);
});

test('isShortened reports honestly in both directions', () => {
    assert.equal(CD.isShortened('short one', 90), false);
    assert.equal(CD.isShortened(FULL, 90), true);
});

test('a phone gets a tighter cap than a desktop', () => {
    assert.ok(CD.maxChars(375) < CD.maxChars(1280),
        'the narrow cap must be tighter than the wide one');
});

test('an empty or missing description is not an error', () => {
    assert.equal(CD.shorten(undefined, 90), '');
    assert.equal(CD.shorten(null, 90), '');
    assert.equal(CD.shorten('', 90), '');
});


test('THE LABEL IS NOT THE VALUE: search matches a word only in the truncated tail', () => {
    const shorten = (t) => CD.shorten(t, 90);
    const category = makeEl('command-category');
    const rewind = makeItem('/rewind', FULL, shorten);
    const clear = makeItem('/clear', 'Clear the conversation history.', shorten);
    for (const item of [rewind, clear]) {
        item._parent = category;
        category._children.push(item);
    }
    const root = makeEl('root');
    root.querySelectorAll = () => [rewind, clear];

    const rendered = rewind.querySelector('.command-description').textContent;
    assert.ok(!rendered.includes('checkpoint'),
        'test is vacuous unless the word is genuinely truncated away');
    assert.ok(FULL.includes('checkpoint'), 'the value must still carry it');

    const filter = new w.SlashCommandFilter();
    filter.index(root);
    filter.apply('checkpoint');

    assert.equal(rewind.classList.contains('filter-hidden'), false,
        'a term in the truncated tail must still match');
    assert.equal(clear.classList.contains('filter-hidden'), true,
        'a non-matching command must still be filtered out');
});

test('search still matches the command name', () => {
    const shorten = (t) => CD.shorten(t, 90);
    const category = makeEl('command-category');
    const rewind = makeItem('/rewind', FULL, shorten);
    rewind._parent = category;
    category._children.push(rewind);
    const root = makeEl('root');
    root.querySelectorAll = () => [rewind];

    const filter = new w.SlashCommandFilter();
    filter.index(root);
    filter.apply('rewi');
    assert.equal(rewind.classList.contains('filter-hidden'), false);
});

test('a row with no data-description still searches its rendered text', () => {
    const category = makeEl('command-category');
    const item = makeEl('command-item', { command: '/legacy' });
    const desc = makeEl('command-description');
    desc.textContent = 'legacy rendered description';
    item._children.push(desc);
    item._parent = category;
    category._children.push(item);
    const root = makeEl('root');
    root.querySelectorAll = () => [item];

    const filter = new w.SlashCommandFilter();
    filter.index(root);
    filter.apply('rendered');
    assert.equal(item.classList.contains('filter-hidden'), false);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures === 0) console.log('ALL PASS');
process.exit(failures === 0 ? 0 : 1);
