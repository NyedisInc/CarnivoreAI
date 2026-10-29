
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { buildOtpauthUri } = require('./otpauth-uri');

const SAFE_CSS_VALUE = /^[#a-zA-Z0-9(),.%\s'"-]+$/;
const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

const THEME_KEYS = Object.freeze([
  '--color-bg', '--color-fg', '--color-fg-muted', '--color-fg-faint',
  '--color-accent', '--color-border', '--font-mono', '--radius-sm',
]);

function readTotpSecret(serverDir) {
  try {
    const text = fs.readFileSync(path.join(serverDir, '.env'), 'utf8');
    for (const line of text.split('\n')) {
      const m = /^\s*TOTP_SECRET\s*=\s*(.+?)\s*$/.exec(line);
      if (m) return m[1].replace(/^['"]|['"]$/g, '');
    }
    return null;
  } catch (err) {
    return null;
  }
}

function readThemeVars(projectRoot) {
  try {
    const file = path.join(projectRoot, 'client', 'css', 'themes', 'carnivore', 'theme.json');
    const vars = (JSON.parse(fs.readFileSync(file, 'utf8')) || {}).cssVars || {};
    const out = {};
    for (const key of THEME_KEYS) {
      const v = vars[key];
      if (typeof v === 'string' && SAFE_CSS_VALUE.test(v)) out[key] = v;
    }
    return out;
  } catch (err) {
    return {};
  }
}

function computerDisplayName() {
  try {
    const name = execFileSync('/usr/sbin/scutil', ['--get', 'ComputerName'],
      { encoding: 'utf8', timeout: 2000 }).trim();
    if (name) return name;
  } catch (err) {
  }
  return os.hostname();
}

const PAIRING_COPY = Object.freeze({
  title: 'pair your authenticator',
  body: 'Scan this QR with Google Authenticator, 1Password, Authy, or any TOTP app.',
  aria: 'TOTP QR code',
  footer: 'Paired already? You can close this window.',
});

function buildHtml(qrSvg, vars, copy) {
  const words = copy || PAIRING_COPY;
  const esc = (text) => String(text).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
  const root = Object.entries(vars).map(([k, v]) => `${k}:${v};`).join('');
  const has = (k) => Object.prototype.hasOwnProperty.call(vars, k);
  const use = (prop, key) => (has(key) ? `${prop}:var(${key});` : '');
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><style>
    :root{${root}}
    body{margin:0;padding:32px;${use('font-family', '--font-mono')}${use('background', '--color-bg')}${use('color', '--color-fg')}
      display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;box-sizing:border-box;}
    .row{width:100%;max-width:340px;padding-bottom:10px;margin-bottom:18px;box-shadow:0 1px 0 0 ${has('--color-border') ? 'var(--color-border)' : 'transparent'};}
    h1{margin:0;font-size:11px;font-weight:600;letter-spacing:0.12em;text-transform:uppercase;${use('color', '--color-accent')}}
    p{margin:0 0 20px 0;font-size:13px;${use('color', '--color-fg-muted')}text-align:center;max-width:340px;line-height:1.5;}
    .qr{width:320px;height:320px;background:#ffffff;${use('border-radius', '--radius-sm')}padding:14px;
      box-sizing:border-box;outline:1px solid ${has('--color-border') ? 'var(--color-border)' : 'transparent'};}
    .qr svg{width:100%;height:100%;display:block;}
    .footer{margin-top:20px;font-size:11px;${use('color', '--color-fg-faint')}}
  </style></head><body>
    <div class="row"><h1>${esc(words.title)}</h1></div>
    <p>${esc(words.body)}</p>
    <div class="qr" role="img" aria-label="${esc(words.aria)}">${qrSvg}</div>
    <div class="footer">${esc(words.footer)}</div>
  </body></html>`;
}

async function showQrPairingWindow({ serverDir, projectRoot, BrowserWindow, QRCode, computerName }) {
  try {
    const secret = readTotpSecret(serverDir);
    if (!secret) {
      throw new Error('TOTP secret not readable from the server .env - has setup run?');
    }
    const qr = QRCode || require('qrcode');
    const qrSvg = await qr.toString(
      buildOtpauthUri(secret, computerName === undefined ? computerDisplayName() : computerName),
      { type: 'svg', margin: 2, errorCorrectionLevel: 'M',
        color: { dark: '#000000', light: '#ffffff' } }
    );
    const vars = readThemeVars(projectRoot);
    const options = {
      width: 420, height: 520, resizable: false, minimizable: false,
      maximizable: false, fullscreenable: false, show: false,
      title: 'Carnivore: pair your authenticator',
      webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true },
    };
    if (vars['--color-bg'] && HEX_COLOR.test(vars['--color-bg'])) {
      options.backgroundColor = vars['--color-bg'];
    }
    const qrWindow = new BrowserWindow(options);
    qrWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(buildHtml(qrSvg, vars))}`);
    qrWindow.once('ready-to-show', () => qrWindow.show());
    qrWindow.setMenu(null);
    return true;
  } catch (err) {
    console.warn('[first-run] could not show QR:', err.message);
    return false;
  }
}

async function showUrlQrWindow({ url, projectRoot, BrowserWindow, QRCode, copy }) {
  try {
    if (!/^https?:\/\//.test(String(url || ''))) throw new Error('no measured server URL');
    const qr = QRCode || require('qrcode');
    const qrSvg = await qr.toString(url, { type: 'svg', margin: 2, errorCorrectionLevel: 'M', color: { dark: '#000000', light: '#ffffff' } });
    const vars = readThemeVars(projectRoot);
    const options = {
      width: 420, height: 520, resizable: false, minimizable: false, maximizable: false, fullscreenable: false, show: false,
      title: copy.title, webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true },
    };
    if (vars['--color-bg'] && HEX_COLOR.test(vars['--color-bg'])) options.backgroundColor = vars['--color-bg'];
    const win = new BrowserWindow(options);
    win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(buildHtml(qrSvg, vars, copy))}`);
    win.once('ready-to-show', () => win.show());
    win.setMenu(null);
    return true;
  } catch (err) {
    console.warn('[tray] could not show the URL QR:', err.message);
    return false;
  }
}

module.exports = { showQrPairingWindow, showUrlQrWindow, readTotpSecret, readThemeVars, buildHtml };
