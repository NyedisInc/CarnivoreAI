// WHY THIS FILE EXISTS
// once:

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const macDir = path.join(here, '..', 'macOS');

const LaunchAgentInstaller = require(path.join(macDir, 'launchagent-installer.js'));

const stubLaunchctlDir = fs.mkdtempSync(path.join(os.tmpdir(), 'stub-launchctl-'));
fs.writeFileSync(path.join(stubLaunchctlDir, 'launchctl'), '#!/bin/sh\nexit 113\n', { mode: 0o755 });
process.env.PATH = `${stubLaunchctlDir}${path.delimiter}${process.env.PATH}`;

let passed = 0;
let failed = 0;
const pending = [];

function test(name, fn) {
  pending.push([name, fn]);
}

function makeIsolatedInstaller() {
  const installer = new LaunchAgentInstaller();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'launchagent-test-'));
  installer.launchAgentDir = dir;
  installer.plistName = 'test.launchagent.plist';
  installer.plistPath = path.join(dir, installer.plistName);
  installer.logDir = path.join(dir, 'logs', 'Carnivore');
  installer.logPath = path.join(installer.logDir, 'menubar.log');
  installer.errorLogPath = path.join(installer.logDir, 'menubar-error.log');
  installer.legacyPlistName = 'test.launchagent.legacy.plist';
  installer.legacyPlistPath = path.join(dir, installer.legacyPlistName);
  return { installer, dir };
}

const OLD_STYLE_PLIST = (label, appPath) => `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${appPath}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/old-style.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/old-style-error.log</string>
</dict>
</plist>`;


test('_buildPlist: includes KeepAlive/SuccessfulExit=false and ThrottleInterval=10', () => {
  const { installer } = makeIsolatedInstaller();
  const xml = installer._buildPlist('/Applications/Carnivore.app/Contents/MacOS/Carnivore');

  const keepAliveAt = xml.indexOf('<key>KeepAlive</key>');
  assert.notEqual(keepAliveAt, -1, 'no KeepAlive key at all');
  const keepAliveBlock = xml.slice(keepAliveAt, keepAliveAt + 200);
  assert.ok(
    /<key>SuccessfulExit<\/key>\s*<false\s*\/>/.test(keepAliveBlock),
    'KeepAlive is not scoped to SuccessfulExit=false, so launchd would relaunch ' +
    'after every exit including a clean Quit'
  );

  assert.ok(
    /<key>ThrottleInterval<\/key>\s*<integer>10<\/integer>/.test(xml),
    'ThrottleInterval 10 is missing, so a crash loop has no floor'
  );
});

test('_buildPlist: still emits Label, ProgramArguments and RunAtLoad (no regression)', () => {
  const { installer } = makeIsolatedInstaller();
  const appPath = '/Applications/Carnivore.app/Contents/MacOS/Carnivore';
  const xml = installer._buildPlist(appPath);

  assert.ok(xml.includes(`<string>${installer.label}</string>`), 'Label missing');
  assert.ok(xml.includes(`<string>${appPath}</string>`), 'ProgramArguments missing appPath');
  assert.ok(/<key>RunAtLoad<\/key>\s*<true\s*\/>/.test(xml), 'RunAtLoad missing');
});

test('_buildPlist: output is a valid plist (plutil -lint)', () => {
  const { installer, dir } = makeIsolatedInstaller();
  const xml = installer._buildPlist('/Applications/Carnivore.app/Contents/MacOS/Carnivore');
  const tmpPlist = path.join(dir, 'lint-check.plist');
  fs.writeFileSync(tmpPlist, xml, 'utf8');

  try {
    execFileSync('plutil', ['-lint', tmpPlist], { stdio: 'pipe' });
  } catch (err) {
    assert.fail(
      `plutil -lint rejected the generated plist: ${err.stderr ? err.stderr.toString() : err.message}`
    );
  }
});

