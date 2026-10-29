
import path from 'node:path';
import fs from 'node:fs';

export const PINNED = ['electron', 'electron-builder', 'electron-updater'];

export const specOf = (pkg, name) => pkg.dependencies?.[name] ?? pkg.devDependencies?.[name];

let mirrorCount = 0;
export function mirror(repo, tmp, mutate = () => {}, installed = {}) {
    const root = path.join(tmp, `mirror${mirrorCount++}`);
    const mac = path.join(root, 'macOS');
    fs.mkdirSync(path.join(root, 'scripts', 'release'), { recursive: true });
    fs.mkdirSync(path.join(root, 'src', 'core', 'catalog'), { recursive: true });
    fs.cpSync(path.join(repo, 'macOS', 'scripts'), path.join(mac, 'scripts'), { recursive: true });
    fs.copyFileSync(path.join(repo, 'scripts', 'release', 'spare_key_gate.py'), path.join(root, 'scripts', 'release', 'spare_key_gate.py'));
    fs.copyFileSync(path.join(repo, 'src', 'core', 'catalog', 'trust_root.py'), path.join(root, 'src', 'core', 'catalog', 'trust_root.py'));
    fs.mkdirSync(path.join(mac, 'payload'), { recursive: true });
    fs.writeFileSync(path.join(mac, 'payload', 'sign-payload.sh'), '#!/bin/bash\necho "$@" >> "$(dirname "$0")/sign-payload.calls"\n', { mode: 0o755 });
    const pkg = JSON.parse(fs.readFileSync(path.join(repo, 'macOS', 'package.json'), 'utf8'));
    mutate(pkg);
    fs.writeFileSync(path.join(mac, 'package.json'), JSON.stringify(pkg, null, 2));
    for (const name of PINNED) {
        const dir = path.join(mac, 'node_modules', name);
        fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name, version: installed[name] ?? String(specOf(pkg, name)).replace(/^[^0-9]*/, '') }));
    }
    return { root, mac, pkg, releaseSh: path.join(mac, 'scripts', 'release-build.sh') };
}

export const daysAgo = (n) => new Date(Date.now() - n * 86400000).toISOString();

let registryCount = 0;
export function registry(tmp, pin, pinAge = 20, extra = [], latest = undefined) {
    const times = { created: daysAgo(900), modified: daysAgo(1), [pin]: daysAgo(pinAge), '999.0.0-beta.1': daysAgo(40) };
    for (const [v, age] of extra) times[v] = daysAgo(age);
    const file = path.join(tmp, `registry${registryCount++}.json`);
    const stable = Object.keys(times).filter((v) => /^\d+\.\d+\.\d+$/.test(v))
        .sort((x, y) => x.split('.').map(Number).reduce((d, n, i) => d || n - y.split('.').map(Number)[i], 0)).pop();
    fs.writeFileSync(file, JSON.stringify({ time: times, 'dist-tags': { latest: latest ?? stable } }));
    return file;
}

export const manifestBody = (...files) =>
    `version: 2.0.0-beta.1\nfiles:\n${files.map((z) => `  - url: ${z}\n    sha512: abc\n    size: 1\n`).join('')}path: ${files[0]}\nsha512: abc\nreleaseDate: '2026-10-23T00:00:00.000Z'\n`;

export const GOOD_MANIFEST = manifestBody('Carnivore-2.0.0-beta.1-universal-mac.zip', 'Carnivore-2.0.0-beta.1-universal.dmg');


export const FUSE_SENTINEL = 'dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX';
export const HARDENED_WIRE = [0, 1, 0, 0, 1, 1, 0, 0, 1];
export const STOCK_WIRE = [1, 0, 1, 1, 0, 0, 0, 1, 1];

export function sliceBytes(wire, sentinels = 1) {
    const one = Buffer.concat([Buffer.from(FUSE_SENTINEL), Buffer.from([1, wire.length]), Buffer.from(wire.map((b) => 0x30 + b))]);
    return Buffer.concat([Buffer.alloc(64, 7), ...Array.from({ length: sentinels }, () => Buffer.concat([one, Buffer.alloc(16, 9)]))]);
}

export function fatBinary(entries, wide = false) {
    const entrySize = wide ? 32 : 20;
    const head = Buffer.alloc(8 + entries.length * entrySize);
    head.writeUInt32BE(wide ? 0xcafebabf : 0xcafebabe, 0);
    head.writeUInt32BE(entries.length, 4);
    let cursor = Math.ceil(head.length / 16) * 16;
    const parts = [head, Buffer.alloc(cursor - head.length)];
    entries.forEach(([cpu, bytes], i) => {
        const at = 8 + i * entrySize;
        head.writeUInt32BE(cpu, at);
        if (wide) {
            head.writeBigUInt64BE(BigInt(cursor), at + 8);
            head.writeBigUInt64BE(BigInt(bytes.length), at + 16);
        } else {
            head.writeUInt32BE(cursor, at + 8);
            head.writeUInt32BE(bytes.length, at + 12);
        }
        const next = Math.ceil((cursor + bytes.length) / 16) * 16;
        parts.push(bytes, Buffer.alloc(next - cursor - bytes.length));
        cursor = next;
    });
    return Buffer.concat(parts);
}

export const ARM64 = 0x0100000c;
export const X86_64 = 0x01000007;

export function writeFakeBuilt(outDir, binary) {
    const file = path.join(outDir, 'mac-universal', 'Carnivore.app', 'Contents', 'Frameworks', 'Electron Framework.framework', 'Versions', 'A', 'Electron Framework');
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, binary);
    return file;
}

export const universal = (wireA, wireB = wireA) => fatBinary([[ARM64, sliceBytes(wireA)], [X86_64, sliceBytes(wireB)]]);

export function hardenedBinaryFile(dir) {
    const file = path.join(dir, 'hardened-framework.bin');
    fs.writeFileSync(file, universal(HARDENED_WIRE));
    return file;
}

export const FRAMEWORK_UNDER_OUT = path.join('mac-universal', 'Carnivore.app', 'Contents', 'Frameworks', 'Electron Framework.framework', 'Versions', 'A', 'Electron Framework');
