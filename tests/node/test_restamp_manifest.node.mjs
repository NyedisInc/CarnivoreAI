import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

const require = createRequire(import.meta.url);
const sha = (b) => crypto.createHash('sha512').update(b).digest('base64');

test('re-stamp fixes a stale dmg entry, keeps the zip, removes the stale dmg blockmap', () => {
    const { restamp } = require('../../macOS/scripts/restamp-manifest.js');
    const dist = fs.mkdtempSync(path.join(os.tmpdir(), 'restamp-'));
    const zip = Buffer.from('zip bytes');
    const dmg = Buffer.from('stapled dmg bytes, longer than before');
    fs.writeFileSync(path.join(dist, 'A-mac.zip'), zip);
    fs.writeFileSync(path.join(dist, 'A-mac.zip.blockmap'), 'zipmap');
    fs.writeFileSync(path.join(dist, 'A.dmg'), dmg);
    fs.writeFileSync(path.join(dist, 'A.dmg.blockmap'), 'stale');
    fs.writeFileSync(path.join(dist, 'latest-mac.yml'),
        `version: 1.0.0\nfiles:\n  - url: A-mac.zip\n    sha512: ${sha(zip)}\n    size: ${zip.length}\n` +
        `  - url: A.dmg\n    sha512: WRONG==\n    size: 5\npath: A-mac.zip\nsha512: ${sha(zip)}\nreleaseDate: 'x'\nminimumSystemVersion: 14.0.0\n`);
    assert.deepEqual(restamp(dist), ['A.dmg']);
    const text = fs.readFileSync(path.join(dist, 'latest-mac.yml'), 'utf8');
    assert.ok(text.includes(`url: A.dmg\n    sha512: ${sha(dmg)}\n    size: ${dmg.length}\n`));
    assert.ok(text.includes(`url: A-mac.zip\n    sha512: ${sha(zip)}\n    size: ${zip.length}\n`));
    assert.ok(text.includes('minimumSystemVersion: 14.0.0'));
    assert.ok(!fs.existsSync(path.join(dist, 'A.dmg.blockmap')));
    assert.ok(fs.existsSync(path.join(dist, 'A-mac.zip.blockmap')));
    assert.deepEqual(restamp(dist), []);
});
