'use strict';

const path = require('path');

function showAboutDialog({ app, BrowserWindow, shell }) {
  const { RELEASE_REPO } = require('./product-identity.js');

  const aboutWindow = new BrowserWindow({
    width: 500,
    height: 400,
    resizable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    show: false,
    // --color-
    backgroundColor: '#02161e',
    title: 'About Carnivore',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true
    }
  });

  aboutWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  const iconPath = app.isPackaged
    ? path.join(app.getAppPath(), 'assets', 'AppIcon-1024.png')
    : path.join(__dirname, 'assets', 'AppIcon-1024.png');

  const fs = require('fs');
  const iconBuffer = fs.readFileSync(iconPath);
  const iconBase64 = iconBuffer.toString('base64');
  const iconDataUrl = `data:image/png;base64,${iconBase64}`;

  const currentYear = new Date().getFullYear();
  const appVersion = `v${app.getVersion()}`;

  const html = `
    <!DOCTYPE html>
    <html>
    <head>
      <style>
        body {
          margin: 0;
          padding: 40px;
          font-family: ui-monospace, 'SF Mono', SFMono-Regular, Menlo, Monaco, 'Cascadia Mono', 'Roboto Mono', 'Courier New', monospace;
          background: #02161e;
          color: #eaebed;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 100vh;
          box-sizing: border-box;
        }
        .icon {
          width: 112px;
          height: 112px;
          margin-bottom: 20px;
          border-radius: 12px;
          border: 1px solid rgba(255, 70, 82, 0.4);
          box-shadow: 0 0 28px rgba(255, 70, 82, 0.35), 0 8px 32px rgba(0, 0, 0, 0.5);
        }
        h1 {
          margin: 0 0 10px 0;
          font-size: 26px;
          font-weight: 700;
          letter-spacing: 0.04em;
          color: #ff4652;
          text-transform: uppercase;
        }
        .tagline {
          margin: 0 0 30px 0;
          font-size: 14px;
          color: #a0a8ae;
          text-align: center;
          max-width: 400px;
          line-height: 1.6;
        }
        .github-btn {
          display: inline-block;
          padding: 12px 30px;
          background: transparent;
          color: #ff6872;
          border: 1px solid rgba(255, 70, 82, 0.6);
          border-radius: 6px;
          font-size: 14px;
          font-weight: 600;
          letter-spacing: 0.02em;
          text-transform: uppercase;
          cursor: pointer;
          text-decoration: none;
          transition: background 0.2s, box-shadow 0.2s, color 0.2s;
        }
        .github-btn:hover {
          background: rgba(239, 30, 45, 0.15);
          color: #ffffff;
          box-shadow: 0 0 20px rgba(255, 70, 82, 0.4);
        }
        .github-btn:active {
          background: rgba(239, 30, 45, 0.25);
        }
        .copyright {
          margin-top: 30px;
          font-size: 11px;
          color: #6b7378;
          text-align: center;
        }
      </style>
    </head>
    <body>
      <img src="${iconDataUrl}" class="icon" />
      <h1>Carnivore <span style="font-size: 14px; color: #6b7378; font-weight: 400; text-transform: none; letter-spacing: normal;">${appVersion}</span></h1>
      <p class="tagline">
        Your AI coding agents, run from the menu bar.<br/>
        Drive real terminal sessions from anywhere, on any device.
      </p>
      <a class="github-btn" href="https://github.com/${RELEASE_REPO}" target="_blank" rel="noopener noreferrer">View on GitHub</a>
      <div class="copyright">
        Copyright © ${currentYear} Nyedis Inc. All rights reserved.
      </div>
    </body>
    </html>
  `;

  aboutWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
  aboutWindow.once('ready-to-show', () => {
    aboutWindow.show();
  });

  aboutWindow.setMenu(null);
}

module.exports = { showAboutDialog };