test('_buildPlist: an app path with & < > and quotes is escaped, lints, and reads back; upgradePlistIfNeeded sees it as current', () => {
  const { installer, dir } = makeIsolatedInstaller();
  const exe = `/Users/me/Apps & Tools <x> "q" 'z'/Carnivore.app/Contents/MacOS/Carnivore`;
  const xml = installer._buildPlist([exe]);
  assert.ok(xml.includes('Apps &amp; Tools &lt;x&gt; &quot;q&quot; &apos;z&apos;'));
  const file = path.join(dir, 'amp.plist');
  fs.writeFileSync(file, xml, 'utf8');
  execFileSync('plutil', ['-lint', file], { stdio: 'pipe' });
  const parsed = JSON.parse(execFileSync('plutil', ['-convert', 'json', '-o', '-', file]).toString());
  assert.deepEqual(parsed.ProgramArguments, [exe], 'launchd reads the exact path back');
  fs.writeFileSync(installer.plistPath, xml, 'utf8');
  installer._ensureLogDir();
  assert.equal(installer.upgradePlistIfNeeded([exe]).upgraded, false, 'an escaped current plist is not rewritten on every launch');
});

test('isEnabled: a plist launchd cannot parse is not "start at login"; a valid one is', () => {
  const { installer } = makeIsolatedInstaller();
  installer.label = 'ai.carnivore.test-not-loaded-' + process.pid;
  assert.equal(installer.isEnabled(), false, 'no file');
  fs.writeFileSync(installer.plistPath, '<?xml version="1.0"?><plist version="1.0"><dict><key>A</key><string>a & b</string></dict></plist>', 'utf8');
  assert.equal(installer.isEnabled(), false, 'a broken file and nothing loaded reads off');
  fs.writeFileSync(installer.plistPath, installer._buildPlist(['/Applications/Carnivore.app/Contents/MacOS/Carnivore']), 'utf8');
  assert.equal(installer.isEnabled(), true);
});


test('constructor: default log paths are absolute under ~/Library/Logs/Carnivore, not /tmp', () => {
  const installer = new LaunchAgentInstaller();
  const dir = path.join(os.homedir(), 'Library', 'Logs', 'Carnivore');
  assert.equal(installer.logDir, dir);
  assert.equal(installer.logPath, path.join(dir, 'menubar.log'));
  assert.equal(installer.errorLogPath, path.join(dir, 'menubar-error.log'));
  const xml = installer._buildPlist('/Applications/Carnivore.app/Contents/MacOS/Carnivore');
  assert.ok(xml.includes(`<string>${installer.logPath}</string>`));
  assert.ok(xml.includes(`<string>${installer.errorLogPath}</string>`));
  assert.ok(!xml.includes('/tmp/'), 'plist still names a /tmp path');
});

test('_ensureLogDir: creates the folder with mode 0700 and is idempotent', () => {
  const { installer } = makeIsolatedInstaller();
  assert.ok(!fs.existsSync(installer.logDir));
  installer._ensureLogDir();
  installer._ensureLogDir();
  assert.equal(fs.statSync(installer.logDir).mode & 0o777, 0o700);
});

test('upgradePlistIfNeeded: a plist with the old /tmp log paths is rewritten to the new paths and creates the folder', () => {
  const { installer } = makeIsolatedInstaller();
  const appPath = '/Applications/Carnivore.app/Contents/MacOS/Carnivore';
  const stale = installer._buildPlist(appPath)
    .replace(installer.logPath, '/tmp/carnivore-menubar.log')
    .replace(installer.errorLogPath, '/tmp/carnivore-menubar-error.log');
  fs.writeFileSync(installer.plistPath, stale, 'utf8');

  const result = installer.upgradePlistIfNeeded(appPath);

  assert.equal(result.upgraded, true, result.details);
  const now = fs.readFileSync(installer.plistPath, 'utf8');
  assert.ok(now.includes(`<string>${installer.logPath}</string>`));
  assert.ok(now.includes(`<string>${installer.errorLogPath}</string>`));
  assert.ok(!now.includes('/tmp/'));
  assert.equal(fs.readFileSync(`${installer.plistPath}.bak`, 'utf8'), stale);
  assert.ok(fs.existsSync(installer.logDir), 'log folder was not created');
});

