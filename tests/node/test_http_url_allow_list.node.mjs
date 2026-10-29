import { strict as assert } from 'node:assert';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const JS = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'client', 'js');
const read = (f) => fs.readFileSync(path.join(JS, f), 'utf8');

function load(withAllowList = true) {
    const sandbox = { console: { log() {}, warn() {} } };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    if (withAllowList) vm.runInContext(read('http-url.js'), sandbox);
    vm.runInContext(read('markdown-lite.js'), sandbox);
    return sandbox;
}

test('markdown links: http and https render, every other scheme is plain text', () => {
    const md = load().window.MarkdownLite;
    assert.match(md.render('[ok](https://example.com/a)'), /<a href="https:\/\/example\.com\/a"/);
    for (const bad of ['file:///etc/passwd', 'vscode://open', 'ms-msdt:x', 'java\tscript:alert(1)', 'javascript:alert(1)', 'data:text/html,x']) {
        const out = md.render(`[label](${bad.replace(/\s/g, '')})`);
        assert.doesNotMatch(out, /<a /, `${bad} must not become a link`);
        assert.match(out, /label/);
    }
});

test('a control character inside the scheme is stripped before the test', () => {
    const { HttpUrl } = load().window;
    assert.equal(HttpUrl.isHttpUrl('java\u001fscript:x'), false);
    assert.equal(HttpUrl.isHttpUrl('\u001fhttps://example.com'), true);
});

test('with the allow-list missing no link is safe (fails closed)', () => {
    const md = load(false).window.MarkdownLite;
    assert.doesNotMatch(md.render('[x](https://example.com)'), /<a /);
});
