
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..', '..');
const SRC = fs.readFileSync(path.join(ROOT, 'client/js/terminal-history-load.js'), 'utf8');

function make() {
    const painted = [];
    const requests = [];
    const win = {
        console: { log() {}, warn() {}, debug() {}, error() {} },
        Uint8Array, Promise, setTimeout, clearTimeout,
        API: { getSession: async (...a) => { requests.push(a); return {}; } },
        TerminalController: null,
        TerminalReconnectBuffer: { measureBufferLines: (t) => t.buffer.active.lines },
        TerminalScrollbackPaint: {
            decodeCapture: (b64) => Uint8Array.from(Buffer.from(b64, 'base64')),
            async paint(shim, b64, what, opts) {
                painted.push({ b64, what, opts });
                shim.term.buffer.active.lines = Buffer.from(b64, 'base64').filter((b) => b === 10).length;
                shim._forceScrollToBottom();
                return 'painted';
            },
        },
    };
    win.window = win;
    vm.createContext(win);
    vm.runInContext(SRC, win, { filename: 'terminal-history-load.js' });
    const term = { cols: 80, rows: 24, options: { scrollback: 5000 }, buffer: { active: { type: 'normal', baseY: 0, viewportY: 0, lines: 0 } } };
    return { History: win.TerminalHistory, term, painted, requests };
}

const b64Of = (text) => Buffer.from(text, 'binary').toString('base64');

test('late bytes handed in as capturedB64 are painted with no second request, and stillValid reaches the painter', async () => {
    const { History, term, painted, requests } = make();
    const stillValid = () => true;
    const out = await History.ensureLoaded(term, 'ses_1', null, { capturedB64: b64Of('a\nb\nc\n'), stillValid });
    assert.equal(out.loaded, 'painted');
    assert.equal(out.lines, 3);
    assert.equal(requests.length, 0, 'the caller already holds the bytes, so no request is made');
    assert.equal(painted.length, 1);
    assert.equal(painted[0].b64, b64Of('a\nb\nc\n'));
    assert.equal(painted[0].opts.stillValid, stillValid);
    assert.equal(painted[0].opts.clearScrollback, true);
});

test('the alreadyLoaded memo of an earlier paint does not make the late paint a no-op', async () => {
    const { History, term, painted, requests } = make();
    assert.equal((await History.ensureLoaded(term, 'ses_1', null, { capturedB64: b64Of('a\n') })).loaded, 'painted');
    const out = await History.ensureLoaded(term, 'ses_1', null, { capturedB64: b64Of('a\nb\nc\nd\n') });
    assert.equal(out.loaded, 'painted', 'a deeper late capture is painted, not answered already');
    assert.equal(painted.length, 2);
    assert.equal(requests.length, 0);
});