test('upgradePlistIfNeeded: a current plist is left byte-identical and creates no folder', () => {
  const { installer } = makeIsolatedInstaller();
  const appPath = '/Applications/Carnivore.app/Contents/MacOS/Carnivore';
  const current = installer._buildPlist(appPath);
  fs.writeFileSync(installer.plistPath, current, 'utf8');
  const result = installer.upgradePlistIfNeeded(appPath);
  assert.equal(result.upgraded, false);
  assert.equal(fs.readFileSync(installer.plistPath, 'utf8'), current);
  assert.ok(!fs.existsSync(installer.logDir));
});

test('upgradePlistIfNeeded: an old plist without the login-launch marker is rewritten to carry it (R1-03)', () => {
  const { installer } = makeIsolatedInstaller();
  const exe = '/Applications/Carnivore.app/Contents/MacOS/Carnivore';
  fs.writeFileSync(installer.plistPath, installer._buildPlist([exe]), 'utf8');
  const result = installer.upgradePlistIfNeeded([exe, '--login-launch']);
  assert.equal(result.upgraded, true, result.details);
  assert.ok(fs.readFileSync(installer.plistPath, 'utf8').includes('<string>--login-launch</string>'));
  assert.equal(installer.upgradePlistIfNeeded([exe, '--login-launch']).upgraded, false, 'a second run is a no-op');
});

test('upgradePlistIfNeeded: login item disabled (no plist) creates neither plist nor folder', () => {
  const { installer } = makeIsolatedInstaller();
  const result = installer.upgradePlistIfNeeded('/Applications/Carnivore.app/Contents/MacOS/Carnivore');
  assert.equal(result.ran, false);
  assert.ok(!fs.existsSync(installer.plistPath));
  assert.ok(!fs.existsSync(installer.logDir));
});


test('upgradePlistIfNeeded: no-op when there is no current plist at all', () => {
  const { installer } = makeIsolatedInstaller();
  const result = installer.upgradePlistIfNeeded('/Applications/Carnivore.app/Contents/MacOS/Carnivore');
  assert.deepEqual(result, { ran: false, upgraded: false, details: 'no current plist to upgrade' });
});

test('upgradePlistIfNeeded: rewrites an old-style plist on disk to add KeepAlive, keeping a .bak', () => {
  const { installer } = makeIsolatedInstaller();
  const appPath = '/Applications/Carnivore.app/Contents/MacOS/Carnivore';
  const oldContent = OLD_STYLE_PLIST(installer.label, appPath);
  fs.writeFileSync(installer.plistPath, oldContent, 'utf8');

  const result = installer.upgradePlistIfNeeded(appPath);

  assert.equal(result.ran, true);
  assert.equal(result.upgraded, true, `expected an upgrade, got: ${result.details}`);

  const rewritten = fs.readFileSync(installer.plistPath, 'utf8');
  assert.ok(rewritten.includes('<key>KeepAlive</key>'), 'plist was not actually rewritten with KeepAlive');
  assert.ok(rewritten.includes(`<string>${appPath}</string>`), 'ProgramArguments lost across the upgrade');

  const bakPath = `${installer.plistPath}.bak`;
  assert.ok(fs.existsSync(bakPath), 'no .bak of the previous plist was kept');
  assert.equal(fs.readFileSync(bakPath, 'utf8'), oldContent, '.bak does not match the pre-upgrade content');

  const dirEntries = fs.readdirSync(path.dirname(installer.plistPath));
  assert.ok(
    !dirEntries.some((name) => name.includes('.upgrade-tmp-')),
    'a temp file from the atomic rewrite was left behind'
  );
});

