'use strict';
// not a universal

const fs = require('node:fs');
const path = require('node:path');
const { outputDirFromArgs } = require('./electron-policy');

const SENTINEL = Buffer.from('dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX');
const WIRE_VERSION = 1;
const DISABLED = 0x30;
const ENABLED = 0x31;
const FUSE_INDEX = {
    runAsNode: 0,
    enableCookieEncryption: 1,
    enableNodeOptionsEnvironmentVariable: 2,
    enableNodeCliInspectArguments: 3,
    enableEmbeddedAsarIntegrityValidation: 4,
    onlyLoadAppFromAsar: 5,
    loadBrowserProcessSpecificV8Snapshot: 6,
    grantFileProtocolExtraPrivileges: 7,
};
const WASM_TRAP_INDEX = 8;
const HARDENED = {
    runAsNode: false,
    enableCookieEncryption: true,
    enableNodeOptionsEnvironmentVariable: false,
    enableNodeCliInspectArguments: false,
    enableEmbeddedAsarIntegrityValidation: true,
    onlyLoadAppFromAsar: true,
    loadBrowserProcessSpecificV8Snapshot: false,
    grantFileProtocolExtraPrivileges: false,
};
const CPU_ARM64 = 0x0100000c;
const CPU_X86_64 = 0x01000007;
const CPU_NAMES = { [CPU_ARM64]: 'arm64', [CPU_X86_64]: 'x86_64' };
const FAT_MAGIC = 0xcafebabe;
const FAT_MAGIC_64 = 0xcafebabf;
const FRAMEWORK_REL = path.join('mac-universal', 'Carnivore.app', 'Contents', 'Frameworks', 'Electron Framework.framework', 'Versions', 'A', 'Electron Framework');

class FuseError extends Error {}

function expectedFromPackage(pkg) {
    const fuses = pkg && pkg.build && pkg.build.electronFuses;
    if (fuses === null || typeof fuses !== 'object') throw new FuseError('package.json has no build.electronFuses: the packaged app would keep Electron\'s default (open) fuses');
    for (const key of Object.keys(fuses)) {
        if (!(key in FUSE_INDEX)) throw new FuseError(`build.electronFuses names "${key}", which is not a fuse electron-builder sets (${Object.keys(FUSE_INDEX).join(', ')})`);
    }
    for (const key of Object.keys(FUSE_INDEX)) {
        if (typeof fuses[key] !== 'boolean') throw new FuseError(`build.electronFuses.${key} must be true or false (it is ${JSON.stringify(fuses[key])})`);
    }
    return { ...fuses };
}

function checkPackage(pkg) {
    const expected = expectedFromPackage(pkg);
    for (const [key, want] of Object.entries(HARDENED)) {
        if (expected[key] !== want) throw new FuseError(`build.electronFuses.${key} is ${expected[key]}, the hardened floor is ${want}`);
    }
}

/* not a universal the whole file */
function fatSlices(buf) {
    if (buf.length < 8) throw new FuseError('the Electron Framework file is too small to be a Mach-O binary');
    const magic = buf.readUInt32BE(0);
    if (magic !== FAT_MAGIC && magic !== FAT_MAGIC_64) throw new FuseError('the Electron Framework is not a universal (fat) Mach-O binary');
    const wide = magic === FAT_MAGIC_64;
    const count = buf.readUInt32BE(4);
    const entry = wide ? 32 : 20;
    if (count < 1 || count > 16 || 8 + count * entry > buf.length) throw new FuseError('the fat header of the Electron Framework is not valid');
    const slices = [];
    for (let i = 0; i < count; i++) {
        const at = 8 + i * entry;
        const cpu = buf.readUInt32BE(at);
        const start = wide ? Number(buf.readBigUInt64BE(at + 8)) : buf.readUInt32BE(at + 8);
        const size = wide ? Number(buf.readBigUInt64BE(at + 16)) : buf.readUInt32BE(at + 12);
        if (start + size > buf.length) throw new FuseError('a slice of the Electron Framework runs past the end of the file');
        slices.push({ cpu, start, end: start + size });
    }
    return slices;
}

