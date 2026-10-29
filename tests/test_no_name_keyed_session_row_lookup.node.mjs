
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

let failures = 0;
let passes = 0;

/**
 * Run one named assertion block, recording pass/fail rather than throwing.
 * @param {string} name  Test description.
 * @param {() => void} fn  Body; throwing marks the test failed.
 * @returns {void}
 */
function test(name, fn) {
    try {
        fn();
        passes++;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures++;
        console.error(`NOT OK - ${name}`);
        console.error(`  ${err && err.message ? err.message : err}`);
    }
}

const NAME_KEYED_FIND = /\.find(?:Index)?\(\s*\(?[\w$]*\)?\s*=>[^;]*?(?:\.name|tmux_name|tmuxName|tmux_session)\s*===\s*[\w$]+/;

function clientJsFiles() {
    const out = [];
    const walk = (dir, exts) => {
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            if (entry.name === 'node_modules' || entry.name === 'vendor'
                || entry.name === 'dist' || entry.name === 'widget-harness-build'
                || entry.name.startsWith('.')) continue;
            const full = path.join(dir, entry.name);
            if (entry.isDirectory()) walk(full, exts);
            else if (exts.some((e) => entry.name.endsWith(e))) out.push(full);
        }
    };
    walk(path.join(ROOT, 'client'), ['.js']);
    walk(path.join(ROOT, 'web', 'src'), ['.ts', '.svelte']);
    return out;
}