test('upgradePlistIfNeeded: NEVER invokes launchctl for the app\'s own label (negative control)', () => {
  const { installer } = makeIsolatedInstaller();
  const appPath = '/Applications/Carnivore.app/Contents/MacOS/Carnivore';
  fs.writeFileSync(installer.plistPath, OLD_STYLE_PLIST(installer.label, appPath), 'utf8');

  const fakeBinDir = fs.mkdtempSync(path.join(os.tmpdir(), 'fake-launchctl-'));
  const invocationLog = path.join(fakeBinDir, 'invocations.log');
  const fakeLaunchctl = path.join(fakeBinDir, 'launchctl');
  fs.writeFileSync(fakeLaunchctl, `#!/bin/sh\necho "$@" >> "${invocationLog}"\nexit 0\n`, 'utf8');
  fs.chmodSync(fakeLaunchctl, 0o755);

  const originalPath = process.env.PATH;
  process.env.PATH = `${fakeBinDir}${path.delimiter}${originalPath}`;
  let result;
  try {
    result = installer.upgradePlistIfNeeded(appPath);
  } finally {
    process.env.PATH = originalPath;
  }

  assert.equal(result.upgraded, true, `expected the upgrade to succeed, got: ${result.details}`);
  assert.ok(
    !fs.existsSync(invocationLog),
    'upgradePlistIfNeeded invoked launchctl while running as its own label\'s job - ' +
    `this would SIGTERM the calling app. Invocations logged: ` +
    (fs.existsSync(invocationLog) ? fs.readFileSync(invocationLog, 'utf8') : '(none)')
  );
});

test('upgradePlistIfNeeded: idempotent - a second call on an already-upgraded plist is a no-op', () => {
  const { installer } = makeIsolatedInstaller();
  const appPath = '/Applications/Carnivore.app/Contents/MacOS/Carnivore';
  fs.writeFileSync(installer.plistPath, OLD_STYLE_PLIST(installer.label, appPath), 'utf8');

  const first = installer.upgradePlistIfNeeded(appPath);
  assert.equal(first.upgraded, true);
  const afterFirst = fs.readFileSync(installer.plistPath, 'utf8');

  const second = installer.upgradePlistIfNeeded(appPath);
  assert.equal(second.ran, true);
  assert.equal(second.upgraded, false, 'a plist that already has KeepAlive was rewritten again');
  assert.equal(second.details, 'plist already has KeepAlive and the current log paths');

  const afterSecond = fs.readFileSync(installer.plistPath, 'utf8');
  assert.equal(afterSecond, afterFirst, 'the file changed on a call that should have been a no-op');
});

test('upgradePlistIfNeeded: a plist that already has KeepAlive (current _buildPlist output) is left untouched', () => {
  const { installer } = makeIsolatedInstaller();
  const appPath = '/Applications/Carnivore.app/Contents/MacOS/Carnivore';
  const current = installer._buildPlist(appPath);
  fs.writeFileSync(installer.plistPath, current, 'utf8');

  const result = installer.upgradePlistIfNeeded(appPath);
  assert.equal(result.ran, true);
  assert.equal(result.upgraded, false);
  assert.equal(fs.readFileSync(installer.plistPath, 'utf8'), current);
});

const ELECTRON_BIN = '/x/cloudecode/macOS/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron';
const APP_DIR = '/x/cloudecode/macOS';

function programArgs(xml) {
  const block = /<key>ProgramArguments<\/key>\s*<array>([\s\S]*?)<\/array>/.exec(xml)[1];
  return [...block.matchAll(/<string>(.*?)<\/string>/g)].map((m) => m[1]);
}

test('_buildPlist: packaged mode runs only the app executable', () => {
  const { installer } = makeIsolatedInstaller();
  const exe = '/Applications/Carnivore.app/Contents/MacOS/Carnivore';
  assert.deepEqual(programArgs(installer._buildPlist([exe])), [exe]);
  assert.deepEqual(programArgs(installer._buildPlist(exe)), [exe]);
});

test('_buildPlist: dev mode runs Electron WITH the app folder as its argument', () => {
  const { installer } = makeIsolatedInstaller();
  assert.deepEqual(programArgs(installer._buildPlist([ELECTRON_BIN, APP_DIR])), [ELECTRON_BIN, APP_DIR]);
});

test('upgradePlistIfNeeded: repairs a KeepAlive plist whose argv is the bare Electron binary', () => {
  const { installer } = makeIsolatedInstaller();
  fs.writeFileSync(installer.plistPath, installer._buildPlist(ELECTRON_BIN), 'utf8');
  const result = installer.upgradePlistIfNeeded([ELECTRON_BIN, APP_DIR]);
  assert.equal(result.upgraded, true);
  assert.deepEqual(programArgs(fs.readFileSync(installer.plistPath, 'utf8')), [ELECTRON_BIN, APP_DIR]);
});

