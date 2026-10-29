
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.join(__dirname, '..');
const CLIENT_JS = path.join(REPO, 'client', 'js');
const THEMES_DIR = path.join(REPO, 'client', 'css', 'themes');

const opacitySrc = fs.readFileSync(path.join(CLIENT_JS, 'terminal-background-opacity.js'), 'utf8');
const backgroundSrc = fs.readFileSync(path.join(CLIENT_JS, 'terminal-background.js'), 'utf8');
const contrastSrc = fs.readFileSync(path.join(CLIENT_JS, 'terminal-background-contrast.js'), 'utf8');
const manifestSrc = fs.readFileSync(path.join(CLIENT_JS, 'terminal-background-manifest.js'), 'utf8');
const backgroundCss = fs.readFileSync(
    path.join(REPO, 'client', 'css', 'terminal-background.css'), 'utf8');

let failures = 0;
let passes = 0;

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

function makeSandbox(themes, overrides) {
    const rootDataset = {};
    const fakeDocument = {
        documentElement: { dataset: rootDataset },
        querySelector() { return null; },
        getElementById() { return null; },
        addEventListener() {},
        dispatchEvent() { return true; },
    };
    const sandbox = {
        console,
        document: fakeDocument,
        MutationObserver: function () {
            return { observe() {}, disconnect() {} };
        },
        CustomEvent: function (type, init) {
            this.type = type;
            this.detail = init && init.detail;
        },
        Math, JSON, isFinite, parseFloat, String, Object, Promise, Error,
        encodeURIComponent,
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    if (themes) sandbox.Themes = themes;
    const context = vm.createContext(sandbox);
    vm.runInContext(opacitySrc, context, { filename: 'terminal-background-opacity.js' });
    vm.runInContext(contrastSrc, context, { filename: 'terminal-background-contrast.js' });
    vm.runInContext(manifestSrc, context, { filename: 'terminal-background-manifest.js' });
    vm.runInContext(backgroundSrc, context, { filename: 'terminal-background.js' });

    const bg = sandbox.TerminalBackground;
    const opacity = sandbox.TerminalBackgroundOpacity;
    Object.assign(bg.getOverrides(), overrides || {});

    function addSurface(name, pinnedThemeId) {
        const host = { style: { backgroundImage: '' }, dataset: {} };
        const term = { options: { theme: null } };
        const handle = opacity.attach(term);
        const client = {
            _containerEl() { return host; },
            _currentTmuxName() { return this._session; },
            _session: name || null,
            _xtermOpacity: handle,
        };
        handle.apply({ background: '#1e1e1e', foreground: '#ffffff' });
        bg.registerSurface(client);
        if (pinnedThemeId !== undefined) bg.setSurfaceTheme(client, pinnedThemeId || null);
        return {
            client,
            host,
            term,
            get image() { return host.style.backgroundImage; },
            get flagged() { return host.dataset.terminalBg; },
            get xtermBackground() { return term.options.theme && term.options.theme.background; },
            bind(next) { client._session = next || null; bg.repaint(); },
            remove() { bg.unregisterSurface(client); },
        };
    }

    let pane = null;
    function ensurePane() {
        if (!pane) pane = addSurface(null, null);
        return pane;
    }

    return {
        bg,
        opacity,
        addSurface,
        documentRoot: rootDataset,
        get container() { return ensurePane().host; },
        get root() { return ensurePane().host.dataset; },
        setSession(name) {
            ensurePane();
            pane.client._session = name || null;
            bg.setActiveSession(name);
            bg.repaint();
        },
    };
}

function bundled(id, extra) {
    const raw = JSON.parse(fs.readFileSync(path.join(THEMES_DIR, id, 'theme.json'), 'utf8'));
    raw.source = 'builtin';
    return Object.assign(raw, extra || {});
}

function themesOver(list, activeId) {
    return {
        listAll() { return list; },
        getActiveTerminalManifest() {
            return list.find((m) => m.id === activeId) || null;
        },
        onXtermThemeChange() { return function () {}; },
    };
}


test('a plain image filename is accepted', () => {
    const { bg } = makeSandbox(null, null);
    assert.equal(bg.isSafeImageName('grid.png'), true);
    assert.equal(bg.isSafeImageName('city_at_night.jpg'), true);
});

test('every escape shape is refused client-side too', () => {
    const { bg } = makeSandbox(null, null);
    for (const bad of [
        '../secrets.png', 'sub/grid.png', '/etc/passwd.png', 'dir\\grid.png',
        'http://evil.example/x.png', 'data:image/png;base64,AAAA',
        'file:///etc/hosts.png', 'grid%2e%2e.png', 'grid.svg', 'grid',
        '.hidden.png', '', null, 12,
    ]) {
        assert.equal(bg.isSafeImageName(bad), false, `leaked: ${String(bad)}`);
    }
});

test('imageUrlFor builds a same-origin url and refuses an unsafe one', () => {
    const { bg } = makeSandbox(null, null);
    assert.equal(
        bg.imageUrlFor({ id: 'demo', source: 'builtin', background: { image: 'grid.png' } }),
        '/static/css/themes/demo/grid.png',
    );
    assert.equal(
        bg.imageUrlFor({ id: 'demo', source: 'user', background: { image: 'grid.png' } }),
        '/themes/demo/grid.png',
    );
    assert.equal(
        bg.imageUrlFor({ id: 'demo', source: 'builtin', background: { image: '../x.png' } }),
        null,
    );
    assert.equal(bg.imageUrlFor({ id: 'demo', source: 'builtin' }), null);
});


test('a theme with no background paints nothing at all', () => {
    const list = [bundled('carnivore', { background: null })];
    const s = makeSandbox(themesOver(list, 'carnivore'), null);
    s.setSession('cloude_api');
    assert.equal(s.bg.resolve().source, 'none');
    assert.equal(s.container.style.backgroundImage, '');
    assert.equal(s.root.terminalBg, undefined);
});

test('the theme answers when the session says nothing', () => {
    const list = [bundled('carnivore', { background: { image: 'a.png', dim: 0.9 } })];
    const s = makeSandbox(themesOver(list, 'carnivore'), null);
    s.setSession('cloude_api');
    const out = s.bg.resolve();
    assert.equal(out.source, 'theme');
    assert.equal(out.url, '/static/css/themes/carnivore/a.png');
    assert.equal(s.root.terminalBg, 'on');
});

test('the session override wins over the theme', () => {
    const list = [
        bundled('carnivore', { background: { image: 'a.png', dim: 0.9 } }),
        bundled('matrix', { background: { image: 'b.png', dim: 0.85 } }),
    ];
    const s = makeSandbox(themesOver(list, 'carnivore'),
        { cloude_api: { theme_id: 'matrix', dim: null, disabled: false } });
    s.setSession('cloude_api');
    const out = s.bg.resolve();
    assert.equal(out.source, 'session');
    assert.equal(out.url, '/static/css/themes/matrix/b.png');
});

test('an override of "off" beats a theme that ships a picture', () => {
    const list = [bundled('carnivore', { background: { image: 'a.png' } })];
    const s = makeSandbox(themesOver(list, 'carnivore'),
        { cloude_api: { theme_id: null, dim: null, disabled: true } });
    s.setSession('cloude_api');
    assert.equal(s.bg.resolve().source, 'none');
    assert.equal(s.container.style.backgroundImage, '');
});


test('an uploaded picture outranks the theme the session borrowed', () => {
    const list = [
        bundled('carnivore', { background: { image: 'a.png', dim: 0.9 } }),
        bundled('matrix', { background: { image: 'b.png', dim: 0.85 } }),
    ];
    const s = makeSandbox(themesOver(list, 'carnivore'), {
        cloude_api: {
            theme_id: 'matrix', dim: null, disabled: false, image: 'cloude_api.png',
        },
    });
    s.setSession('cloude_api');
    const out = s.bg.resolve();
    assert.equal(out.source, 'upload');
    assert.equal(out.url, s.bg.UPLOADED_URL);
});

test('"off" still beats the session\'s own uploaded picture', () => {
    const list = [bundled('carnivore', { background: { image: 'a.png' } })];
    const s = makeSandbox(themesOver(list, 'carnivore'), {
        cloude_api: {
            theme_id: null, dim: null, disabled: true, image: 'cloude_api.png',
        },
    });
    s.setSession('cloude_api');
    assert.equal(s.bg.resolve().source, 'none');
    assert.equal(s.container.style.backgroundImage, '');
});

test('an unsafe stored image name falls through to the theme', () => {
    const list = [bundled('carnivore', { background: { image: 'a.png' } })];
    const s = makeSandbox(themesOver(list, 'carnivore'), {
        cloude_api: {
            theme_id: null, dim: null, disabled: false,
            image: '../../etc/passwd',
        },
    });
    s.setSession('cloude_api');
    const out = s.bg.resolve();
    assert.equal(out.source, 'theme');
    assert.equal(out.url, '/static/css/themes/carnivore/a.png');
});

test('an uploaded picture paints nothing until its bytes are in hand', () => {
    const list = [bundled('carnivore', { background: null })];
    const s = makeSandbox(themesOver(list, 'carnivore'), {
        cloude_api: {
            theme_id: null, dim: null, disabled: false, image: 'cloude_api.png',
        },
    });
    s.setSession('cloude_api');
    assert.equal(s.container.style.backgroundImage, '');
    assert.equal(s.root.terminalBg, undefined);
});


test('carnivore ships a dim its own readability floor allows', () => {
    const { bg } = makeSandbox(null, null);
    const manifest = bundled('carnivore');
    assert.ok(manifest.background, 'carnivore must ship a background block');
    assert.equal(manifest.background.image, 'background.webp');
    const floor = bg.minimumDim(manifest.xterm);
    assert.notEqual(floor, null, 'carnivore\'s palette must be measurable');
    assert.ok(
        manifest.background.dim >= floor,
        `carnivore ships dim ${manifest.background.dim} but its floor is ${floor}`,
    );
    assert.equal(
        bg.effectiveDim(manifest.background.dim, manifest.xterm),
        manifest.background.dim,
    );
});

test('an override naming an uninstalled theme falls through, never blank', () => {
    const list = [bundled('carnivore', { background: { image: 'a.png' } })];
    const s = makeSandbox(themesOver(list, 'carnivore'),
        { cloude_api: { theme_id: 'deleted_theme', dim: null, disabled: false } });
    s.setSession('cloude_api');
    assert.equal(s.bg.resolve().source, 'theme');
});

test('a session dim rides over an inherited picture', () => {
    const list = [bundled('carnivore', { background: { image: 'a.png', dim: 0.85 } })];
    const s = makeSandbox(themesOver(list, 'carnivore'),
        { cloude_api: { theme_id: null, dim: 0.97, disabled: false } });
    s.setSession('cloude_api');
    const out = s.bg.resolve();
    assert.equal(out.source, 'theme');
    assert.equal(out.dim, 0.97);
});


test('the floor holds AA on the foreground for every bundled theme', () => {
    const { bg } = makeSandbox(null, null);
    const ids = fs.readdirSync(THEMES_DIR).filter(
        (n) => fs.existsSync(path.join(THEMES_DIR, n, 'theme.json')));
    assert.ok(ids.length >= 12, `expected the bundled themes, saw ${ids.length}`);
    let measured = 0;
    for (const id of ids) {
        const m = bundled(id);
        const floor = bg.minimumDim(m.xterm);
        if (floor === null) continue;
        measured++;
        const parse = makeSandbox(null, null).opacity.parseCssColorChannels;
        const fg = parse(m.xterm.foreground);
        const bgc = parse(m.xterm.background);
        const ratio = bg.worstRatio(bgc, fg, floor);
        assert.ok(ratio >= bg.TEXT_TARGET,
            `${id}: foreground ${ratio.toFixed(2)}:1 at floor ${floor.toFixed(3)}`);
    }
    assert.ok(measured >= 12, `only ${measured} palettes were measurable`);
});

test('worstRatio knows an image can make a glyph vanish outright', () => {
    const { bg } = makeSandbox(null, null);
    const black = { r: 0, g: 0, b: 0 };
    const mid = { r: 128, g: 128, b: 128 };
    assert.equal(bg.worstRatio(black, mid, 0), 1);
    assert.ok(bg.worstRatio(black, mid, 1) > 4);
});

test('a dark-text theme is floored against BLACK, not against its own text', () => {
    const { bg } = makeSandbox(null, null);
    const m = bundled('carnivore-light');
    const parse = makeSandbox(null, null).opacity.parseCssColorChannels;
    const bgc = parse(m.xterm.background);
    const fg = parse(m.xterm.foreground);
    const floor = bg.minimumDim(m.xterm);
    const againstBlack = bg.contrastRatio(fg, bg.composite(bgc, { r: 0, g: 0, b: 0 }, floor));
    const againstText = bg.contrastRatio(fg, bg.composite(bgc, fg, floor));
    assert.ok(againstBlack < againstText,
        'black must be the harder case for this palette, or the premise is wrong');
    assert.ok(againstBlack >= bg.TEXT_TARGET,
        `carnivore-light over solid black at its floor is ${againstBlack.toFixed(2)}:1`);
});

test('the floor is per-theme, not one constant', () => {
    const { bg } = makeSandbox(null, null);
    const matrix = bg.minimumDim(bundled('matrix').xterm);
    const light = bg.minimumDim(bundled('carnivore-light').xterm);
    assert.ok(matrix !== null && light !== null);
    assert.ok(light > matrix + 0.05,
        `expected carnivore-light (${light}) to need a higher floor than matrix (${matrix})`);
});

test('effectiveDim never returns below the floor', () => {
    const { bg } = makeSandbox(null, null);
    const xterm = bundled('carnivore-light').xterm;
    const floor = bg.minimumDim(xterm);
    assert.equal(bg.effectiveDim(0, xterm), floor);
    assert.equal(bg.effectiveDim(-5, xterm), floor);
    assert.equal(bg.effectiveDim(0.2, xterm), floor);
    assert.equal(bg.effectiveDim(1, xterm), 1);
    assert.equal(bg.effectiveDim('dark', xterm), Math.max(floor, bg.DEFAULT_DIM));
});

test('an unmeasurable palette paints no picture at all', () => {
    const { bg } = makeSandbox(null, null);
    assert.equal(bg.minimumDim({ background: 'not a colour', foreground: '#fff' }), null);
    assert.equal(bg.effectiveDim(0.8, { background: 'nope', foreground: 'nope' }), null);
});

test('an unmeasurable palette is refused at paint time, not defaulted', () => {
    const list = [{
        id: 'broken', source: 'builtin',
        background: { image: 'a.png' },
        xterm: { background: 'not-a-colour', foreground: 'also-not' },
    }];
    const s = makeSandbox(themesOver(list, 'broken'), null);
    s.setSession('cloude_api');
    assert.equal(s.container.style.backgroundImage, '');
    assert.equal(s.root.terminalBg, undefined);
});


test('the scrim is painted once, on the host, not twice', () => {
    const list = [bundled('carnivore', { background: { image: 'a.png', dim: 0.8 } })];
    const s = makeSandbox(themesOver(list, 'carnivore'), null);
    s.setSession('cloude_api');
    // rgb(2, 22, 30)
    assert.equal(
        s.container.style.backgroundImage,
        'linear-gradient(rgba(2, 22, 30, 0.8), rgba(2, 22, 30, 0.8)), '
        + 'url("/static/css/themes/carnivore/a.png")',
    );
    const out = s.opacity.withTerminalBackgroundOpacity(
        { background: '#0e1112', foreground: '#eaebed' }, 0.8);
    assert.equal(out.background, 'rgba(14, 17, 18, 0)');
    assert.equal(out.foreground, '#eaebed');
});

test('an unparseable background colour means no scrim and so no picture', () => {
    const list = [{
        id: 'oddball', source: 'builtin',
        background: { image: 'a.png', dim: 0.8 },
        xterm: { background: 'var(--nope)', foreground: '#ffffff' },
    }];
    const s = makeSandbox(themesOver(list, 'oddball'), null);
    s.setSession('cloude_api');
    assert.equal(s.container.style.backgroundImage, '');
    assert.equal(s.root.terminalBg, undefined);
});

test('no picture means the terminal stays exactly as opaque as before', () => {
    const list = [bundled('carnivore', { background: null })];
    const s = makeSandbox(themesOver(list, 'carnivore'), null);
    s.setSession('cloude_api');
    const raw = { background: '#0e1112' };
    assert.equal(s.opacity.withTerminalBackgroundOpacity(raw, null), raw);
});

test('a dim of 1 is an opaque scrim, so no picture can show through', () => {
    const list = [bundled('carnivore', { background: { image: 'a.png', dim: 1 } })];
    const s = makeSandbox(themesOver(list, 'carnivore'), null);
    s.setSession('cloude_api');
    assert.match(s.container.style.backgroundImage, /rgba\(2, 22, 30, 1\)/);
});


test('the css is gated on the same attribute the resolver sets', () => {
    assert.match(backgroundCss, /\[data-terminal-bg="on"\]\s*#terminal\s*\{[^}]*background-color:\s*transparent/);
    assert.ok(!/\[data-terminal-bg="on"\]\s*#terminal\s*\{[^}]*[^-]background:\s/.test(backgroundCss),
        'the background shorthand is back on #terminal and will reset background-size');
    assert.match(backgroundCss, /\[data-terminal-bg="on"\]\s*\{[^}]*background-size:\s*cover/);
});

test('the css gate is not pinned to the document element', () => {
    assert.ok(!/html\[data-terminal-bg/.test(backgroundCss),
        'a document-wide gate survived the move to per-session backgrounds');
    assert.ok((backgroundCss.match(/\[data-terminal-bg="on"\]/g) || []).length >= 2);
});


test('two sessions on screen paint two different pictures', () => {
    const list = [
        bundled('carnivore', { background: { image: 'a.png', dim: 0.9 } }),
        bundled('matrix', { background: { image: 'b.png', dim: 0.9 } }),
    ];
    const s = makeSandbox(themesOver(list, 'carnivore'), {
        cloude_one: { theme_id: 'carnivore', dim: 0.9 },
        cloude_two: { theme_id: 'matrix', dim: 0.9 },
    });
    const one = s.addSurface('cloude_one', null);
    const two = s.addSurface('cloude_two', null);
    s.bg.repaint();
    assert.match(one.image, /a\.png/);
    assert.match(two.image, /b\.png/);
    assert.ok(one.image !== two.image, 'both cells painted the same picture');
});

test('a session with no picture is left alone while its neighbour has one', () => {
    const list = [bundled('carnivore', { background: { image: 'a.png', dim: 0.9 } })];
    const s = makeSandbox(themesOver(list, 'carnivore'), {
        cloude_one: { theme_id: 'carnivore', dim: 0.9 },
        cloude_two: { disabled: true },
    });
    const one = s.addSurface('cloude_one', null);
    const two = s.addSurface('cloude_two', null);
    s.bg.repaint();
    assert.match(one.image, /a\.png/);
    assert.equal(two.image, '', 'the disabled session was painted a picture');
    assert.equal(one.flagged, 'on');
    assert.equal(two.flagged, undefined, 'the flag reached a cell with no picture');
    assert.equal(two.xtermBackground, '#1e1e1e');
});

test('two sessions with different dims get two different cell alphas', () => {
    const list = [
        bundled('carnivore', { background: { image: 'a.png' } }),
        bundled('matrix', { background: { image: 'b.png' } }),
    ];
    const s = makeSandbox(themesOver(list, 'carnivore'), {
        cloude_one: { theme_id: 'carnivore', dim: 1 },
        cloude_two: { theme_id: 'matrix', dim: 0.8 },
    });
    const one = s.addSurface('cloude_one', null);
    const two = s.addSurface('cloude_two', null);
    s.bg.repaint();

    assert.match(one.image, /, 1\)/, 'the first cell did not paint its own dim');
    assert.ok(/, 0\.\d+\)/.test(two.image), 'the second cell did not paint its own dim');
    const alphaOne = one.image.match(/rgba\([^)]*?,\s*([0-9.]+)\)/)[1];
    const alphaTwo = two.image.match(/rgba\([^)]*?,\s*([0-9.]+)\)/)[1];
    assert.ok(alphaOne !== alphaTwo,
        `both cells painted the same alpha (${alphaOne})`);

    assert.equal(one.client._xtermOpacity.imageAlpha(), 1);
    const second = two.client._xtermOpacity.imageAlpha();
    assert.ok(second !== null && second !== 1,
        `the second terminal took the first one's alpha (${second})`);
});