function stripJsComments(text) {
    return text
        .replace(/\/\*[\s\S]*?\*\//g, (m) => '\n'.repeat((m.match(/\n/g) || []).length))
        .replace(/^\s*\/\/.*$/gm, '');
}

function findHits(root) {
    const files = root
        ? (() => {
            const out = [];
            const walk = (dir) => {
                for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
                    const full = path.join(dir, entry.name);
                    if (entry.isDirectory()) walk(full);
                    else if (entry.name.endsWith('.js')) out.push(full);
                }
            };
            walk(root);
            return out;
        })()
        : clientJsFiles();

    const hits = [];
    for (const file of files) {
        const code = stripJsComments(fs.readFileSync(file, 'utf8'));
        const relFile = path.relative(ROOT, file);
        code.split('\n').forEach((line, i) => {
            const m = line.match(NAME_KEYED_FIND);
            if (m) {
                const snippet = m[0].replace(/\s+/g, ' ').trim();
                hits.push({
                    file: relFile,
                    line: i + 1,
                    snippet,
                    key: `${relFile}::${snippet}`,
                });
            }
        });
    }
    return hits;
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
const ALLOWED_MATCHES = {
    'web/src/lib/skills-page/SkillsScreen.svelte::.find((row) => row.name === name':
        'NOT A SESSION LOOKUP: matches a skill census row by the skill\'s own name.',
    'web/src/cplugs/devwidgetlab/lab-selection.ts::.find((one) => one.name === size':
        "NOT A SESSION LOOKUP: matches a Widget Lab size, widget or host by its own configuration name or key (dev widget lab).",
    'web/src/cplugs/devwidgetlab/lab-selection.ts::.find((size) => size.name === sel':
        "NOT A SESSION LOOKUP: matches a Widget Lab size, widget or host by its own configuration name or key (dev widget lab).",
    'web/src/cplugs/devwidgetlab/lab-selection.ts::.find((one) => one.key === sel.widget)?.hosts.find((host) => host.zone === intent.host)?.sizes.some((size) => size.name === intent':
        "NOT A SESSION LOOKUP: matches a Widget Lab size, widget or host by its own configuration name or key (dev widget lab).",
    "web/src/lib/drawer/last-view.ts::.find((r) => !r.asleep && r.status !== 'dead' && r.status !== 'closed' && (view.sessionId ? r.session_id === view.sessionId : r.name === view":
        "KNOWN, FALLBACK ONLY: the stored last view matches by session_id whenever it has one; the name is used only for a record saved without an id, and the match is among live, not-dead, not-closed rows.",
    'web/src/lib/sessions-page/PivotView.svelte::.find((c) => c.name === name':
        "NOT A SESSION LOOKUP: matches a company chip by the company's own name.",
    'web/src/lib/settings-page/mcp-panel/McpToolSwitchesPanel.test.ts::.find((x) => x.name === name':
        "NOT A SESSION LOOKUP: matches an MCP tool switch by the tool's own name (test helper).",
    'web/src/lib/sidebar-shell/row-middle-click.test.ts::.find((r) => r.name === name':
        "NOT A SESSION LOOKUP: test helper finding its own fixture row by the fixture's name.",
    'web/src/lib/sidebar-shell/row-middle-click.ts::.find((r) => r.name === name':
        "KNOWN, FALLBACK ONLY: the row element's session uuid is matched first; the tmux name is used only for an element drawn without a uuid, and the hit only decides which middle-click action applies.",
    'web/src/lib/skill-page/SkillPage.svelte::.find((g) => g.name === item':
        "NOT A SESSION LOOKUP: matches a skill group by the skill's own name.",
    'web/src/lib/skills-page/SkillDetailPane.svelte::.find((g) => g.name === item':
        "NOT A SESSION LOOKUP: matches a skill group by the skill's own name.",
    'web/src/lib/skills-page/skill-actions.svelte.ts::.find((g) => g.name === item':
        "NOT A SESSION LOOKUP: matches a skill group by the skill's own name.",
    'web/src/cplugs/huddle/style-guide/ExpressionBoard.svelte::.findIndex((x) => x.name === current':
        'NOT A SESSION LOOKUP: matches a Swarm character eye expression by its own name (style guide specimen).',
    'web/src/cplugs/huddle/style-guide/ExpressionBoard.svelte::.find((e) => e.name === cell':
        'NOT A SESSION LOOKUP: matches a Swarm character eye expression by its own name (style guide specimen).',
    'web/src/lib/widgets-page/preview-sizes.ts::.find((one) => one.name === name':
        'NOT A SESSION LOOKUP: matches a widget preview size by its configuration name.',
    'web/src/lib/widgets-page/WidgetHero.svelte::.find((one) => one.name === size':
        'NOT A SESSION LOOKUP: matches a widget preview size by its configuration name.',
    'web/src/lib/widgets-page/WidgetPane.svelte::.find((one) => one.name === size':
        'NOT A SESSION LOOKUP: matches a widget preview size by its configuration name.',
    'web/src/lib/widgets-page/WidgetTilePreview.svelte::.find((one) => one.name === name':
        'NOT A SESSION LOOKUP: matches a widget preview size by its configuration name.',
    'web/src/lib/drawer-tabs/DrawerSearch.svelte::.find((el) => el.dataset.name === target':
        'KNOWN, BAND-LOCAL: the search cursor and the AGENTS band under it are built from the one searchD.agentNames list, so the name picks a row inside that band only (data-band is matched too); the hit only clicks that row, as the pointer would.',
    'web/src/lib/item-menu/menus/row.ts::.find((r) => (uuid && (r.session_uuid === uuid || r.session?.session_uuid === uuid)) || (r.tmux_session && r.tmux_session === tmuxName':
        'KNOWN, DISPLAY ONLY: the row matches on the durable uuid OR the tmux name (the name covers a menu opened without a uuid), and the hit only words the project in the send-to menu and never routes or mutates by it.',
    'web/src/lib/bookmarks/BookmarkButtons.svelte::.find((info) => info.tmux_session === sessionName':
        'KNOWN: the button\'s prop is the tmux name; the hit only fetches the row\'s session_row_id and every bookmark call after it is keyed on that id.',
    'web/src/lib/bookmarks/row-actions.ts::.find((s) => s.tmux_session === tmuxName':
        'KNOWN: a menu action hands over the tmux name; the hit only fetches the row\'s session_row_id and label, and the bookmark popup is then keyed on that id.',
    'web/src/lib/auto-sleep/KeepAwakeIcon.svelte::.find((row) => row.tmux_session === sessionName':
        'KNOWN, DISPLAY ONLY: the icon\'s prop is the tmux name; the hit only words why a live session is held awake and never routes or mutates by it.',
    'web/src/opscenter/engine/tab-drag.ts::.find((r) => r.asleep && r.tmux_name === start':
        'KNOWN: the drawer drag start carries only the row name; the match is among ASLEEP records only (a live row is never matched) and the drop re-resolves by record id.',
    'web/src/opscenter/cells/terminal-live/toolbar.ts::.findIndex((s) => s.name === item':
        'NOT A SESSION LOOKUP: matches a static toolbar width step by its configuration name.',
    'web/src/lib/launchpad/navigation.ts::.find((row) => row.name === tmuxName': [
        'KNOWN BUG, MOVED NOT INTRODUCED. Slice 7 of the svelte migration',
        'ported this from `_handleAttachRunningSession`, where it stood as',
        '`.find(r => r.name === tmuxName)`. It resolves the LISTING ROW',
        'whose label the adopt response does not carry, and `tmuxName` is',
        'the only handle the adopt was made with - the attach came from a',
        'row click or a deep link, neither of which has a durable key for',
        'a session this app has not adopted yet. Listed rather than fixed',
        'because a MOVE that also changes behaviour is a regression nobody',
        'can bisect. The blast radius is small and named: the worst case',
        'is a recreated pane reusing a name and the tab opening with the',
        'previous session of that name`s label, on a session whose label',
        'the server did not send. The fix is the same one the entry below',
        'needs - a durable key on the live row that the attachable row',
        'also carries.',
    ].join(' '),
    'web/src/opscenter/engine/tab-drag.ts::.find((row) => row.tmux_session === start': [
        'KNOWN, UNFIXED HERE, RECORDED AS A FOLLOW-UP (parity merge,',
        '2026-09-25, .claude/notes/parity-merge-20260924.md). Terminal tabs',
        'slice 4 (#455) resolves the dragged DRAWER row to a session id by',
        'its tmux name, because the drawer drag hands over only `name`. The',
        'lookup is made once, at drag start, against the LIVE listing, where',
        'a tmux name names one live session, and the tab it builds is keyed',
        "on that session's database row (issue #612, `terminal:row:<id>`),",
        'so a wake, recreate or reopen does not strand it. The residual risk',
        'is a name reused between the drawer paint and the drag. The fix is',
        'for the drawer drag to carry the session id or its row id.',
    ].join(' '),
    'web/src/lib/drawer-tabs/DrawerQuestions.svelte::.find((r) => r.tmux_session === item': [
        'FALLBACK AFTER THE DURABLE KEY. The question row is matched on its',
        'session id first; the tmux name is tried only when the id finds no',
        'row, and only to read that row`s pinned theme for painting the',
        'question. A reused name at worst tints one question with the',
        'previous session`s theme. Recorded, not fixed here.',
    ].join(' '),
    'web/src/lib/sidebar-shell/row-plan.ts::.findIndex((o) => o.name === m': [
        'NOT A ROW LOOKUP: de-duplicates the members of ONE Layout body by',
        'name before drawing, because Svelte`s keyed list refuses a repeated',
        'key. It resolves no session and reads no other listing.',
    ].join(' '),
    'web/src/opscenter/cells/terminal-group/tab-controller.svelte.ts::.find((row) => row.tmux_session === tmux': [
        'FALLBACK, RECORDED. After a wake or re-adopt mints another id for the',
        'same pane, the tab joins on the primary pane`s tmux name (which both',
        'ids carry) so its title is not the raw id. Used only for the title;',
        'the tab itself stays keyed on the database row (#612).',
    ].join(' '),
    'web/src/opscenter/layouts/names.ts::.find((row) => row.tmux_session === tmux': [
        'FALLBACK AFTER THE DURABLE KEY. `rowIdForSession(primarySessionId())`',
        'runs first; the primary pane`s tmux name is read only when the id',
        'does not resolve (a re-adopt minted another), to find the row id.',
    ].join(' '),
    'web/src/widget-harness/main.ts::.find((one) => one.name === request': [
        'NOT A SESSION IDENTITY: the widget harness resolves a widget by its',
        'registry name from a developer`s show() request.',
    ].join(' '),
    'web/src/opscenter/lib/states.ts::.find((step) => step.name === previous': [
        'NOT A SESSION IDENTITY: the previous layout state step, by its own',
        'compile-time label, used to keep hysteresis from flickering a',
        'column on and off around a threshold.',
    ].join(' '),
    'web/src/opscenter/lib/states.ts::.find((step) => step.name === chosen': [
        'NOT A SESSION IDENTITY: the chosen layout state step, by its own',
        'compile-time label, read back to compare its threshold against the',
        'previous one.',
    ].join(' '),
    'web/src/opscenter/lib/states.ts::.findIndex((step) => step.name === current': [
        'NOT A SESSION IDENTITY: the current layout state step is found by',
        'its compile-time label so `atLeast` can compare two steps by their',
        'position in the ladder.',
    ].join(' '),
    'web/src/opscenter/lib/states.ts::.findIndex((step) => step.name === name': [
        'NOT A SESSION IDENTITY: the same ladder position lookup for the',
        'step being asked about.',
    ].join(' '),
    'web/src/lib/sessions/running.ts::.find((s) => s.name === tmuxName': [
        'KNOWN BUG, MOVED NOT INTRODUCED. This is the same lookup that',
        'stood in launchpad.js as `.find(s => s.name === tmuxName)`,',
        'ported line by line by slice 3 of the svelte migration. It is',
        'listed here rather than fixed because slice 3 is a MOVE: fixing',
        'a behaviour while relocating it makes a regression impossible to',
        'bisect. The fix needs the server to ship a durable key on the',
        'live row that the attachable row also carries, which is its own',
        'change.',
    ].join(' '),
    // there is nothing
    // there is nothing
    'web/src/lib/drawer/fetch.ts::.find((r) => r.name === tmuxName': [
        'KNOWN BUG, unfixed by this guard. This is mergeLiveRow(), and',
        'its own module docstring names this exact function as the',
        '"home screen joined live sessions to stored rows by name" bug',
        "from this task's background - it writes session_id, status,",
        'unread and created_by_cloude onto whatever row matches the',
        "name. This file is not in this task's do-not-touch list, but",
        "this task's constraints forbid fixing any flagged site - guard",
        'only.',
    ].join(' '),
    'web/src/lib/sidebar-shell/group-assign.ts::.find((g) => g.name === String': [
        'NOT a session identity lookup: matches a GROUP by its user-given',
        'name right after creating it, to read back the server-assigned',
        "uuid. Groups are named entities in this app's data model, not",
        'sessions.',
    ].join(' '),
    'web/src/opscenter/api/activity.svelte.ts::.find((r) => r.tmux_session === key': [
        'NOT UNANCHORED: the tmux-name comparison is the FIRST half of an',
        'OR whose SECOND half, `r.session.id === key`, already matches on',
        "the row's durable id. `key` is a socket/toast frame's `handle`,",
        'which can itself be either a bare tmux name or a session id -',
        'the tmux-name arm only ever fires for the tmux-name shape of',
        "`key`, and a stale/reused name can at worst pick the WRONG row's",
        'label for a display-only feed line (issue #591). No status,',
        'unread or identity field is read or written off this match, so',
        "the residual risk is cosmetic, not a stranded-identity bug.",
    ].join(' '),
    'web/src/lib/skills-page/skill-state.ts::.find((s) => s.name === group': [
        'NOT A SESSION IDENTITY: a skill group`s fire count from the health',
        'census, joined on the skill group`s own name.',
    ].join(' '),
    'web/src/lib/skills-page/skills-adapter.ts::.find((g) => g.name === id': [
        'NOT A SESSION IDENTITY: a skill group in the last inventory, by its',
        'own name.',
    ].join(' '),
};

// reader.

test('the client JS scanner finds files to scan', () => {
    assert.ok(clientJsFiles().length > 0,
        'no client .js files found - the scan is vacuous');
});

test('the guard can actually fail (positive control)', () => {
    const tmpDir = fs.mkdtempSync(path.join(ROOT, '.tmp_js_guard_proof_'));
    try {
        fs.writeFileSync(
            path.join(tmpDir, 'planted.js'),
            "function mergeLiveRow(rows, info) {\n"
            + "    const tmuxName = info && info.tmux_session;\n"
            + "    const existing = rows.find((r) => r.name === tmuxName);\n"
            + "    if (existing) existing.status = info.activity_status;\n"
            + "}\n",
        );
        const hits = findHits(tmpDir);
        assert.equal(hits.length, 1,
            `expected exactly one planted hit, scanner found ${hits.length}`);
        assert.match(hits[0].snippet, /\.find\(/);
    } finally {
        fs.rmSync(tmpDir, { recursive: true, force: true });
    }
});

test('a plain equality unrelated to session rows is not flagged (negative control)', () => {
    const tmpDir = fs.mkdtempSync(path.join(ROOT, '.tmp_js_guard_proof_'));
    try {
        fs.writeFileSync(
            path.join(tmpDir, 'safe.js'),
            "function findByColor(items, color) {\n"
            + "    return items.find((x) => x.color === color);\n"
            + "}\n",
        );
        const hits = findHits(tmpDir);
        assert.deepEqual(hits, []);
    } finally {
        fs.rmSync(tmpDir, { recursive: true, force: true });
    }
});

test('every name-keyed session-row find/findIndex in client/js is a registered, reasoned exemption', () => {
    const hits = findHits();
    const unregistered = hits.filter((h) => !(h.key in ALLOWED_MATCHES));
    assert.deepEqual(unregistered.map((h) => `${h.file}:${h.line}  ${h.snippet}`), [],
        'new (or newly regressed) session-row lookup(s) keyed on a tmux '
        + 'name via .find()/.findIndex() - a tmux name is reused whenever a '
        + 'session is recreated after its pane dies, so matching "the row '
        + 'whose name equals this one" is a guess about identity, not a '
        + 'fact. Resolve the row through something durable instead (the '
        + 'session id the server already sends, or session_uuid), or if '
        + 'this hit is genuinely NOT a session lookup (a project, a group, '
        + 'a DOM node), add it to ALLOWED_MATCHES in this file with a '
        + 'one-line reason:\n  '
        + unregistered.map((h) => `${h.file}:${h.line}  ${h.snippet}`).join('\n  '));

    const foundKeys = new Set(hits.map((h) => h.key));
    const stale = Object.keys(ALLOWED_MATCHES).filter((k) => !foundKeys.has(k));
    assert.deepEqual(stale, [],
        'ALLOWED_MATCHES entry registered for a match this scan no longer '
        + 'finds - the code was fixed, rewritten, or removed, and the '
        + 'entry is now dead weight that will mislead the next reader:\n  '
        + stale.join('\n  '));
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
