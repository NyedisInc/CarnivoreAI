
'use strict';

const COPIED_TOOLTIP_MS = 2000;

async function changeBind(ctx, ip) {
  const tray = ctx.getTray();
  if (tray) tray.setToolTip(`Carnivore: restarting on ${ip}...`);
  try {
    await ctx.serverManager.setBindHost(ip, { api: ctx.data.api() });
  } catch (err) {
    console.error('[bind-host] change failed:', err);
    ctx.dialog.showErrorBox('Bind IP change failed',
      `Could not restart the server on ${ip}.\n\n${err.message || err}\n\nFalling back to the previous binding.`);
  } finally {
    ctx.refresh();
  }
}

function handlers(ctx) {
  const sm = ctx.serverManager;
  return {
    'phone.copy_url': (a) => ctx.clipboard.writeText(a.url),
    'phone.url_qr': async (a) => {
      const t = ctx.t;
      const shown = await ctx.qrWindow.showUrlQrWindow({
        url: a.url, projectRoot: sm.getProjectRoot(), BrowserWindow: ctx.BrowserWindow,
        copy: { title: t('menubar.qr.url_title'), body: t('menubar.qr.url_body'), aria: t('menubar.qr.url_aria'), footer: a.url },
      });
      if (!shown) ctx.dialog.showErrorBox('Carnivore: could not show the QR', 'The URL QR window could not be drawn; Copy URL still works.');
    },
    'phone.copy_otp': () => {
      const fresh = sm.getCurrentOtp();
      if (!fresh) return;
      ctx.clipboard.writeText(fresh);
      const tray = ctx.getTray();
      if (tray) {
        tray.setToolTip('OTP copied to clipboard');
        setTimeout(() => ctx.refresh(), COPIED_TOOLTIP_MS);
      }
    },
    'phone.totp_qr': async () => {
      const shown = await ctx.qrWindow.showQrPairingWindow({ serverDir: sm.baseDir, projectRoot: sm.getProjectRoot(), BrowserWindow: ctx.BrowserWindow });
      if (!shown) ctx.dialog.showErrorBox('Carnivore: could not show the QR', 'The authenticator secret could not be read; has setup run?');
    },
    'phone.bind': (a) => changeBind(ctx, a.ip),
  };
}

module.exports = { COPIED_TOOLTIP_MS, changeBind, handlers };
