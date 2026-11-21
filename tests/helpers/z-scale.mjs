import fs from 'node:fs';
import assert from 'node:assert/strict';

const TOKENS = fs.readFileSync(new URL('../../web/src/opscenter/tokens.css', import.meta.url), 'utf8');

export function resolveZ(value, label) {
    let plain = value.trim();
    for (let depth = 0; depth < 4 && /var\(/.test(plain); depth += 1) {
        plain = plain.replace(/var\((--oc-z-[a-z-]+)\)/g, (_, name) => {
            const m = new RegExp(`${name}:\\s*([^;]+);`).exec(TOKENS);
            assert.ok(m, `${label} reads ${name}, which tokens.css does not define`);
            return m[1].replace(/\/\*.*$/, '').trim();
        });
    }
    plain = plain.replace(/calc\(([\d\s+]+)\)/g, (_, sum) => String(sum.split('+').reduce((a, b) => a + Number(b), 0)));
    assert.match(plain, /^-?\d+$/, `${label} has a z-index this test cannot resolve: ${value}`);
    return Number(plain);
}
