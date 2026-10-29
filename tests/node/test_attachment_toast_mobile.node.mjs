import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '../..');
const css = fs.readFileSync(path.join(ROOT, 'client/css/toast.css'), 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, '');

function split(src) {
  let mobile = '';
  let rest = '';
  let i = 0;
  const re = /@media \(max-width: 640px\) \{/g;
  let m;
  while ((m = re.exec(src))) {
    rest += src.slice(i, m.index);
    let depth = 1;
    let j = re.lastIndex;
    while (depth && j < src.length) depth += src[j] === '{' ? 1 : src[j] === '}' ? -1 : 0, j++;
    mobile += src.slice(re.lastIndex, j - 1);
    i = j;
    re.lastIndex = j;
  }
  return { mobile, rest: rest + src.slice(i) };
}

function decls(src, sel) {
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(src))) {
    if (m[1].split(',').map((s) => s.trim()).includes(sel)) return m[2];
  }
  return null;
}

const { mobile, rest } = split(css);
const card = '.toast[data-kind="Attachment"]';

assert.match(decls(mobile, card) || '', /align-self:\s*flex-end/, 'card shrinks to content, right edge');
for (const part of ['.toast__title', '.toast__session', '.toast__thumb-name']) {
  assert.match(decls(mobile, `${card} ${part}`) || '', /display:\s*none/, `${part} hidden on phone`);
}
assert.match(
  decls(mobile, `${card}:not([data-expanded="1"]) .toast__thumbs`) || '',
  /display:\s*flex/, 'thumbs always shown, beating the collapse rule');
assert.equal(decls(rest, `${card} .toast__title`), null, 'desktop keeps the title');
assert.equal(decls(rest, card), null, 'desktop card unchanged');
console.log('ok attachment toast mobile');
