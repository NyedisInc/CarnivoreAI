'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const PINNED_PACKAGES = ['electron', 'electron-builder', 'electron-updater'];
const EXACT_VERSION = /^\d+\.\d+\.\d+$/;
const MACOS_FLOOR = '14.0';
const MANIFEST_MIN_SYSTEM_VERSION = '23.0.0';

class PolicyError extends Error {}

function declared(pkg, name) {
    return (pkg.dependencies && pkg.dependencies[name]) || (pkg.devDependencies && pkg.devDependencies[name]);
}

function parsePins(pkg) {
    const pins = {};
    for (const name of PINNED_PACKAGES) {
        const spec = declared(pkg, name);
        if (spec === undefined) throw new PolicyError(`${name} is not declared in macOS/package.json`);
        if (!EXACT_VERSION.test(spec)) {
            throw new PolicyError(`${name} is "${spec}" in macOS/package.json: pin an exact version (no ^, ~, range or tag)`);
        }
        pins[name] = spec;
    }
    return pins;
}

function checkBuildConfig(pkg, pins) {
    const mac = (pkg.build && pkg.build.mac) || {};
    const targets = Array.isArray(mac.target) ? mac.target : [];
    if (targets.length === 0) throw new PolicyError('build.mac.target is empty: a universal dmg and zip are required');
    for (const t of targets) {
        const arch = JSON.stringify(t && t.arch);
        if (arch !== '["universal"]') {
            throw new PolicyError(`build.mac.target "${t && t.target}" has arch ${arch}: universal required (arm64 and x64 in one app)`);
        }
    }
    if (mac.minimumSystemVersion !== MACOS_FLOOR) {
        throw new PolicyError(`build.mac.minimumSystemVersion is ${JSON.stringify(mac.minimumSystemVersion)}: the floor is "${MACOS_FLOOR}"`);
    }
    const scripts = pkg.allowScripts || {};
    if (scripts[`electron@${pins.electron}`] !== true) {
        throw new PolicyError(`allowScripts has no "electron@${pins.electron}": move the key with the Electron pin`);
    }
}

function checkInstalled(macOSDir, pins) {
    const problems = [];
    for (const [name, pin] of Object.entries(pins)) {
        let installed = 'not installed';
        try {
            installed = JSON.parse(fs.readFileSync(path.join(macOSDir, 'node_modules', name, 'package.json'), 'utf8')).version;
        } catch (err) {
            if (err.code !== 'ENOENT') installed = `unreadable (${err.code || err.name})`;
        }
        if (installed !== pin) problems.push(`${name} pinned ${pin} but installed ${installed}`);
    }
    if (problems.length > 0) {
        throw new PolicyError(`${problems.join('; ')}; run npm install in macOS/ by hand (this script never installs)`);
    }
}

function compareVersions(a, b) {
    const pa = a.split('.').map(Number);
    const pb = b.split('.').map(Number);
    for (let i = 0; i < 3; i += 1) if (pa[i] !== pb[i]) return pa[i] - pb[i];
    return 0;
}

function newestStable(times) {
    let best = null;
    for (const version of Object.keys(times)) {
        if (!EXACT_VERSION.test(version)) continue;
        if (best === null || compareVersions(version, best) > 0) best = version;
    }
    return best;
}

function checkRegistry(pin, registry) {
    const newest = newestStable(registry.time);
    if (newest === null) throw new PolicyError('could not determine: the registry lists no stable electron release');
    if (newest !== registry.latest) {
        throw new PolicyError(`could not determine: the registry's newest stable electron is ${newest} but its latest tag is ${registry.latest}`);
    }
    if (compareVersions(newest, pin) > 0) {
        throw new PolicyError(`electron ${newest} is the newest stable and the pin is ${pin}: bump the pin`);
    }
    if (compareVersions(newest, pin) < 0) {
        throw new PolicyError(`electron ${pin} is not on the registry's stable list (newest stable is ${newest}): pin the newest stable`);
    }
}

