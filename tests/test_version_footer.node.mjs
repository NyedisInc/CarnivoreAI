// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let failures = 0;
let passes = 0;
const queue = [];

/** Queue one named assertion block. Inputs: name, fn. Output: void. */
function test(name, fn) {
    queue.push([name, fn]);
}

/** Run every queued test in order. Inputs: none. Output: Promise<void>. */
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

function repoFile(...parts) {
    return fs.readFileSync(path.join(__dirname, '..', ...parts), 'utf8');
}

function fakeDocument(content) {
    let calls = 0;
    const meta = content === null ? null : {
        getAttribute: (k) => (k === 'content' ? content : null),
    };
    const document = {
        querySelector: (sel) => {
            calls++;
            return sel === 'meta[name="cloude-app-version"]' ? meta : null;
        },
    };
    return { document, queryCount: () => calls };
}

function loadModule(doc) {
    const context = { console, document: doc };
    vm.createContext(context);
    vm.runInContext(repoFile('client', 'js', 'version-footer.js'), context);
    return context.VersionFooter;
}


test('a resolved version renders as the shared span, unescaped content escaped', () => {
    const { document } = fakeDocument('v1.0.35');
    const VF = loadModule(document);
    assert.equal(
        VF.versionSpanHtml(),
        '<span class="version">v1.0.35</span>',
    );
});

test('an extra class joins onto the shared "version" class, never replaces it', () => {
    const { document } = fakeDocument('v1.0.35');
    const VF = loadModule(document);
    assert.equal(
        VF.versionSpanHtml('sidebar-thing'),
        '<span class="version sidebar-thing">v1.0.35</span>',
    );
});

test('the meta tag is read AT MOST ONCE, however many times the span is rendered', () => {
    const { document, queryCount } = fakeDocument('v1.0.35');
    const VF = loadModule(document);
    VF.versionSpanHtml();
    VF.versionSpanHtml();
    VF.readVersionText();
    assert.equal(queryCount(), 1, 'the DOM must be queried once and cached');
});

test('resetCache forces a fresh read - test-only escape hatch', () => {
    const { document, queryCount } = fakeDocument('v1.0.35');
    const VF = loadModule(document);
    VF.readVersionText();
    VF.resetCache();
    VF.readVersionText();
    assert.equal(queryCount(), 2);
});

test('a version string is HTML-escaped before interpolation', () => {
    const { document } = fakeDocument('v1.0.0"><script>x</script>');
    const VF = loadModule(document);
    const html = VF.versionSpanHtml();
    assert.ok(!html.includes('<script>'), html);
    assert.ok(html.includes('&lt;script&gt;'), html);
});


test('an EMPTY meta tag renders "version unknown", not a blank span', () => {
    const { document } = fakeDocument('');
    const VF = loadModule(document);
    assert.equal(
        VF.versionSpanHtml(),
        `<span class="version">${VF.UNKNOWN_TEXT}</span>`,
    );
    assert.notEqual(VF.UNKNOWN_TEXT, '', 'the fallback itself must not be blank');
});

test('a MISSING meta tag renders the same honest fallback as an empty one', () => {
    const { document } = fakeDocument(null);
    const VF = loadModule(document);
    assert.equal(VF.readVersionText(), '');
    assert.ok(VF.versionSpanHtml().includes(VF.UNKNOWN_TEXT));
});

test('a document that THROWS on read degrades to the fallback, never throws itself', () => {
    const throwingDoc = {
        querySelector: () => { throw new Error('DOM access blocked'); },
    };
    const VF = loadModule(throwingDoc);
    assert.doesNotThrow(() => VF.versionSpanHtml());
    assert.ok(VF.versionSpanHtml().includes(VF.UNKNOWN_TEXT));
});

test('the fallback text is lowercase, matching this app\'s UI voice', () => {
    const { document } = fakeDocument('');
    const VF = loadModule(document);
    assert.equal(VF.UNKNOWN_TEXT, VF.UNKNOWN_TEXT.toLowerCase());
});

test('the unresolved case is NEVER a stale-looking version-shaped string', () => {
    const { document } = fakeDocument('');
    const VF = loadModule(document);
    assert.ok(!/^v?\d/.test(VF.UNKNOWN_TEXT), 'fallback must not look like a version number');
});


