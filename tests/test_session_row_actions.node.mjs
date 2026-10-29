// WHY THIS FILE EXISTS: the repo has no package.json / jest / mocha, so the
// established pattern for testing client JS is a `vm`-sandboxed node script
// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
// SLICE 3: the session data layer lives in the compiled bundle, and the
// `Launchpad` fields this harness drives are accessors over that one
// store. The REAL client/dist/app.js is evaluated in this sandbox rather
// than stubbed, so these assertions run against the shipped path.
import { installCloudeWeb } from './helpers/cloude-web-sandbox.mjs';
import { glyphSvg } from '../client/js/icons/glyphs.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** Read one client JS module's source. */
function readClientJs(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'js', name), 'utf8');
}

let failures = 0;
let passes = 0;
const queue = [];

function test(name, fn) {
    queue.push([name, fn]);
}

async function runQueue() {
    for (const [name, fn] of queue) {
        try {
            await fn();
            passes++;
            console.log(`ok - ${name}`);
        } catch (err) {
            failures++;
            console.error(`NOT OK - ${name}`);
            console.error(err && err.stack ? err.stack : err);
        }
    }
}

function makeSandbox() {
    const confirmCalls = [];

    function makeEscapingDiv() {
        let text = '';
        return {
            set textContent(v) { text = v == null ? '' : String(v); },
            get textContent() { return text; },
            get innerHTML() {
                return text
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;');
            },
        };
    }

    const fakeDocument = {
        createElement() { return makeEscapingDiv(); },
        getElementById() { return null; },
        querySelectorAll() { return []; },
        addEventListener() {},
    };

    const fakeWindow = {
        App: {
            showConfirmModal(title, message, details, primaryLabel, secondaryLabel) {
                confirmCalls.push([title, message, details, primaryLabel, secondaryLabel]);
                return Promise.resolve(true);
            },
        },
    };
    fakeWindow.window = fakeWindow;

    // publishes it in a browser. Every icon in session-status-ui.js reads
    // its coordinates from `globalThis.CloudeGlyphs` at call time, so a
    const context = {
        window: fakeWindow, document: fakeDocument, console,
        CloudeGlyphs: { glyphSvg },
    };
    context.globalThis = context;
    vm.createContext(context);
    installCloudeWeb(context);
    vm.runInContext(readClientJs('session-status-ui.js'), context);
    vm.runInContext(readClientJs('session-row-actions-confirm.js'), context);
    vm.runInContext(readClientJs('session-row-actions.js'), context);

    return {
        SessionRowActions: fakeWindow.SessionRowActions,
        SessionStatusUI: fakeWindow.SessionStatusUI,
        confirmCalls,
    };
}

const { SessionRowActions, SessionStatusUI, confirmCalls } = makeSandbox();

const RUNNING_STATUSES = [
    'question', 'working_subagent', 'working', 'finished_unread', 'idle',
    'running', 'unknown', undefined, null, 'nonsense',
];
const STOPPED_STATUSES = ['dead'];

test('running statuses get the close action; stopped get restart then remove', () => {
    for (const status of RUNNING_STATUSES) {
        assert.equal(
            SessionRowActions.actionFor(status),
            SessionRowActions.ACTION_CLOSE,
            `expected close for status ${String(status)}`
        );
    }
    for (const status of STOPPED_STATUSES) {
        assert.equal(SessionRowActions.actionFor(status), SessionRowActions.ACTION_RESTART);
        assert.ok(
            Array.from(SessionRowActions.actionsFor(status)).indexOf(
                SessionRowActions.ACTION_REMOVE
            ) !== -1,
            'remove must still be offered on a stopped row'
        );
    }
});

test('unknown is never treated as stopped', () => {
    assert.equal(SessionRowActions.actionFor('unknown'), SessionRowActions.ACTION_CLOSE);
});

test('the X and the trash are still never both on one row', () => {
    const running = SessionRowActions.html('working', 'cloude_api', 'running-session-kill');
    const stopped = SessionRowActions.html('dead', 'cloude_api', 'running-session-kill');
    const unread = SessionRowActions.html('unknown', 'cloude_api', 'running-session-kill');
    // could not be read
    assert.equal((running.match(/<button/g) || []).length, 2, 'running row lost a control');
    assert.equal((stopped.match(/<button/g) || []).length, 2, 'stopped row must offer restart + remove');
    assert.equal((unread.match(/<button/g) || []).length, 1, 'an unreadable row grew a control');

    const closeGlyph = SessionStatusUI.closeIconSvg();
    const trashGlyph = SessionStatusUI.trashIconSvg();
    const restartGlyph = SessionStatusUI.restartIconSvg();
    assert.ok(running.includes(closeGlyph), 'running row must draw the X');
    assert.ok(!running.includes(trashGlyph), 'running row must not draw the trash');
    assert.ok(running.includes(restartGlyph), 'running row lost its restart arrow');
    assert.ok(stopped.includes(trashGlyph), 'stopped row must draw the trash');
    assert.ok(stopped.includes(restartGlyph), 'stopped row must draw the restart arrow');
    assert.ok(!stopped.includes(closeGlyph), 'stopped row must not draw the X');
    assert.ok(!unread.includes(restartGlyph), 'an unreadable row was offered a restart');
});

