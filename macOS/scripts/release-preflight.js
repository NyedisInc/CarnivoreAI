'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const DIST_FILES = ['LICENSE', 'LICENSES.chromium.html'];

class PreflightError extends Error {}

function run(cmd, args, cwd, hint) {
    try {
        execFileSync(cmd, args, { cwd, stdio: 'inherit', timeout: 600000 });
    } catch (err) {
        throw new PreflightError(`\`${cmd} ${args.join(' ')}\` failed in ${cwd} (${err.code || err.status || err.name}): ${hint}`);
    }
}

function electronProblems(macOSDir, pin) {
    const root = path.join(macOSDir, 'node_modules', 'electron');
    let installed = 'not installed';
    try {
        installed = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).version;
    } catch (err) {
        if (err.code !== 'ENOENT') installed = `unreadable (${err.code || err.name})`;
    }
    if (installed !== pin) return [`electron pinned ${pin} but installed ${installed}`];
    const problems = [];
    let binary = null;
    try {
        binary = fs.readFileSync(path.join(root, 'path.txt'), 'utf8').trim();
    } catch (err) {
        if (err.code !== 'ENOENT') throw err;
    }
    if (!binary || !fs.existsSync(path.join(root, 'dist', binary))) problems.push('the Electron binary is missing');
    for (const f of DIST_FILES) if (!fs.existsSync(path.join(root, 'dist', f))) problems.push(`dist/${f} is missing`);
    return problems;
}

function preflight(macOSDir) {
    const pkg = JSON.parse(fs.readFileSync(path.join(macOSDir, 'package.json'), 'utf8'));
    const pin = (pkg.dependencies && pkg.dependencies.electron) || (pkg.devDependencies && pkg.devDependencies.electron);
    const webDir = path.resolve(macOSDir, '..', 'web');
    run('npm', ['ci'], macOSDir, 'macOS/package-lock.json is out of sync with package.json: fix the lockfile');
    run('npm', ['ci'], webDir, 'web/package-lock.json is out of sync with web/package.json: fix the lockfile');
    if (!fs.existsSync(path.join(webDir, 'node_modules'))) throw new PreflightError(`${webDir}/node_modules is missing after npm ci (gen_notices needs it)`);
    if (!/^\d+\.\d+\.\d+$/.test(String(pin))) return;
    let problems = electronProblems(macOSDir, pin);
    if (problems.length > 0 && problems[0].startsWith('electron pinned')) {
        throw new PreflightError(`${problems[0]} after a clean install: remove macOS/node_modules and rerun`);
    }
    if (problems.length > 0) {
        process.stderr.write(`release-preflight: ${problems.join('; ')}: running Electron's own install.js once\n`);
        run(process.execPath, [path.join(macOSDir, 'node_modules', 'electron', 'install.js')], macOSDir, 'Electron could not fetch its binary');
        problems = electronProblems(macOSDir, pin);
    }
    if (problems.length > 0) throw new PreflightError(`electron ${pin} is not whole after install.js: ${problems.join('; ')}`);
}

if (require.main === module) {
    try {
        preflight(path.resolve(__dirname, '..'));
    } catch (err) {
        if (!(err instanceof PreflightError)) throw err;
        process.stderr.write(`release-preflight: refusing the build: ${err.message}\n`);
        process.exitCode = 1;
    }
}

module.exports = { preflight, electronProblems, PreflightError };