function fetchRegistry() {
    try {
        const out = execFileSync('npm', ['view', 'electron', 'time', 'dist-tags', '--json'], { encoding: 'utf8', timeout: 60000, stdio: ['ignore', 'pipe', 'ignore'] });
        const doc = JSON.parse(out);
        const time = doc && doc.time;
        const latest = doc && doc['dist-tags'] && doc['dist-tags'].latest;
        if (time === null || typeof time !== 'object' || Object.keys(time).filter((k) => EXACT_VERSION.test(k)).length === 0 || !EXACT_VERSION.test(String(latest))) {
            throw new Error('no releases in the answer');
        }
        return { time, latest };
    } catch (err) {
        throw new PolicyError(`could not determine the newest electron: the registry answer was unreadable (${err.message.split('\n')[0]})`);
    }
}

function check(macOSDir, registrySource = fetchRegistry) {
    const pkg = JSON.parse(fs.readFileSync(path.join(macOSDir, 'package.json'), 'utf8'));
    const pins = parsePins(pkg);
    checkBuildConfig(pkg, pins);
    checkInstalled(macOSDir, pins);
    checkRegistry(pins.electron, registrySource());
}

function outputDirFromArgs(args) {
    let dir = 'dist';
    for (const arg of args) {
        const m = /^--?(?:c|config)\.directories\.output=(.+)$/.exec(arg);
        if (m) dir = m[1];
    }
    return dir;
}

function finish(macOSDir, builderArgs, required) {
    const pkg = JSON.parse(fs.readFileSync(path.join(macOSDir, 'package.json'), 'utf8'));
    const pins = parsePins(pkg);
    const out = path.resolve(macOSDir, outputDirFromArgs(builderArgs));
    const manifest = path.join(out, 'latest-mac.yml');
    const notes = [];
    if (!fs.existsSync(manifest)) {
        if (required) throw new PolicyError(`the build wrote no ${manifest}`);
        notes.push(`no latest-mac.yml in ${out}: nothing to stamp (an ad hoc build is not published)`);
    } else {
        let text = fs.readFileSync(manifest, 'utf8');
        const zips = [...text.matchAll(/^\s*-?\s*url:\s*(\S+)/gm)].map((m) => m[1]).filter((u) => u.endsWith('.zip'));
        if (zips.length !== 1 || !/universal/.test(zips[0]) || /arm64|x64/.test(zips[0])) {
            throw new PolicyError(`latest-mac.yml must name exactly one universal zip (no arm64 or x64 in its name), it names: ${zips.join(', ') || 'none'}`);
        }
        text = text.replace(/^minimumSystemVersion:.*\n?/gm, '');
        if (!text.endsWith('\n')) text += '\n';
        fs.writeFileSync(manifest, `${text}minimumSystemVersion: ${MANIFEST_MIN_SYSTEM_VERSION}\n`);
        notes.push(`stamped minimumSystemVersion ${MANIFEST_MIN_SYSTEM_VERSION} (macOS ${MACOS_FLOOR}) into ${manifest}`);
    }
    return notes;
}

function main(argv) {
    const macOSDir = path.resolve(__dirname, '..');
    const [cmd, ...rest] = argv;
    const split = rest.indexOf('--');
    const flags = split === -1 ? rest : rest.slice(0, split);
    const builderArgs = split === -1 ? [] : rest.slice(split + 1);
    try {
        if (cmd === 'check') {
            check(macOSDir);
            return 0;
        }
        if (cmd === 'finish') {
            for (const note of finish(macOSDir, builderArgs, flags.includes('--require'))) process.stderr.write(`electron-policy: ${note}\n`);
            return 0;
        }
    } catch (err) {
        if (!(err instanceof PolicyError)) throw err;
        process.stderr.write(`electron-policy: refusing the build: ${err.message}\n`);
        return 1;
    }
    process.stderr.write('usage: electron-policy.js check | finish [--require] [-- <electron-builder args>]\n');
    return 2;
}

if (require.main === module) process.exitCode = main(process.argv.slice(2));

module.exports = {
    PINNED_PACKAGES, MACOS_FLOOR, MANIFEST_MIN_SYSTEM_VERSION, PolicyError,
    parsePins, checkBuildConfig, checkInstalled, compareVersions, newestStable, checkRegistry, check, outputDirFromArgs, finish,
};