function readSliceWires(buf) {
    const slices = fatSlices(buf);
    const out = [];
    for (const want of [CPU_ARM64, CPU_X86_64]) {
        const slice = slices.find((s) => s.cpu === want);
        const arch = CPU_NAMES[want];
        if (!slice) throw new FuseError(`the Electron Framework has no ${arch} slice: the build is not universal`);
        const bytes = buf.subarray(slice.start, slice.end);
        const first = bytes.indexOf(SENTINEL);
        if (first === -1) throw new FuseError(`the ${arch} slice has no fuse sentinel`);
        if (bytes.indexOf(SENTINEL, first + 1) !== -1) throw new FuseError(`the ${arch} slice holds more than one fuse sentinel`);
        const at = first + SENTINEL.length;
        if (bytes[at] !== WIRE_VERSION) throw new FuseError(`the ${arch} slice carries fuse wire version ${bytes[at]}, this check reads version ${WIRE_VERSION}`);
        const length = bytes[at + 1];
        if (length <= WASM_TRAP_INDEX - 1 || at + 2 + length > bytes.length) throw new FuseError(`the ${arch} slice's fuse wire is ${length} long, shorter than the ${Object.keys(FUSE_INDEX).length} fuses this check pins`);
        out.push({ arch, wire: [...bytes.subarray(at + 2, at + 2 + length)] });
    }
    return out;
}

function mismatches(wires, expected) {
    const lines = [];
    for (const { arch, wire } of wires) {
        for (const [key, want] of Object.entries(expected)) {
            const got = wire[FUSE_INDEX[key]];
            if (got !== (want ? ENABLED : DISABLED)) lines.push(`${arch} slice: ${key} is ${got === ENABLED ? 'on' : got === DISABLED ? 'off' : `state byte ${got}`}, expected ${want ? 'on' : 'off'}`);
        }
        if (wire.length > WASM_TRAP_INDEX && wire[WASM_TRAP_INDEX] !== ENABLED) lines.push(`${arch} slice: WasmTrapHandlers must stay at Electron's default (on)`);
    }
    return lines;
}

function checkBuilt(macOSDir, builderArgs) {
    const expected = expectedFromPackage(JSON.parse(fs.readFileSync(path.join(macOSDir, 'package.json'), 'utf8')));
    const binary = path.join(path.resolve(macOSDir, outputDirFromArgs(builderArgs)), FRAMEWORK_REL);
    if (!fs.existsSync(binary)) throw new FuseError(`the build wrote no ${binary}: cannot read its fuses`);
    const wires = readSliceWires(fs.readFileSync(binary));
    const bad = mismatches(wires, expected);
    if (bad.length > 0) throw new FuseError(`the built Electron's fuses differ from package.json: ${bad.join('; ')}`);
    return `built binary fuses match package.json on ${wires.map((w) => w.arch).join(' and ')} (${Object.keys(expected).length} fuses plus WasmTrapHandlers)`;
}

function main(argv) {
    const macOSDir = path.resolve(__dirname, '..');
    const [cmd, ...rest] = argv;
    const split = rest.indexOf('--');
    const builderArgs = split === -1 ? [] : rest.slice(split + 1);
    try {
        if (cmd === 'check') {
            checkPackage(JSON.parse(fs.readFileSync(path.join(macOSDir, 'package.json'), 'utf8')));
            return 0;
        }
        if (cmd === 'built') {
            process.stderr.write(`electron-fuses-check: ${checkBuilt(macOSDir, builderArgs)}\n`);
            return 0;
        }
    } catch (err) {
        if (!(err instanceof FuseError)) throw err;
        process.stderr.write(`electron-fuses-check: refusing the build: ${err.message}\n`);
        return 1;
    }
    process.stderr.write('usage: electron-fuses-check.js check | built -- <electron-builder args>\n');
    return 2;
}

if (require.main === module) process.exitCode = main(process.argv.slice(2));

module.exports = {
    SENTINEL, FUSE_INDEX, HARDENED, WASM_TRAP_INDEX, FRAMEWORK_REL, FuseError,
    expectedFromPackage, checkPackage, fatSlices, readSliceWires, mismatches, checkBuilt,
};
