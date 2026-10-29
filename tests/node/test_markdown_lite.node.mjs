import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
globalThis.window = {};
const log = console.log;
console.log = () => {};
require('../../client/js/http-url.js');
require('../../client/js/markdown-lite.js');
console.log = log;
const render = (md) => globalThis.window.MarkdownLite.render(md);

{
    const html = render('- **LEAN** (Alex (Harbor666),\n  2026-09-28; more)\n- second\n');
    assert.equal((html.match(/<li>/g) || []).length, 2, html);
    assert.equal((html.match(/<ul>/g) || []).length, 1, html);
    assert.ok(html.includes('<li><strong>LEAN</strong> (Alex (Harbor666), 2026-09-28; more)</li>'), html);
    assert.ok(!html.includes('<p>'), html);
}

{
    const html = render('1. first line\n   continues here\n2. next');
    assert.ok(html.includes('<li>first line continues here</li>'), html);
    assert.equal((html.match(/<ol>/g) || []).length, 1, html);
}

{
    const html = render('- item\n  wrapped\n\nafter');
    assert.ok(html.includes('<li>item wrapped</li>\n</ul>\n<p>after</p>'), html);
}

{
    const html = render('one\ntwo\nthree\n\nfour');
    assert.equal(html, '<p>one two three</p>\n<p>four</p>');
}

{
    const html = render('- item\n# Head');
    assert.equal(html, '<ul>\n<li>item</li>\n</ul>\n<h1>Head</h1>');
}

{
    const html = render('| a | b |\n|---|:-:|\n| 1 | `x` |\n| <i> | 2 |\n\ntext');
    assert.ok(html.startsWith('<table><thead><tr><th>a</th><th>b</th></tr></thead>'), html);
    assert.ok(html.includes('<td><code>x</code></td>'), html);
    assert.ok(html.includes('<td>&lt;i&gt;</td>'), html);
    assert.ok(html.includes('<p>text</p>'), html);
}

console.log('markdown-lite: ok');
