'use strict';


const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { outputDirFromArgs } = require('./electron-policy');

function restamp(dist) {
    const manifest = path.join(dist, 'latest-mac.yml');
    if (!fs.existsSync(manifest)) throw new Error(`no latest-mac.yml in ${dist}`);
    const changed = [];
    const pattern = /^(\s*-\s*url:\s*)(\S+)(\s*\n\s*sha512:\s*)(\S+)(\s*\n\s*size:\s*)(\d+)/gm;
    const text = fs.readFileSync(manifest, 'utf8').replace(pattern, (whole, a, url, b, sha, c, size) => {
        const file = path.join(dist, url);
        if (url.includes('/') || !fs.existsSync(file)) throw new Error(`latest-mac.yml names ${url}, which is not in ${dist}`);
        const bytes = fs.readFileSync(file);
        const got = crypto.createHash('sha512').update(bytes).digest('base64');
        if (got === sha && String(bytes.length) === size) return whole;
        fs.rmSync(`${file}.blockmap`, { force: true });
        changed.push(url);
        return `${a}${url}${b}${got}${c}${bytes.length}`;
    });
    if (changed.length) fs.writeFileSync(manifest, text);
    return changed;
}

if (require.main === module) {
    const split = process.argv.indexOf('--');
    const dist = path.resolve(path.resolve(__dirname, '..'), outputDirFromArgs(split === -1 ? [] : process.argv.slice(split + 1)));
    try {
        const changed = restamp(dist);
        process.stderr.write(`restamp-manifest: ${changed.length ? `re-stamped ${changed.join(', ')} (stale blockmaps removed)` : 'every entry already matches'}\n`);
    } catch (err) {
        process.stderr.write(`restamp-manifest: ${err.message}\n`);
        process.exitCode = 1;
    }
}

module.exports = { restamp };