test('a terminal registered before it binds re-resolves when it does', () => {
    const list = [
        bundled('carnivore', { background: { image: 'a.png', dim: 0.9 } }),
        bundled('matrix', { background: { image: 'b.png', dim: 0.9 } }),
    ];
    const s = makeSandbox(themesOver(list, 'carnivore'), {
        cloude_late: { theme_id: 'matrix', dim: 0.9 },
    });
    const late = s.addSurface(null, null);
    assert.match(late.image, /a\.png/,
        'an unbound surface should fall back to the page theme');
    late.bind('cloude_late');
    assert.match(late.image, /b\.png/,
        'the terminal kept its unbound answer after its session arrived');
});

test('a surface that is removed stops being painted and lets its bytes go', () => {
    const list = [bundled('carnivore', { background: { image: 'a.png', dim: 0.9 } })];
    const s = makeSandbox(themesOver(list, 'carnivore'), {
        cloude_one: { theme_id: 'carnivore', dim: 0.9 },
    });
    const one = s.addSurface('cloude_one', null);
    s.bg.repaint();
    assert.match(one.image, /a\.png/);
    one.remove();
    assert.equal(one.image, '', 'a removed cell was left wearing its picture');
});

test('a session wears the theme IT pinned, not the one the page resolved', () => {
    const list = [
        bundled('carnivore', { background: { image: 'a.png', dim: 0.9 } }),
        bundled('matrix', { background: { image: 'b.png', dim: 0.9 } }),
    ];
    const s = makeSandbox(themesOver(list, 'carnivore'), null);
    const pinned = s.addSurface('cloude_two', 'matrix');
    s.bg.repaint();
    assert.match(pinned.image, /b\.png/,
        'the cell wore the page theme instead of its own pin');
});

test('the css never uses a fixed background attachment', () => {
    assert.ok(!/background-attachment\s*:\s*fixed/.test(backgroundCss));
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
