
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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
        console.error(err && err.stack ? err.stack : err);
    }
}

function css(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'css', name), 'utf8');
}

function js(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'js', name), 'utf8');
}

function stripCssComments(sheet) {
    return sheet.replace(/\/\*[\s\S]*?\*\//g, '');
}

const html = fs.readFileSync(path.join(__dirname, '..', 'client', 'index.html'), 'utf8');
// The screen-entry steps moved out of app.js into app-screen-entry.js.
const appJs = js('app.js') + js('app-screen-entry.js');
const tools = stripCssComments(css('terminal-tools.css'));
const styles = stripCssComments(css('styles.css'));
const iosChrome = stripCssComments(css('ios-chrome.css'));
const configDrawer = stripCssComments(css('config-drawer.css'));
const terminalGrid = stripCssComments(css('terminal-grid.css'));


test('#status-rail no longer exists anywhere in the client', () => {
    assert.doesNotMatch(html, /status-rail/, 'index.html still names the retired rail');
    assert.doesNotMatch(tools, /status-rail/, 'terminal-tools.css still has rail rules');
    assert.doesNotMatch(iosChrome, /status-rail/, 'ios-chrome.css still has rail rules');
    assert.doesNotMatch(configDrawer, /status-rail/, 'config-drawer.css still has rail rules');
    assert.doesNotMatch(appJs, /status-rail/, 'app.js still targets the rail by id');
});


test('exactly one #statusText node exists in the whole client', () => {
    const inHtml = (html.match(/id="statusText"/g) || []).length;
    assert.equal(inHtml, 1, 'the light is moved between screens, never cloned');
    const jsDir = path.join(__dirname, '..', 'client', 'js');
    for (const name of fs.readdirSync(jsDir)) {
        if (!name.endsWith('.js')) continue;
        const src = fs.readFileSync(path.join(jsDir, name), 'utf8');
        assert.doesNotMatch(
            src, /id="statusText"/,
            `${name} renders a second copy - both writers address it by id`);
    }
});

test('#statusText is not inside .header .controls', () => {
    const controlsStart = html.indexOf('<div class="controls">');
    assert.ok(controlsStart !== -1, 'expected the header controls row');
    const terminalScreenAt = html.indexOf('<div id="terminal-screen"');
    assert.ok(terminalScreenAt !== -1, 'expected the terminal screen element');
    assert.ok(terminalScreenAt > controlsStart, 'the terminal screen must be declared after the header');
    const statusAt = html.indexOf('id="statusText"');
    assert.ok(statusAt > terminalScreenAt,
        'the light must be declared well after the header, not inside the controls row');
});

test('#statusText starts inside a hidden wrapper, so nothing paints it before app.js boots', () => {
    const m = html.match(/<div hidden>\s*<span class="status" id="statusText"[^>]*><\/span>\s*<\/div>/);
    assert.ok(m, '#statusText must start as the only child of a <div hidden>');
    const tag = html.match(/<span class="status" id="statusText"[^>]*>/);
    assert.doesNotMatch(tag[0], /\shidden[\s>=]/,
        'hidden on the span itself is overridden by .status display and would paint anyway');
});

test('#statusText stays focusable so a tap can reveal its text', () => {
    const tag = html.match(/<span class="status" id="statusText"[^>]*>/);
    assert.ok(tag, 'expected the status span');
    assert.match(tag[0], /tabindex="0"/, 'hover does not exist on a phone');
    assert.match(tag[0], /role="status"/, 'it announces live state');
});


test('_placeStatusLight targets no bar - #home-bar-status and #archive-bar-status are dead', () => {
    const start = appJs.indexOf('_placeStatusLight(screen) {');
    assert.ok(start !== -1, 'the function must exist');
    const body = appJs.slice(start, appJs.indexOf('\n    }', start));
    assert.doesNotMatch(
        body, /getElementById\('home-bar-status'\)/,
        '#home-bar-status went with HomeScreen.svelte in the opscenter pivot - ' +
        'reaching for it finds nothing and must not be mistaken for a real placement');
    assert.doesNotMatch(body, /getElementById\('archive-bar-status'\)/, 'the archive screen is deleted');
    assert.doesNotMatch(
        body, /getElementById\('terminal-bar-status'\)/,
        '.info is deleted - there is no terminal bar target to reach for any more');
    assert.doesNotMatch(
        body, /\.header \.controls/,
        'the header is not a home for the light any more');
    assert.doesNotMatch(
        body, /getElementById\('terminal-status-bar'\)/,
        'the old floating-chip container id must not come back');
});

test('_placeStatusLight detaches the node instead of leaving it wherever it last was', () => {
    const start = appJs.indexOf('_placeStatusLight(screen) {');
    assert.ok(start !== -1, 'the function must exist');
    const body = appJs.slice(start, appJs.indexOf('\n    }', start));
    assert.match(
        body, /parentNode\.removeChild\(el\)/,
        'no target must detach the node (parentNode.removeChild), not merely return');
});

test('all three screens still place the light, even where it is now a deliberate detach', () => {
    for (const screen of ['auth', 'launchpad', 'terminal']) {
        assert.match(
            appJs,
            new RegExp(`_placeStatusLight\\('${screen}'\\)`),
            `${screen} must place the light - an unplaced node is a stale one`);
    }
});

test('no status label sync is left behind - every bar that showed one is gone', () => {
    assert.doesNotMatch(appJs, /_syncStatusLabel|_observeStatusText/);
    assert.doesNotMatch(appJs, /(?:home|archive|terminal)-bar-status-text/);
});


test('.info has no CSS rule any more, in any stylesheet that used to carry one', () => {
    for (const [name, sheet] of [
        ['styles.css', styles],
        ['terminal-grid.css', terminalGrid],
    ]) {
        assert.doesNotMatch(sheet, /(?:^|\n)\s*\.info\s*\{/, `${name} still declares .info`);
        assert.doesNotMatch(sheet, /\.info\s+\./, `${name} still styles a control inside .info`);
    }
});

test('#sessionInfo, #terminal-bar-status and the terminal-bar__* classes are gone from every stylesheet', () => {
    for (const [name, sheet] of [['styles.css', styles], ['terminal-tools.css', tools]]) {
        assert.doesNotMatch(sheet, /#sessionInfo/, `${name} still styles #sessionInfo`);
        assert.doesNotMatch(sheet, /#terminal-bar-status/, `${name} still styles #terminal-bar-status`);
        assert.doesNotMatch(sheet, /\.terminal-bar__/, `${name} still styles a .terminal-bar__ class`);
    }
});

test('--terminal-bar-height is gone - nothing is reserving space for a bar that does not exist', () => {
    assert.doesNotMatch(styles, /--terminal-bar-height/, 'the token must not linger unread');
});

test('.info, #sessionInfo and the terminal-bar-status group are gone from index.html', () => {
    assert.doesNotMatch(html, /class="info"/, 'the bar container must not come back');
    assert.doesNotMatch(html, /id="sessionInfo"/, 'the session id/PID readout must not come back');
    assert.doesNotMatch(html, /id="terminal-bar-status"/, 'the status group container must not come back');
    assert.doesNotMatch(html, /id="terminal-mobile-title"/, 'the mobile title mirror must not come back');
    assert.doesNotMatch(html, /id="terminal-background-control"/,
        'the legacy background-control mount point must not come back');
});

test('the .info hiding rule in terminal-grid.css is gone - the element it targeted no longer exists', () => {
    assert.doesNotMatch(
        terminalGrid, /:has\(#terminal-grid > \.oc-surface\) > \.info/,
        'a rule that hides a deleted element is dead weight, not a harmless leftover');
});

test('the terminal.js sessionInfoEl property is gone, not merely null-guarded', () => {
    const terminalJs = js('terminal.js');
    assert.doesNotMatch(terminalJs, /sessionInfoEl/,
        'writing to a null element throws; the property and its four writers must be fully removed');
});

test('terminal-metrics.js no longer measures .info', () => {
    const metrics = js('terminal-metrics.js');
    assert.doesNotMatch(metrics, /querySelector\('\.info'\)/, 'describeBoxHeights must not read a deleted element');
    assert.doesNotMatch(metrics, /info=\$\{info\}/, 'describeBoxHeights must not carry a phantom info= reading');
});

test('the diagnostic bottom-bar watch is gone from terminal-layout.js', () => {
    const layout = js('terminal-layout.js');
    assert.doesNotMatch(layout, /watchBottomBar/, 'a watch over a deleted element is dead code');
    assert.doesNotMatch(layout, /TERM-BAR/, 'its log tag must not linger either');
});

test('the old floating terminal-status-bar chip rules are still gone', () => {
    assert.doesNotMatch(tools, /\.terminal-status-bar\s*\{/, 'the floating chip container rule must not come back');
    assert.doesNotMatch(html, /class="terminal-status-bar"/, 'the floating chip element must not come back');
});


test('the docked config drawer (right side) does not reference the terminal bar', () => {
    assert.doesNotMatch(
        configDrawer, /\.terminal-status-bar|\.info\b/,
        'no chip selector and no bar selector - neither exists any more');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