test('sidebarFooterHtml wraps the SAME span the home bar renders', () => {
    const { document } = fakeDocument('v1.0.35');
    const VF = loadModule(document);
    const span = VF.versionSpanHtml();
    assert.ok(
        VF.sidebarFooterHtml().includes(span),
        'the sidebar footer must contain the exact span versionSpanHtml produces',
    );
    assert.ok(VF.sidebarFooterHtml().startsWith('<div class="version-footer">'));
});

test('the sidebar wrapper also carries the honest fallback', () => {
    const { document } = fakeDocument('');
    const VF = loadModule(document);
    assert.ok(VF.sidebarFooterHtml().includes(VF.UNKNOWN_TEXT));
});

test('THE SIDEBAR VERSION LINKS TO THE RELEASE NOTES', () => {
    const { document } = fakeDocument('v1.0.35');
    const VF = loadModule(document);
    const html = VF.sidebarFooterHtml();
    assert.ok(html.includes(`href="${VF.RELEASE_NOTES_URL}"`), html);
    assert.ok(html.includes('target="_blank"'), html);
    assert.ok(html.includes('rel="noopener noreferrer"'), html);
    assert.equal(VF.RELEASE_NOTES_URL,
        'https://github.com/NyedisInc/CarnivoreAI/releases',
        VF.RELEASE_NOTES_URL);
});

test('THE VERSION LABEL CARRIES NO TOOLTIP (#1209: the bar shows the short form)', () => {
    const long = '1.12.20-preview.130.g8578f81';
    const { document } = fakeDocument(long);
    const VF = loadModule(document);
    assert.ok(!VF.sidebarFooterHtml().includes('title='), VF.sidebarFooterHtml());
});

test('THE BAR SHOWS THE SHORT VERSION AND NEVER TRUNCATES IT', () => {
    const preview = loadModule(fakeDocument('1.12.20-preview.130.g8578f81').document);
    const html = preview.sidebarFooterHtml();
    assert.ok(html.includes('>v1.12.20<span class="version-footer__preview">preview</span></span>'), html);
    assert.ok(!html.includes('g8578f81</span>'), html);
    const shortRelease = preview.shortVersion('v1.12.21');
    assert.equal(shortRelease.text, 'v1.12.21');
    assert.equal(shortRelease.preview, false);
    const release = loadModule(fakeDocument('v1.12.21').document).sidebarFooterHtml();
    assert.ok(!release.includes('preview</span>'), release);
    const bar = repoFile('client', 'css', 'session-sidebar.css');
    const version = bar.match(/\.session-sidebar-bar__version\s*\{[^}]*\}/)[0];
    for (const rule of [/flex:\s*0 0 auto/, /margin-left:\s*auto/, /white-space:\s*nowrap/]) {
        assert.ok(rule.test(version), String(rule) + ' in ' + version);
    }
    assert.ok(!/max-width|text-overflow|overflow:\s*hidden/.test(version), version);
});

test('the link is the release LIST, never a per-version tag', () => {
    for (const content of ['v1.0.35', '1.0.35', 'v9.9.9']) {
        const VF = loadModule(fakeDocument(content).document);
        const html = VF.sidebarFooterHtml();
        assert.ok(html.includes(`href="${VF.RELEASE_NOTES_URL}"`), content);
        assert.ok(!html.includes('/releases/tag/'), content);
        assert.ok(!/href="[^"]*\d+\.\d+\.\d+/.test(html),
            `the href must carry no version at all: ${html}`);
    }
});

test('AN UNRESOLVED VERSION IS NOT A LINK AT ALL', () => {
    for (const content of ['', null]) {
        const VF = loadModule(fakeDocument(content).document);
        const html = VF.sidebarFooterHtml();
        assert.ok(!html.includes('<a '), html);
        assert.ok(!html.includes('href'), html);
        assert.ok(html.includes(VF.UNKNOWN_TEXT), html);
    }
});

test('THE HOME BAR IS NOT A LINK - versionSpanHtml is untouched', () => {
    const VF = loadModule(fakeDocument('v1.0.35').document);
    assert.equal(VF.versionSpanHtml(), '<span class="version">v1.0.35</span>');
    assert.ok(!VF.versionSpanHtml().includes('<a '));
});

test('THE FOOTER ORDER IS THE BOX, THEN THE BAR', () => {
    const html = repoFile('client', 'index.html');
    const listIdx = html.indexOf('id="session-sidebar-list"');
    const slotIdx = html.indexOf('id="session-sidebar-bar-slot"');
    assert.ok(listIdx > -1, 'expected #session-sidebar-list in client/index.html');
    assert.ok(slotIdx > -1, 'expected #session-sidebar-bar-slot in client/index.html');
    assert.ok(listIdx < slotIdx,
        `the readout is this session's and must sit above the app bar: `
        + `list@${listIdx} slot@${slotIdx}`);

    const plan = repoFile('web', 'src', 'lib', 'sidebar-shell', 'plan.ts');
    assert.ok(!/status-legend|lights mean/i.test(plan),
        'the status-light key was removed; its slot must not linger');
});