(async () => {
  console.log('launchagent installer: KeepAlive/ThrottleInterval plist keys and the upgrade path');
  for (const [name, fn] of pending) {
    try {
      await fn();
      console.log(`  ok   ${name}`);
      passed += 1;
    } catch (err) {
      console.log(`  FAIL ${name}`);
      console.log(`       ${err.message}`);
      failed += 1;
    }
  }
  console.log(`\nlaunchagent installer: ${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASS');
})();

test('disable: from a login-launched app the plist is removed and launchctl unload never runs (it would kill the app first)', () => {
  const { installer } = makeIsolatedInstaller();
  fs.writeFileSync(installer.plistPath, OLD_STYLE_PLIST(installer.label, '/Applications/Carnivore.app/Contents/MacOS/Carnivore'), 'utf8');
  const fakeBinDir = fs.mkdtempSync(path.join(os.tmpdir(), 'fake-launchctl-'));
  const invocationLog = path.join(fakeBinDir, 'invocations.log');
  fs.writeFileSync(path.join(fakeBinDir, 'launchctl'), `#!/bin/sh\necho "$@" >> "${invocationLog}"\nexit 0\n`, 'utf8');
  fs.chmodSync(path.join(fakeBinDir, 'launchctl'), 0o755);
  const originalPath = process.env.PATH;
  const originalArgv = process.argv;
  process.env.PATH = `${fakeBinDir}${path.delimiter}${originalPath}`;
  try {
    process.argv = [...originalArgv, '--login-launch'];
    installer.disable();
    assert.ok(!fs.existsSync(installer.plistPath), 'the plist must be gone so the next login starts nothing');
    assert.ok(!fs.existsSync(invocationLog), 'launchctl ran from the launchd job itself');
    fs.writeFileSync(installer.plistPath, OLD_STYLE_PLIST(installer.label, '/x'), 'utf8');
    process.argv = originalArgv.filter((a) => a !== '--login-launch');
    installer.disable();
    assert.match(fs.readFileSync(invocationLog, 'utf8'), /^unload /, 'a manually opened app still unloads the job');
    assert.ok(!fs.existsSync(installer.plistPath));
  } finally {
    process.argv = originalArgv;
    process.env.PATH = originalPath;
  }
});

test('disable: from a login-launched app the loaded job is removed by label even when the app dies by SIGKILL (#2497)', () => {
  const { installer } = makeIsolatedInstaller();
  fs.writeFileSync(installer.plistPath, OLD_STYLE_PLIST(installer.label, '/x'), 'utf8');
  const fakeBinDir = fs.mkdtempSync(path.join(os.tmpdir(), 'fake-launchctl-'));
  const invocationLog = path.join(fakeBinDir, 'invocations.log');
  fs.writeFileSync(path.join(fakeBinDir, 'launchctl'), `#!/bin/sh\necho "$@" >> "${invocationLog}"\nexit 0\n`, 'utf8');
  fs.chmodSync(path.join(fakeBinDir, 'launchctl'), 0o755);
  const script = `const L=require(${JSON.stringify(path.join(macDir, 'launchagent-installer.js'))});const C=L.LaunchAgentInstaller||L;const i=new C();`
    + `i.plistPath=${JSON.stringify(installer.plistPath)};i.label=${JSON.stringify(installer.label)};i.disable();setTimeout(()=>process.kill(process.pid,'SIGKILL'),300);setTimeout(()=>{},5000);`;
  const env = { ...process.env, PATH: `${fakeBinDir}${path.delimiter}${process.env.PATH}` };
  const child = spawnSync(process.execPath, ['-e', script, '--', '--login-launch'], { env, stdio: 'ignore' });
  assert.equal(child.signal, 'SIGKILL', 'the app really died by SIGKILL, so no exit hook ran');
  const deadline = Date.now() + 5000;
  while (!fs.existsSync(invocationLog) && Date.now() < deadline) Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 50);
  assert.ok(fs.existsSync(invocationLog), 'a watcher outside the app removed the job');
  assert.equal(fs.readFileSync(invocationLog, 'utf8').trim(), `remove ${installer.label}`);
});
