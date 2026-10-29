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

function loadLed() {
    const src = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'status-led.js'),
        'utf8',
    );
    const context = { console };
    vm.createContext(context);
    vm.runInContext(src, context);
    return context.StatusLed;
}

const Led = loadLed();

const CSS = fs.readFileSync(
    path.join(__dirname, '..', 'client', 'css', 'status-led.css'),
    'utf8',
);

function ruleBody(selector) {
    const stripped = CSS.replace(/\/\*[\s\S]*?\*\//g, '');
    const hits = [...stripped.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter(
        (m) => m[1].trim().replace(/\s*,\s*/g, ', ').replace(/\s+/g, ' ') === selector,
    );
    assert.equal(hits.length, 1, `expected exactly one "${selector}" rule`);
    return hits[0][2];
}

const RULES = CSS.replace(/\/\*[\s\S]*?\*\//g, '');

function stripSelectors() {
    const stripped = CSS.replace(/\/\*[\s\S]*?\*\//g, '');
    return [...stripped.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
        selector: m[1].trim().replace(/\s+/g, ' '),
        body: m[2],
    }));
}


function ruleBodies(selector) {
    const stripped = CSS.replace(/\/\*[\s\S]*?\*\//g, '');
    return [...stripped.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
        .filter((m) => m[1].trim().replace(/\s*,\s*/g, ', ').replace(/\s+/g, ' ') === selector)
        .map((m) => m[2]);
}

function plain(value) {
    return JSON.parse(JSON.stringify(value));
}

function rawAttr(html, attr) {
    const start = html.indexOf(`${attr}="`);
    if (start === -1) return null;
    const from = start + attr.length + 2;
    const end = html.indexOf('"', from);
    if (end === -1) return null;
    return html.slice(from, end);
}


test('both vocabularies are exported and non-empty', () => {
    assert.ok(Array.isArray(Led.INNER_STATES) && Led.INNER_STATES.length > 0);
    assert.ok(Array.isArray(Led.OUTER_STATES) && Led.OUTER_STATES.length > 0);
});

test('the inner vocabulary is exactly the twelve documented states', () => {
    assert.deepEqual(plain(Led.INNER_STATES), [
        'working',
        'waiting-permission',
        'waiting-input',
        'notice',
        'idle',
        'done',
        'dead',
        'disconnected',
        'asleep',
        'asleep-unread',
        'limit',
        'unknown',
    ]);
});

test('the outer vocabulary is exactly the five documented states', () => {
    assert.deepEqual(plain(Led.OUTER_STATES), [
        'active',
        'steady',
        'unread',
        'off',
        'dim',
    ]);
});

test('the exported vocabularies are copies, so a caller cannot mutate them', () => {
    const victim = loadLed();
    victim.INNER_STATES.push('bogus');
    const fresh = loadLed();
    assert.ok(fresh.INNER_STATES.indexOf('bogus') === -1);
});

// ---- markup per state -------------------------------------------------

test('every inner x outer combination renders a labelled LED', () => {
    for (const inner of plain(Led.INNER_STATES)) {
        for (const outer of plain(Led.OUTER_STATES)) {
            const html = Led.ledHtml({ inner, outer });
            assert.equal(rawAttr(html, 'data-inner'), inner, `inner ${inner}`);
            assert.equal(rawAttr(html, 'data-outer'), outer, `outer ${outer}`);
            assert.ok(html.includes('class="status-led"'), 'carries the class');
            assert.ok(html.includes('role="img"'), 'is a meaningful glyph');
            const label = rawAttr(html, 'aria-label');
            assert.ok(label && label.length > 0, `labelled: ${inner}/${outer}`);
            assert.equal(rawAttr(html, 'title'), label, 'title matches aria-label');
        }
    }
});

test('an unknown inner or outer value is clamped, never emitted raw', () => {
    const html = Led.ledHtml({ inner: 'banana', outer: 'kumquat' });
    assert.equal(rawAttr(html, 'data-inner'), 'unknown');
    assert.equal(rawAttr(html, 'data-outer'), 'dim');
});

test('no arguments at all still renders a valid not-measured LED', () => {
    const html = Led.ledHtml();
    assert.equal(rawAttr(html, 'data-inner'), 'unknown');
    assert.equal(rawAttr(html, 'data-outer'), 'dim');
});

test('ledHtml escapes a hostile title rather than interpolating it raw', () => {
    const html = Led.ledHtml({ inner: 'done', outer: 'steady', title: '"><img src=x>' });
    assert.ok(!html.includes('<img'), 'no tag escapes into the markup');
    assert.ok(html.includes('&quot;'), 'the quote is entity-encoded');
});

test('size is accepted only as a plain CSS length', () => {
    assert.ok(Led.ledHtml({ size: '18px' }).includes('--led-size: 18px'));
    assert.ok(Led.ledHtml({ size: '1.5rem' }).includes('--led-size: 1.5rem'));
    assert.ok(!Led.ledHtml({ size: 'red; background:url(x)' }).includes('style='));
    assert.ok(!Led.ledHtml({ size: 12 }).includes('style='));
});

test('extraClass is accepted only as plain class names', () => {
    const ok = Led.ledHtml({ extraClass: 'status-dot status-dot--dead' });
    assert.ok(ok.includes('class="status-dot status-dot--dead status-led"'));
    const bad = Led.ledHtml({ extraClass: '" onload="x' });
    assert.ok(bad.includes('class="status-led"'), 'rejected, not escaped in');
});

// ---- the mapping from server signals ----------------------------------

test('dead outranks everything, and a corpse never glows', () => {
    assert.deepEqual(plain(Led.ledStateFor({ activity_status: 'dead', unread: true })), {
        inner: 'dead',
        outer: 'off',
    });
    assert.deepEqual(plain(Led.ledStateFor({ activity_status: 'stopped', unread: true })), {
        inner: 'dead',
        outer: 'off',
    });
});

test('a startup prompt is waiting-input even when the status says nothing', () => {
    assert.deepEqual(
        plain(Led.ledStateFor({
            activity_status: 'idle',
            startup_gate: 'awaiting_startup_prompt',
        })),
        { inner: 'waiting-input', outer: 'active' },
    );
});

test('a startup gate that could not be measured does not claim anything', () => {
    assert.deepEqual(
        plain(Led.ledStateFor({ activity_status: 'idle', startup_gate: 'unknown' })),
        { inner: 'idle', outer: 'steady' },
    );
});

test('question maps to waiting-permission - the agent is stopped', () => {
    assert.deepEqual(plain(Led.ledStateFor({ activity_status: 'question' })), {
        inner: 'waiting-permission',
        outer: 'active',
    });
});

test('notice has its own inner state - working, and wanting you', () => {
    assert.deepEqual(plain(Led.ledStateFor({ activity_status: 'notice' })), {
        inner: 'notice',
        outer: 'active',
    });
});

test('question and notice do not paint the same inner dot', () => {
    assert.notEqual(
        Led.ledStateFor({ activity_status: 'question' }).inner,
        Led.ledStateFor({ activity_status: 'notice' }).inner,
    );
});

test('a startup prompt is STOPPED, so it paints the permission yellow', () => {
    const gated = Led.ledStateFor({
        activity_status: 'idle',
        startup_gate: 'awaiting_startup_prompt',
    });
    assert.equal(gated.inner, 'waiting-input');
    assert.notEqual(gated.inner, Led.ledStateFor({ activity_status: 'notice' }).inner);
});

test('the two yellows resolve to the same colour token', () => {
    assert.ok(CSS.includes('--led-color-waiting: var(--color-warning'));
    assert.ok(CSS.includes('--led-color-permission: var(--color-warning'));
});

test('light blue is not the green, and is not derived from it', () => {
    assert.ok(CSS.includes('--led-color-notice: var(--color-info'));
    assert.ok(CSS.includes('--led-color-working: var(--color-success'));
});

test('BOTH a permission and a notice open still answers yellow', () => {
    const both = Led.ledStateFor({
        activity_status: 'question',
        notice_open: true,
        permission_open: true,
    });
    assert.equal(both.inner, 'waiting-permission');
    assert.notEqual(both.inner, 'notice');
});

test('a dropped socket is red, and outranks every session-side status', () => {
    for (const status of [
        'working', 'working_subagent', 'question', 'notice',
        'finished_unread', 'idle', 'unknown', undefined,
    ]) {
        assert.deepEqual(
            plain(Led.ledStateFor({ activity_status: status, transport: 'disconnected' })),
            { inner: 'disconnected', outer: 'off' },
            `transport must win over ${status}`,
        );
    }
    assert.ok(CSS.includes('--led-color-disconnected: var(--color-danger'));
    assert.ok(CSS.includes('--led-color-dead: #494c4f'));
});

test('DEAD IS NO LONGER RED, DISCONNECTED STILL IS, AND THE LABELS MUST NOT SHARE WORDS', () => {
    const dead = Led.INNER_LABELS.dead;
    const gone = Led.INNER_LABELS.disconnected;
    assert.ok(dead && gone && dead !== gone);
    assert.ok(/process/.test(dead), 'dead must say the process exited');
    assert.ok(/connection/.test(gone), 'disconnected must say the connection is gone');
});

test('AND SO DO THE TWO YELLOWS - permission is not a startup prompt', () => {
    const perm = Led.INNER_LABELS['waiting-permission'];
    const input = Led.INNER_LABELS['waiting-input'];
    assert.ok(perm && input && perm !== input);
    assert.ok(/permission/.test(perm), `permission must say so, got "${perm}"`);
    for (const label of [perm, input]) {
        assert.ok(/stopped/.test(label), `got "${label}"`);
    }
    const inkFor = (state) => {
        const block = CSS.split(`[data-inner='${state}'] {`)[1].split('}')[0];
        return block.match(/--led-ink:\s*var\((--led-color-[a-z-]+)\)/)[1];
    };
    const hueOf = (token) => CSS.match(
        new RegExp(`${token}:\\s*([^;]+);`),
    )[1].trim();
    assert.equal(
        hueOf(inkFor('waiting-permission')),
        hueOf(inkFor('waiting-input')),
        'the two yellow states must really paint the same hue',
    );
    assert.notEqual(
        hueOf(inkFor('dead')),
        hueOf(inkFor('disconnected')),
        'dead must no longer paint the same hue as disconnected',
    );
});

test('connected and unknown transports change nothing', () => {
    for (const t of ['connected', 'unknown', undefined, null, '']) {
        assert.equal(
            Led.ledStateFor({ activity_status: 'working', transport: t }).inner,
            'working',
        );
    }
});

test('an unread flag never downgrades a blocking permission prompt', () => {
    assert.deepEqual(
        plain(Led.ledStateFor({ activity_status: 'question', unread: true })),
        { inner: 'waiting-permission', outer: 'active' },
    );
});

test('working and working_subagent share the inner dot', () => {
    assert.equal(Led.ledStateFor({ activity_status: 'working' }).inner, 'working');
    assert.equal(
        Led.ledStateFor({ activity_status: 'working_subagent' }).inner,
        'working',
    );
});

test('the legacy `running` spelling still maps to working', () => {
    assert.equal(Led.ledStateFor({ activity_status: 'running' }).inner, 'working');
});

test('A WORKING SESSION IS SOLID GREEN, unread flag or not', () => {
    const busy = Led.ledStateFor({ activity_status: 'working', unread: true });
    assert.deepEqual(plain(busy), { inner: 'working', outer: 'active' });

    const rested = Led.ledStateFor({ activity_status: 'idle', unread: true });
    assert.deepEqual(plain(rested), { inner: 'done', outer: 'unread' });
});

test('idle and seen is a steady IDLE - the grey read dot, not the green one', () => {
    assert.deepEqual(plain(Led.ledStateFor({ activity_status: 'idle' })), {
        inner: 'idle',
        outer: 'steady',
    });
});

test('READ AND UNREAD DIFFER IN BOTH RINGS, which is what makes it visible', () => {
    const read = plain(Led.ledStateFor({ activity_status: 'idle' }));
    const unread = plain(Led.ledStateFor({ activity_status: 'finished_unread' }));
    assert.notEqual(read.inner, unread.inner, 'the dot must change');
    assert.notEqual(read.outer, unread.outer, 'the ring must change');
});

test('an idle row carrying the flag renders as finished_unread, not as idle', () => {
    assert.deepEqual(plain(Led.ledStateFor({ activity_status: 'idle', unread: true })), {
        inner: 'done',
        outer: 'unread',
    });
});

test('finished_unread is done plus an unread halo', () => {
    assert.deepEqual(plain(Led.ledStateFor({ activity_status: 'finished_unread' })), {
        inner: 'done',
        outer: 'unread',
    });
});

test('UNKNOWN IS NOT DONE - the false green this project keeps paying for', () => {
    assert.equal(Led.ledStateFor({ activity_status: 'unknown' }).inner, 'unknown');
    assert.equal(Led.ledStateFor({}).inner, 'unknown');
    assert.equal(Led.ledStateFor(null).inner, 'unknown');
    assert.equal(Led.ledStateFor({ activity_status: 'a-state-from-2030' }).inner, 'unknown');
});

test('UNKNOWN STAYS GREY even with an unread flag on it', () => {
    assert.deepEqual(plain(Led.ledStateFor({ activity_status: 'unknown', unread: true })), {
        inner: 'unknown',
        outer: 'dim',
    });
});

test('THE WHOLE MAPPING, one row per state, is what the user asked for', () => {
    const cases = [
        [{ activity_status: 'question' }, 'waiting-permission', 'active'],
        [{ activity_status: 'idle', startup_gate: 'awaiting_startup_prompt' },
            'waiting-input', 'active'],
        [{ activity_status: 'notice' }, 'notice', 'active'],
        [{ activity_status: 'finished_unread' }, 'done', 'unread'],
        [{ activity_status: 'working' }, 'working', 'active'],
        [{ activity_status: 'working_subagent' }, 'working', 'active'],
        [{ activity_status: 'idle' }, 'idle', 'steady'],
        [{ activity_status: 'idle', unread: true }, 'done', 'unread'],
        [{ activity_status: 'unknown' }, 'unknown', 'dim'],
        [{ activity_status: 'dead' }, 'dead', 'off'],
        [{ activity_status: 'stopped' }, 'dead', 'off'],
        [{ transport: 'disconnected' }, 'disconnected', 'off'],
    ];
    for (const [signals, inner, outer] of cases) {
        assert.deepEqual(
            plain(Led.ledStateFor(signals)),
            { inner, outer },
            `wrong LED for ${JSON.stringify(signals)}`,
        );
    }
});

test('the finished-turn ring is a GREEN RIM around the SAME recessed centre unknown shows', () => {
    const led = Led.ledStateFor({ activity_status: 'finished_unread' });
    assert.equal(led.inner, 'done');
    assert.equal(led.outer, 'unread');
    assert.ok(CSS.includes('--led-color-idle: var(--color-fg-muted'));
    assert.ok(/--led-ink:\s*var\(--led-color-idle\)/.test(
        ruleBody(".status-led[data-inner='done']")));
    assert.ok(CSS.includes('--led-color-unread: var(--color-success'));
    const block = ruleBody(".status-led[data-outer='unread']");
    assert.ok(
        /--led-inset-ring:\s*inset 0 0 0 var\(--led-hollow-width\) var\(--led-color-unread\)/
            .test(block),
        "unread reuses unknown's inset rim in green, as a shadow LAYER",
    );
    for (const geom of ['--led-size', '--led-ring-width', '--led-ring-feather-blur',
                        '--led-glow-blur', '--led-glow-spread', '--led-lit-scale',
                        '--led-halo-scale']) {
        assert.ok(!new RegExp(geom + ':').test(block),
            `no state may set ${geom} - see the geometry block`);
    }
});

test("unread's centre matches unknown's centre - same recipe, one different hue", () => {
    const unknownBlock = ruleBody(".status-led[data-inner='unknown']");
    const unreadBlock = ruleBody(".status-led[data-outer='unread']");
    for (const block of [unknownBlock, unreadBlock]) {
        assert.ok(
            /--led-inset-ring:\s*inset 0 0 0 var\(--led-hollow-width\)/.test(block),
            'both rims are the same width, read from one token',
        );
    }
    assert.ok(/var\(--led-color-unknown\)/.test(unknownBlock), "unknown's rim is grey");
    assert.ok(/var\(--led-color-unread\)/.test(unreadBlock), "unread's rim is green");
    assert.ok(/--led-ring-ink:\s*var\(--led-color-unknown\)/.test(unreadBlock));
    assert.ok(/--led-glow-alpha:\s*0%/.test(unreadBlock), 'the ring does not glow');
});

test('THE CLEARED CENTRE IS ONE RECIPE SHARED BY BOTH HOLLOW STATES', () => {
    const clears = CSS.match(/--led-fill:\s*transparent;/g) || [];
    assert.equal(
        clears.length, 2,
        'the cleared centre must be declared once per reason, and there are two',
    );
    assert.ok(
        /--led-fill:\s*transparent;/.test(ruleBody(
            ".status-led[data-inner='unknown'], .status-led[data-outer='unread']",
        )),
        'the one clear must name both hollow states',
    );
    const base = ruleBodies('.status-led')[0];
    assert.ok(
        /background-color:\s*var\(--led-fill\);/.test(base),
        'the dot is painted with the fill token, not the ink',
    );
    assert.ok(
        /--led-fill:\s*var\(--led-ink\);/.test(base),
        'and it defaults to the ink, so a solid state stays solid',
    );
    const legacy = ruleBody('.status-dot.status-led');
    assert.ok(
        /background-color:\s*var\(--led-fill\);/.test(legacy),
        'the legacy compat block must not refill the hollow states',
    );
});

test('grey at rest and grey unmeasured are told apart by SHAPE', () => {
    assert.ok(CSS.includes('--led-color-unknown: var(--color-fg-muted'));
    assert.ok(CSS.includes('--led-color-idle: var(--color-fg-muted'));
    const hollow = ruleBody(".status-led[data-inner='unknown']");
    assert.ok(/--led-inset-ring:\s*inset/.test(hollow), 'the rim is an inset shadow layer');
    assert.ok(/var\(--led-color-unknown\)/.test(hollow), 'the rim is grey');
    const idle = ruleBody(".status-led[data-inner='idle']");
    assert.ok(!/--led-inset-ring:/.test(idle), 'idle is not hollow');
    assert.ok(!/--led-fill:\s*transparent/.test(idle), 'idle keeps its fill');
    const ring = ruleBody(".status-led[data-outer='unread']");
    assert.ok(/var\(--led-color-unread\)/.test(ring), 'the ring is green');
});


test('every inner state has a colour rule', () => {
    for (const inner of plain(Led.INNER_STATES)) {
        assert.ok(
            CSS.includes(`[data-inner='${inner}']`),
            `no rule for inner state ${inner}`,
        );
    }
});

test('every outer state has a rule', () => {
    for (const outer of plain(Led.OUTER_STATES)) {
        assert.ok(
            CSS.includes(`[data-outer='${outer}']`),
            `no rule for outer state ${outer}`,
        );
    }
});

test('every state colour is a named token declared in one place', () => {
    for (const token of [
        '--led-color-working',
        '--led-color-waiting',
        '--led-color-permission',
        '--led-color-notice',
        '--led-color-idle',
        '--led-color-dead',
        '--led-color-disconnected',
        '--led-color-unknown',
        '--led-color-unread',
    ]) {
        const declarations = CSS.split(`${token}:`).length - 1;
        assert.equal(declarations, 1, `${token} must be declared exactly once`);
    }
});










test('no pseudo-element on the LED can become a SECOND BOX', () => {
    const pseudo = stripSelectors().filter((r) => /::(after|before)/.test(r.selector));

    assert.ok(pseudo.length > 0,
        'this guard must have a subject; zero rules means it proves nothing');

    const declaring = pseudo.filter((r) => /content\s*:/.test(r.body));
    assert.ok(declaring.length > 0, 'no pseudo-element is declared at all');
    for (const rule of declaring) {
        assert.ok(
            /position:\s*absolute/.test(rule.body),
            `${rule.selector} must be absolutely positioned, or it is a second box`,
        );
        assert.ok(
            /inset:\s*0/.test(rule.body),
            `${rule.selector} must be inset to the element's own box`,
        );
    }
});

test('the ring and the glow are layers of ONE box-shadow on the element', () => {
    const base = RULES.split('\n.status-led {')[1].split('\n}')[0];
    const shadowDeclarations = base.split('box-shadow:').length - 1;
    assert.equal(
        shadowDeclarations,
        1,
        'the base rule must declare box-shadow exactly once',
    );
    assert.ok(
        base.includes(
            'box-shadow: var(--led-inset-ring), var(--led-ring-layer), var(--led-ring-feather-layer),\n' +
                '        var(--led-glow-layer);',
        ),
        'the one declaration must be the four named layers, in paint order',
    );
});

test('the hard ring is a zero-blur spread shadow, so its outer edge is exact', () => {
    assert.ok(
        /--led-ring-layer:\s*0 0 0 var\(--led-ring-width\)/.test(CSS),
        'the ring layer must be 0 0 0 <ring-width>, not a blurred shadow',
    );
    const widthMatch = CSS.match(/--led-ring-width:\s*([\d.]+)px;/);
    assert.ok(widthMatch, '--led-ring-width must be a plain px value');
    const width = Number(widthMatch[1]);
    assert.equal(
        width,
        0,
        '2026-09-21: the outer ring is off so every state reads at ONE lit diameter,'
            + ' the bare --led-size - the owner\'s "they should all be the same size as'
            + ' the red / dead dot"',
    );
    const size = 9;
    assert.equal(
        size + 2 * width,
        size,
        `the ring must add nothing to the ${size}px dot while it is off`,
    );
});

test('the ring edge is feathered by a second, blurred layer at the same spread', () => {
    assert.ok(
        /--led-ring-feather-layer:\s*0 0 var\(--led-ring-feather-blur\) var\(--led-ring-width\)/.test(
            CSS,
        ),
        'the feather layer must share the ring\'s own spread, blurred',
    );
    assert.ok(
        CSS.includes(
            'color-mix(\n            in srgb,\n            var(--led-ring-ink) calc(var(--led-ring-alpha) * var(--led-ring-feather-fraction)),\n            transparent\n        )',
        ),
        'the feather alpha must be a FRACTION of the ring alpha, so it zeroes automatically with the ring',
    );
    const blurMatch = CSS.match(/--led-ring-feather-blur:\s*([\d.]+)px;/);
    const fractionMatch = CSS.match(/--led-ring-feather-fraction:\s*([\d.]+);/);
    assert.ok(blurMatch, '--led-ring-feather-blur must be a plain px value');
    assert.ok(fractionMatch, '--led-ring-feather-fraction must be a plain unitless value');
    assert.equal(Number(blurMatch[1]), 0, 'the feather blur must be off with the ring');
    assert.equal(
        Number(fractionMatch[1]),
        0,
        'the feather fraction must be off with the ring',
    );
});

test('the whole ring apparatus (hard ring plus feather) stays within about 4px of the dot', () => {
    const width = Number(CSS.match(/--led-ring-width:\s*([\d.]+)px;/)[1]);
    const featherBlur = Number(CSS.match(/--led-ring-feather-blur:\s*([\d.]+)px;/)[1]);
    const reach = width + featherBlur / 2;
    assert.ok(
        reach <= 4,
        `the ring's feathered edge reaches ${reach}px past the dot, over the owner's ~4px ceiling`,
    );
});

test('the soft glow is a blurred layer with its own blur and spread tokens', () => {
    assert.ok(
        /--led-glow-layer:\s*0 0 var\(--led-glow-blur\) var\(--led-glow-spread\)/.test(
            CSS,
        ),
        'the glow layer must be 0 0 <blur> <spread>',
    );
    const blurMatch = CSS.match(/--led-glow-blur:\s*([\d.]+)px;/);
    const spreadMatch = CSS.match(/--led-glow-spread:\s*([\d.]+)px;/);
    assert.ok(blurMatch && spreadMatch, 'both glow tokens must be plain px values');
    assert.equal(Number(blurMatch[1]), 0, '2026-09-21: the soft glow is off');
    assert.equal(Number(spreadMatch[1]), 0, '2026-09-21: the soft glow is off');
    const reach = Number(spreadMatch[1]) + Number(blurMatch[1]) / 2;
    const litDiameter = 9 + 2 * reach;
    assert.equal(
        litDiameter,
        9,
        `lit object ${litDiameter}px must equal the 9px dot: every state one diameter,`
            + ' the same one `dead` has always drawn',
    );
});

test('alpha lives in the shadow colour, never in a STATIC element opacity', () => {
    const staticRules = RULES.split('@keyframes')[0];
    assert.ok(
        !/^\s*opacity:/m.test(staticRules),
        'no static rule may set opacity on the LED - it would fade the fill as well as the ring',
    );
    assert.ok(
        CSS.includes('color-mix(in srgb, var(--led-ring-ink) var(--led-ring-alpha), transparent)'),
        'the ring alpha must be mixed into the ring colour',
    );
    assert.ok(
        CSS.includes('color-mix(in srgb, var(--led-ring-ink) var(--led-glow-alpha), transparent)'),
        'the glow alpha must be mixed into the glow colour',
    );
});

test('the hollow unknown rim is a shadow LAYER, not a second box-shadow declaration', () => {
    const unknownBlock = RULES.split(".status-led[data-inner='unknown'] {")[1].split(
        '\n}',
    )[0];
    assert.ok(
        !unknownBlock.includes('box-shadow:'),
        'the unknown rule must not declare box-shadow',
    );
    assert.ok(
        unknownBlock.includes('--led-inset-ring: inset 0 0 0 var(--led-hollow-width)'),
        'it must set the inset layer instead',
    );
    assert.ok(
        CSS.includes('--led-inset-ring: inset 0 0 0 0 transparent;'),
        'and the default must be a no-op inset layer, so the list length never changes',
    );
});

test('the legacy referee no longer resets box-shadow, which would erase every ring', () => {
    const refereeBlocks = RULES.split('.status-dot.status-led');
    for (let i = 1; i < refereeBlocks.length; i++) {
        const block = refereeBlocks[i].split('\n}')[0];
        assert.ok(
            !block.includes('box-shadow'),
            'no .status-dot.status-led rule may touch box-shadow',
        );
    }
});

test('the referee animation reset excludes the breathing state', () => {
    assert.ok(
        CSS.includes(".status-dot.status-led:not([data-outer='active']) {"),
        'the legacy animation reset must be scoped off the breathing state',
    );
});

test('idle has its own NAMED token, and is told apart by shape not hue', () => {
    const idleBlock = RULES.split(".status-led[data-inner='idle'] {")[1].split('\n}')[0];
    assert.ok(
        idleBlock.includes('--led-ink: var(--led-color-idle)'),
        'idle must resolve through its own colour token',
    );
    assert.ok(
        !idleBlock.includes('var(--led-color-unknown)'),
        'idle must not reach for the unknown token directly',
    );
    assert.ok(/--led-color-idle:\s*var\(/.test(CSS));
    assert.ok(/--led-color-unknown:\s*var\(/.test(CSS));
    assert.equal(
        (CSS.match(/--led-color-idle:/g) || []).length, 1,
        'declared exactly once',
    );
});

test('idle stays a SOLID dot - unknown is the only hollow one', () => {
    const idleBlock = RULES.split(".status-led[data-inner='idle'] {")[1].split(
        '\n}',
    )[0];
    assert.ok(
        !idleBlock.includes('background-color: transparent'),
        'idle must not go hollow - that shape is reserved for unknown',
    );
    assert.ok(
        !idleBlock.includes('--led-inset-ring:'),
        'idle must not set the hollow-rim layer',
    );
});

test('EXACTLY ONE outer state animates, and the animation is on the element', () => {
    assert.ok(CSS.includes(".status-led[data-outer='active'] {"));
    assert.equal(
        (CSS.match(/animation: status-led-breathe/g) || []).length,
        1,
        'only one rule may start the breathing animation',
    );
    assert.ok(
        !/^\.status-led\s*\{[^}]*animation:\s*(?!none)/m.test(RULES),
        'the base rule must not carry a running animation',
    );
});

test('dead has no ring and no glow at all, rather than dim ones', () => {
    const block = RULES.split(".status-led[data-outer='off'] {")[1].split('\n}')[0];
    assert.ok(block.includes('--led-ring-alpha: 0%'), 'a corpse must not ring');
    assert.ok(block.includes('--led-glow-alpha: 0%'), 'a corpse must not glow');
    assert.ok(
        !block.includes('box-shadow'),
        'off must not blank the whole box-shadow - the inset layer belongs to the other dimension',
    );
});

test('dim is a low-alpha ring, not a lit one', () => {
    const block = RULES.split(".status-led[data-outer='dim'] {")[1].split('\n}')[0];
    const alpha = Number(block.match(/--led-ring-alpha:\s*(\d+)%/)[1]);
    assert.ok(alpha > 0 && alpha < 50, `dim ring alpha ${alpha}% must be faint but present`);
    assert.ok(block.includes('--led-glow-alpha: 0%'), 'not-measured must not glow');
});

test('the breathing keyframes move the FILL ALPHA and nothing else', () => {
    const block = RULES.split('@keyframes status-led-breathe')[1].split('\n}\n')[0];
    assert.ok(block, 'the breathing keyframes must exist');
    for (const forbidden of [
        'transform:',
        'width:',
        'height:',
        'margin',
        'inset:',
        'top:',
        'left:',
        'scale(',
        'box-shadow:',
    ]) {
        assert.ok(
            !block.includes(forbidden),
            `the keyframes must not touch ${forbidden} - opacity is the only paint-only option here`,
        );
    }
    const opacityFrames = block.split('opacity:').length - 1;
    assert.equal(opacityFrames, 2, 'exactly two keyframes, each writing opacity');
    const values = Array.from(block.matchAll(/opacity:\s*([\d.]+)/g))
        .map((m) => Number(m[1]))
        .sort((a, b) => a - b);
    assert.equal(values.length, 2, 'two opacity values, a trough and a peak');
    assert.equal(values[1], 1, 'the peak must be full strength');
    assert.ok(
        values[0] >= 0.3 && values[0] < 1,
        `the trough ${values[0]} must still read as a lit dot, and must actually differ from the peak`,
    );
});
test('the rest glow shrinks and dims from ONE fraction', () => {
    assert.ok(
        CSS.includes('calc(var(--led-glow-spread) * var(--led-glow-rest))'),
        'the trough spread must derive from the rest fraction',
    );
    assert.ok(
        CSS.includes('calc(var(--led-glow-alpha) * var(--led-glow-rest))'),
        'the trough alpha must derive from the same fraction',
    );
    const rest = Number(CSS.match(/--led-glow-rest:\s*([\d.]+);/)[1]);
    assert.ok(rest > 0 && rest < 1, `--led-glow-rest ${rest} must be a real fraction`);
});

test('nothing in the stylesheet can move THE ELEMENT', () => {
    const KEYFRAME_STEP = /^(from|to|[\d.]+%)(\s*,\s*(from|to|[\d.]+%))*$/;
    const elementRules = stripSelectors().filter(
        (r) => !/::(after|before)/.test(r.selector) && !KEYFRAME_STEP.test(r.selector),
    );
    assert.ok(elementRules.length > 0, 'this guard must have a subject');
    for (const forbidden of ['transform:', 'margin-top:', 'margin-left:', 'inset:']) {
        for (const rule of elementRules) {
            assert.ok(
                !rule.body.includes(forbidden),
                `${rule.selector} must not use ${forbidden} - it would move the element`,
            );
        }
    }
    for (const rule of elementRules) {
        assert.ok(
            !rule.body.includes('position: absolute'),
            `${rule.selector} may not be taken out of flow - the element is one box`,
        );
    }
});

test('prefers-reduced-motion kills the pulse and leaves the ring lit', () => {
    assert.ok(CSS.includes('@media (prefers-reduced-motion: reduce)'));
    const block = RULES.split('@media (prefers-reduced-motion: reduce)')[1];
    assert.ok(block.includes('animation: none'), 'no motion');
    assert.ok(
        !block.includes('box-shadow'),
        'reduced motion must not restate the shadow - the base rule is already the lit value',
    );
});

test('the breathing period is about two seconds, as specified', () => {
    assert.ok(CSS.includes('status-led-breathe 2s ease-in-out infinite'));
});

await runQueue();
console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
