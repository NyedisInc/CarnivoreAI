'use strict';
// cannot be read

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
    if (targets.length === 0) throw new PolicyError('build.mac.target is empty: split arm64 and x64 dmg and zip are required');
    for (const t of targets) {
        const arch = JSON.stringify(t && t.arch);
        if (arch !== '["arm64","x64"]') {
            throw new PolicyError(`build.mac.target "${t && t.target}" has arch ${arch}: split ["arm64","x64"] required`);
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

const WAIVER_VAR = 'CARNIVORE_ELECTRON_WAIVER';
const WAIVER_FORMAT = /^(\d+\.\d+\.\d+):(\d+\.\d+\.\d+):(.*\S) (\d{4}-\d{2}-\d{2})$/;

function parseWaiver(raw) {
    if (raw === undefined || raw.trim() === '') return null;
    const m = WAIVER_FORMAT.exec(raw.trim());
    if (m === null) throw new PolicyError(`${WAIVER_VAR} is malformed: expected "<pin>:<newest>:<operator> <YYYY-MM-DD>"`);
    return { pin: m[1], newest: m[2], who: m[3], date: m[4] };
}

function checkRegistry(pin, registry, waiverRaw) {
    const newest = newestStable(registry.time);
    if (newest === null) throw new PolicyError('could not determine: the registry lists no stable electron release');
    if (newest !== registry.latest) {
        throw new PolicyError(`could not determine: the registry's newest stable electron is ${newest} but its latest tag is ${registry.latest}`);
    }
    if (compareVersions(newest, pin) > 0) {
        const waiver = parseWaiver(waiverRaw);
        if (waiver !== null && waiver.pin === pin && waiver.newest === newest) {
            return `WAIVED: electron pin ${pin} lags the newest stable ${newest}; waived by ${waiver.who} ${waiver.date}`;
        }
        const have = waiver === null ? '' : ` (the waiver given names ${waiver.pin} and ${waiver.newest}, which is not this pair)`;
        throw new PolicyError(`electron ${newest} is the newest stable and the pin is ${pin}${have}: bump the pin, or the operator approves shipping on ${pin} and you rerun with ${WAIVER_VAR}="${pin}:${newest}:<operator> <YYYY-MM-DD>" macOS/scripts/release-build.sh <same arguments>`);
    }
    if (compareVersions(newest, pin) < 0) {
        throw new PolicyError(`electron ${pin} is not on the registry's stable list (newest stable is ${newest}): pin the newest stable`);
    }
    return null;
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

function check(macOSDir, registrySource = fetchRegistry, env = process.env) {
    const pkg = JSON.parse(fs.readFileSync(path.join(macOSDir, 'package.json'), 'utf8'));
    const pins = parsePins(pkg);
    checkBuildConfig(pkg, pins);
    checkInstalled(macOSDir, pins);
    return checkRegistry(pins.electron, registrySource(), env[WAIVER_VAR]);
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
        const hasArm64 = zips.some((u) => /arm64/.test(u) && !/universal/.test(u));
        const hasX64 = zips.some((u) => !/arm64|universal/.test(u));
        if (zips.length !== 2 || !hasArm64 || !hasX64) {
            throw new PolicyError(`latest-mac.yml must name two split arch zips (arm64 and x64, no universal), it names: ${zips.join(', ') || 'none'}`);
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
            const waived = check(macOSDir);
            if (waived) process.stderr.write(`electron-policy: ${waived}\n`);
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
    PINNED_PACKAGES, WAIVER_VAR, MACOS_FLOOR, MANIFEST_MIN_SYSTEM_VERSION, PolicyError,
    parsePins, checkBuildConfig, checkInstalled, compareVersions, newestStable, parseWaiver, checkRegistry, check, outputDirFromArgs, finish,
};
