'use strict';


const fs = require('fs');
const path = require('path');
const { execFileSync, spawn } = require('child_process');
const os = require('os');
const { BUNDLE_ID } = require('./product-identity');

const LEGACY_LABEL = 'com.cloudecode.menubar';

const LOG_DIR_NAME = 'Carnivore';
const LOG_FILE_NAME = 'menubar.log';
const ERROR_LOG_FILE_NAME = 'menubar-error.log';
const LOG_DIR_MODE = 0o700;

function xmlEscape(text) {
  return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

class LaunchAgentInstaller {
  constructor() {
    this.launchAgentDir = path.join(os.homedir(), 'Library', 'LaunchAgents');

    this.label = BUNDLE_ID;
    this.plistName = `${this.label}.plist`;
    this.plistPath = path.join(this.launchAgentDir, this.plistName);

    this.logDir = path.join(os.homedir(), 'Library', 'Logs', LOG_DIR_NAME);
    this.logPath = path.join(this.logDir, LOG_FILE_NAME);
    this.errorLogPath = path.join(this.logDir, ERROR_LOG_FILE_NAME);

    this.legacyLabel = LEGACY_LABEL;
    this.legacyPlistName = `${this.legacyLabel}.plist`;
    this.legacyPlistPath = path.join(this.launchAgentDir, this.legacyPlistName);
  }

  isEnabled() {
    if (!fs.existsSync(this.plistPath)) return false;
    return this._isLabelLoaded(this.label) || this._plistIsValid();
  }

  _plistIsValid() {
    try {
      execFileSync('/usr/bin/plutil', ['-lint', this.plistPath], { stdio: 'ignore' });
      return true;
    } catch (err) {
      return typeof err.status !== 'number';
    }
  }

  _buildPlist(programArgs) {
    const argv = [].concat(programArgs);
    const argXml = argv.map((a) => `        <string>${xmlEscape(a)}</string>`).join('\n');
    return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${xmlEscape(this.label)}</string>
    <key>ProgramArguments</key>
    <array>
${argXml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>${xmlEscape(this.logPath)}</string>
    <key>StandardErrorPath</key>
    <string>${xmlEscape(this.errorLogPath)}</string>
</dict>
</plist>`;
  }

  _ensureLogDir() {
    fs.mkdirSync(this.logDir, { recursive: true, mode: LOG_DIR_MODE });
  }

  dropPlistFile() {
    try {
      fs.unlinkSync(this.plistPath);
    } catch (err) {
      if (err.code !== 'ENOENT') throw err;
    }
  }

  _isLabelLoaded(label) {
    try {
      execFileSync('launchctl', ['list', label], { stdio: 'ignore' });
      return true;
    } catch (err) {
      return false;
    }
  }

  _unloadLabel(label, plistPath) {
    if (!fs.existsSync(plistPath)) {
      return true;
    }
    try {
      execFileSync('launchctl', ['unload', plistPath], { stdio: 'ignore' });
    } catch (err) {
    }
    return !this._isLabelLoaded(label);
  }

  enable(appPath) {
    console.log('Enabling auto-launch...');
    console.log(`App path: ${appPath}`);

    if (!fs.existsSync(this.launchAgentDir)) {
      fs.mkdirSync(this.launchAgentDir, { recursive: true });
    }

    this._ensureLogDir();
    fs.writeFileSync(this.plistPath, this._buildPlist(appPath), 'utf8');
    console.log(`Created LaunchAgent plist at: ${this.plistPath}`);

    try {
      execFileSync('launchctl', ['load', this.plistPath], { stdio: 'inherit' });
      console.log('LaunchAgent loaded successfully');
    } catch (err) {
      console.error('Failed to load LaunchAgent:', err.message);
    }
  }

  disable() {
    console.log('Disabling auto-launch...');

    if (!fs.existsSync(this.plistPath)) {
      console.log('LaunchAgent plist not found, nothing to disable');
      return;
    }

    if (process.argv.includes('--login-launch')) {
      try {
        spawn('/bin/sh', ['-c', 'while kill -0 "$1" 2>/dev/null; do sleep 0.1; done; exec launchctl remove "$2"', 'sh', String(process.pid), this.label],
          { detached: true, stdio: 'ignore' }).unref();
      } catch (err) {
        console.error('Failed to schedule LaunchAgent removal:', err.message);
      }
    } else {
      try {
        execFileSync('launchctl', ['unload', this.plistPath], { stdio: 'inherit' });
        console.log('LaunchAgent unloaded successfully');
      } catch (err) {
        console.error('Failed to unload LaunchAgent:', err.message);
      }
    }

    try {
      fs.unlinkSync(this.plistPath);
      console.log('LaunchAgent plist removed');
    } catch (err) {
      console.error('Failed to remove plist:', err.message);
    }
  }

  toggle(appPath) {
    if (this.isEnabled()) {
      this.disable();
    } else {
      this.enable(appPath);
    }
  }

  /* once per launch true only when this */
  migrateLegacyIfNeeded(appPath) {
    const legacyExists = fs.existsSync(this.legacyPlistPath);

    if (!legacyExists) {
      return { ran: false, migrated: false, details: 'no legacy plist present' };
    }

    // already exists

    const legacyWasLoaded = this._isLabelLoaded(this.legacyLabel);

    const unloadOk = this._unloadLabel(this.legacyLabel, this.legacyPlistPath);
    if (!unloadOk) {
      return {
        ran: true,
        migrated: false,
        details: 'could not unload the legacy LaunchAgent; left the legacy install in place',
      };
    }

    if (!fs.existsSync(this.launchAgentDir)) {
      fs.mkdirSync(this.launchAgentDir, { recursive: true });
    }
    try {
      this._ensureLogDir();
      fs.writeFileSync(this.plistPath, this._buildPlist(appPath), 'utf8');
    } catch (err) {
      this._restoreLegacy(legacyWasLoaded);
      return {
        ran: true,
        migrated: false,
        details: `failed writing the new plist (${err.message}); restored the legacy LaunchAgent`,
      };
    }

    if (legacyWasLoaded) {
      try {
        execFileSync('launchctl', ['load', this.plistPath], { stdio: 'ignore' });
      } catch (err) {
      }
      if (!this._isLabelLoaded(this.label)) {
        this._restoreLegacy(legacyWasLoaded);
        return {
          ran: true,
          migrated: false,
          details: 'wrote the new plist but it did not load; restored the legacy LaunchAgent',
        };
      }
    }

    return this._finishLegacyCleanup();
  }

  /* once per launch */
  upgradePlistIfNeeded(appPath) {
    if (!fs.existsSync(this.plistPath)) {
      return { ran: false, upgraded: false, details: 'no current plist to upgrade' };
    }

    let previousContent;
    try {
      previousContent = fs.readFileSync(this.plistPath, 'utf8');
    } catch (err) {
      return {
        ran: true,
        upgraded: false,
        details: `could not read the current plist (${err.message}); left it in place`,
      };
    }

    const argsCurrent = [].concat(appPath).every((a) => previousContent.includes(`<string>${xmlEscape(a)}</string>`));
    const logsCurrent = previousContent.includes(`<string>${xmlEscape(this.logPath)}</string>`)
      && previousContent.includes(`<string>${xmlEscape(this.errorLogPath)}</string>`);
    if (previousContent.includes('<key>KeepAlive</key>') && argsCurrent && logsCurrent) {
      return { ran: true, upgraded: false, details: 'plist already has KeepAlive and the current log paths' };
    }

    const bakPath = `${this.plistPath}.bak`;
    const tmpPath = `${this.plistPath}.upgrade-tmp-${process.pid}`;
    try {
      this._ensureLogDir();
      fs.writeFileSync(bakPath, previousContent, 'utf8');
      fs.writeFileSync(tmpPath, this._buildPlist(appPath), 'utf8');
      fs.renameSync(tmpPath, this.plistPath);
    } catch (err) {
      try {
        fs.rmSync(tmpPath, { force: true });
      } catch (cleanupErr) {
      }
      return {
        ran: true,
        upgraded: false,
        details: `failed writing the upgraded plist (${err.message}); left the previous plist in place`,
      };
    }

    return {
      ran: true,
      upgraded: true,
      details: 'rewrote the plist on disk (KeepAlive, current argv and log paths); takes effect at next load (login, reboot, or deploy bootstrap), not this run',
    };
  }

  _finishLegacyCleanup() {
    if (this._isLabelLoaded(this.legacyLabel)) {
      const unloadOk = this._unloadLabel(this.legacyLabel, this.legacyPlistPath);
      if (!unloadOk) {
        return {
          ran: true,
          migrated: false,
          details: 'legacy LaunchAgent was reloaded and could not be unloaded again; left in place',
        };
      }
    }

    try {
      if (fs.existsSync(this.legacyPlistPath)) {
        fs.unlinkSync(this.legacyPlistPath);
      }
    } catch (err) {
      return {
        ran: true,
        migrated: false,
        details: `new LaunchAgent is loaded, but could not remove the legacy plist file (${err.message})`,
      };
    }

    return { ran: true, migrated: true, details: 'migrated to the new LaunchAgent label' };
  }

  _restoreLegacy(shouldBeLoaded) {
    if (!shouldBeLoaded) {
      return;
    }
    if (!fs.existsSync(this.legacyPlistPath)) {
      return;
    }
    try {
      execFileSync('launchctl', ['load', this.legacyPlistPath], { stdio: 'ignore' });
      console.log('[launchagent] restored the legacy LaunchAgent after a failed migration step');
    } catch (err) {
      console.error('[launchagent] could not restore the legacy LaunchAgent:', err.message);
    }
  }
}

module.exports = LaunchAgentInstaller;
