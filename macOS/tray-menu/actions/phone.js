
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

const TOTP_QR_FAILURE_KEY = Object.freeze({
  offline: 'menubar.qr.failure.offline',
  restart_needed: 'menubar.qr.failure.restart_needed',
  loopback_only: 'menubar.qr.failure.loopback_only',
  rate_limited: 'menubar.qr.failure.rate_limited',
  login_failed: 'menubar.qr.failure.login_failed',
  refused: 'menubar.qr.failure.refused',
  failed: 'menubar.qr.failure.failed',
});

const OTP_ONLY_KEY = Object.freeze({
  restart_pending: 'menubar.otp.restart_pending',
  no_code_free: 'menubar.otp.no_code_free',
});

function loopbackApiUrl(sm) {
  try {
    return `http://127.0.0.1:${sm.getPort()}`;
  } catch (err) {
    console.warn('[tray] no port for the loopback QR route:', err.message);
    return undefined;
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
      if (!shown) ctx.dialog.showErrorBox(ctx.t('menubar.qr.error_title'), ctx.t('menubar.qr.url_failed'));
    },
    'phone.copy_otp': async () => {
      const loaded = await ctx.qrWindow.fetchLoadedCode(ctx.data.api(), loopbackApiUrl(sm));
      if (loaded.state !== 'ok') {
        const key = OTP_ONLY_KEY[loaded.state] || TOTP_QR_FAILURE_KEY[loaded.state];
        ctx.dialog.showErrorBox(ctx.t('menubar.otp.error_title'), ctx.t(key || TOTP_QR_FAILURE_KEY.refused));
        return;
      }
      ctx.clipboard.writeText(loaded.code);
      const tray = ctx.getTray();
      if (tray) {
        tray.setToolTip(ctx.t('menubar.otp.copied'));
        setTimeout(() => ctx.refresh(), COPIED_TOOLTIP_MS);
      }
    },
    'phone.totp_qr': async () => {
      const outcome = await ctx.qrWindow.showQrPairingWindow({
        api: ctx.data.api(), projectRoot: sm.getProjectRoot(), BrowserWindow: ctx.BrowserWindow,
        restartFooter: ctx.t('menubar.qr.restart_pending'), baseUrl: loopbackApiUrl(sm),
      });
      if (outcome !== 'shown') {
        ctx.dialog.showErrorBox(ctx.t('menubar.qr.error_title'), ctx.t(TOTP_QR_FAILURE_KEY[outcome] || TOTP_QR_FAILURE_KEY.failed));
      }
    },
    'phone.bind': (a) => changeBind(ctx, a.ip),
  };
}

module.exports = { COPIED_TOOLTIP_MS, changeBind, handlers };