test('THE BAR CALLS THE SHARED COMPONENT, AND THE FOOTER DOES NOT', () => {
    const bar = repoFile('web', 'src', 'lib', 'drawer', 'bar.ts');
    assert.ok(
        bar.includes('footer.readVersionText()') && bar.includes('footer.shortVersion('),
        'the bar must render its version through VersionFooter, not build one itself',
    );
    const plan = repoFile('web', 'src', 'lib', 'sidebar-shell', 'plan.ts');
    assert.ok(
        !plan.includes('barHtml') && !plan.includes('bar-slot'),
        'the list paint must not render the bottom bar; it has its own slot now',
    );
    const paint = repoFile('web', 'src', 'lib', 'drawer', 'paint.ts');
    assert.ok(
        paint.includes('bar.paint()'),
        'and the list repaint must actually paint the bar into its slot',
    );
});

test('BOTH FILES ARE SERVED, IN AN ORDER THAT WORKS', () => {
    const html = repoFile('client', 'index.html');
    assert.ok(html.includes('/static/js/version-footer.js'), 'the module is served');
    assert.ok(html.includes('/static/css/version-footer.css'), 'and so is its CSS');
    const scriptIdx = html.indexOf('<script src="/static/js/version-footer.js"></script>');
    const launchpadIdx = html.indexOf('<script type="module" src="/static/dist/app.js"></script>');
    assert.ok(scriptIdx > -1 && launchpadIdx > -1);
    assert.ok(scriptIdx < launchpadIdx, 'version-footer.js must load before the bundle');
});

test('THE VERSION TEXT IS SELECTABLE - no user-select: none anywhere in its CSS', () => {
    const css = repoFile('client', 'css', 'version-footer.css');
    assert.ok(!/user-select\s*:\s*none/i.test(css), css);
});

test('THE VERSION LINE IS A PLAIN ANCHOR - no role, no tabindex, no click wiring', () => {
    const js = repoFile('client', 'js', 'version-footer.js');
    assert.ok(!/role=["']button["']/.test(js), js);
    assert.ok(!/\btabindex\s*=/i.test(js), js);
    assert.ok(!/\.tabIndex\s*=/.test(js), js);
    assert.ok(!/addEventListener/.test(js), js);
});

test('the muted colour comes from a CSS custom property, never a hard-coded value', () => {
    const styles = repoFile('client', 'css', 'styles.css');
    const versionRule = styles.match(/^\.version \{[^}]*\}/m);
    assert.ok(versionRule, 'expected a .version rule in styles.css');
    assert.ok(/color:\s*var\(--color-fg-faint\)/.test(versionRule[0]), versionRule[0]);
    const footerCss = repoFile('client', 'css', 'version-footer.css');
    assert.ok(!/color:\s*#[0-9a-f]{3,8}/i.test(footerCss), 'no hard-coded colour in version-footer.css');
});

test('no rule draws a line above the version in the drawer bar', () => {
    const files = [
        ['client', 'css', 'version-footer.css'],
        ['client', 'css', 'session-sidebar.css'],
    ];
    let seen = 0;
    for (const f of files) {
        const css = repoFile(...f);
        for (const m of css.matchAll(/([^{}]*)\{([^}]*)\}/g)) {
            const selector = m[1].replace(/\/\*[\s\S]*?\*\//g, '').trim();
            if (!/version/.test(selector)) continue;
            seen += 1;
            assert.ok(!/border(-top)?\s*:/.test(m[2]), `${f[2]}: ${selector} draws a border`);
        }
    }
    assert.ok(seen >= 3, `expected the version rules to be found, saw ${seen}`);
});

test('nothing here uses an em-dash, an en-dash, or an emoji', () => {
    for (const f of [['js', 'version-footer.js'], ['css', 'version-footer.css']]) {
        const src = repoFile('client', ...f);
        assert.ok(!/[—–]/.test(src), `${f[1]} carries a dash`);
        assert.ok(
            !/[\u{1F300}-\u{1FAFF}\u{2700}-\u{27BF}]/u.test(src),
            `${f[1]} carries an emoji`,
        );
    }
});

await runQueue();
console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