test('every control has an aria-label (the original bug); only remove adds a hover title (#1686)', () => {
    let titled = 0;
    let untitled = 0;
    for (const status of ['working', 'dead']) {
        const markup = SessionRowActions.html(status, 'cloude_api', 'running-session-kill');
        for (const button of markup.split('</button>').filter((b) => b.includes('<button'))) {
            const title = /title="([^"]*)"/.exec(button);
            const aria = /aria-label="([^"]*)"/.exec(button);
            assert.ok(aria && aria[1], `missing aria-label for status ${status}`);
            if (aria[1] === 'remove from the list') {
                assert.ok(title && title[1] === aria[1], 'remove says the record is kept, so it keeps its tip');
                titled += 1;
            } else {
                assert.equal(title, null, `"${aria[1]}" names a self-evident glyph and draws no tip`);
                untitled += 1;
            }
        }
    }
    assert.ok(titled >= 1 && untitled >= 1, 'both kinds of control were checked');
});

test('both surfaces get identical wording for the same action', () => {
    const launcher = SessionRowActions.html('working', 'cloude_api', 'running-session-kill');
    const sidebar = SessionRowActions.html('working', 'cloude_api', 'session-sidebar-row-delete');
    const wording = (m) => /aria-label="([^"]*)"/.exec(m)[1];
    assert.equal(wording(launcher), wording(sidebar));
    assert.ok(launcher.includes(SessionRowActions.BASE_CLASS));
    assert.ok(sidebar.includes(SessionRowActions.BASE_CLASS));
});

test('the session name is escaped into the data attribute', () => {
    const markup = SessionRowActions.html('working', 'evil" onclick="x', 'running-session-kill');
    assert.ok(!markup.includes('onclick="'), 'attribute injection must not survive escaping');
    assert.ok(markup.includes('evil&quot; onclick=&quot;x'), 'quotes must be entity-escaped');
    assert.ok(!/<script/i.test(SessionRowActions.html('working', '<script>x</script>', 'c')));
});

test('the control is a real button, so it is keyboard operable', () => {
    const markup = SessionRowActions.html('working', 'cloude_api', 'running-session-kill');
    assert.ok(markup.startsWith('<button type="button"'));
    assert.ok(!markup.includes('role="button"'), 'a span pretending to be a button needs key handlers');
});

async function confirmCopyFor(action, sessionName) {
    confirmCalls.length = 0;
    const ok = await SessionRowActions.confirm(action, sessionName);
    assert.equal(confirmCalls.length, 1, 'must route through the ONE shared confirm modal');
    const [title, message, details] = confirmCalls[0];
    return { title, message, details, ok };
}

test('neither copy may claim disk is left untouched', async () => {
    for (const action of [SessionRowActions.ACTION_CLOSE, SessionRowActions.ACTION_REMOVE]) {
        const { details } = await confirmCopyFor(action, 'api-work');
        assert.ok(
            !/nothing (?:on disk is touched|is deleted)|no files are deleted|disk is untouched|leaves? (?:disk|files) (?:alone|untouched)/i.test(details),
            `${action}: copy must not claim disk is untouched`,
        );
        assert.ok(/deleted/.test(details), `${action}: must say files are deleted`);
        assert.ok(/uploads folder/.test(details), `${action}: must name the directory that is removed`);
    }
});

test('both copies state that the transcript survives', async () => {
    for (const action of [SessionRowActions.ACTION_CLOSE, SessionRowActions.ACTION_REMOVE]) {
        const { details } = await confirmCopyFor(action, 'api-work');
        assert.ok(
            /transcript is kept/.test(details),
            `${action}: must say the transcript is kept`,
        );
        assert.ok(/~\/\.claude\/projects/.test(details), `${action}: must say where it stays`);
    }
});

test('close and remove differ on whether a process is stopped', async () => {
    const close = await confirmCopyFor(SessionRowActions.ACTION_CLOSE, 'api-work');
    const remove = await confirmCopyFor(SessionRowActions.ACTION_REMOVE, 'old-thing');
    assert.equal(close.ok, true);
    assert.ok(/terminated/.test(close.details), 'closing does stop the process, say so');
    assert.ok(!/no running process is stopped/.test(close.details));
    assert.ok(
        /no running process is stopped|already exited/.test(remove.details),
        'a stopped session has no process to kill',
    );
    assert.ok(!/terminated/.test(remove.details));
    assert.notEqual(close.details, remove.details, 'the two paths are not interchangeable');
});

test('the confirm names the specific session and the action', async () => {
    const close = await confirmCopyFor(SessionRowActions.ACTION_CLOSE, 'api-work');
    assert.ok(close.message.includes('api-work'), 'the confirm must name the specific session');
    assert.ok(/close/.test(close.title));
    const remove = await confirmCopyFor(SessionRowActions.ACTION_REMOVE, 'old-thing');
    assert.ok(remove.message.includes('old-thing'), 'the confirm must name the specific session');
    assert.ok(/remove/.test(remove.title));
});

test('remove copy still reads exactly as written', async () => {
    const { details } = await confirmCopyFor(SessionRowActions.ACTION_REMOVE, 'old-thing');
    assert.equal(
        details,
        'this cannot be undone. this session already exited, so no running ' +
            "process is stopped, but the project's uploads folder is deleted " +
            'with every file in it, including files other sessions in that ' +
            'folder uploaded. the leftover tmux shell is ' +
            'cleared and carnivore forgets the entry. the transcript is kept ' +
            'and stays under ~/.claude/projects.',
    );
});

test('the close glyph matches the shared icon family', () => {
    const svg = SessionStatusUI.closeIconSvg();
    assert.ok(svg.includes('viewBox="0 0 16 16"'));
    assert.ok(svg.includes('fill="none"'));
    assert.ok(svg.includes('stroke="currentColor"'));
    assert.ok(svg.includes('stroke-width="1.5"'));
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

await runQueue();
console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
