
'use strict';

const { act, off, maybe, sub, sep, radio } = require('./items');
const { isTailscaleIp } = require('../../network-interfaces');
const trayStatus = require('../../tray-status');
const tlsStatus = require('../../tls-status');

const OTP_ROLL_HINT_S = 5;

function bindRadios(phone, t) {
  const chosen = phone.bindHost;
  const pick = (ip) => ({ kind: 'phone.bind', ip });
  return [
    radio('bind.loopback', '127.0.0.1', chosen === '127.0.0.1', pick('127.0.0.1'), { sublabel: t('menubar.phone.bind_loopback') }),
    ...(phone.localIps || []).map(({ iface, ip }) => radio(`bind.${ip}`, ip, chosen === ip, pick(ip),
      { sublabel: isTailscaleIp(ip) ? t('menubar.phone.bind_tailscale', { iface }) : iface })),
    radio('bind.all', '0.0.0.0', chosen === '0.0.0.0', pick('0.0.0.0'), { sublabel: t('menubar.phone.bind_all') }),
  ];
}

function phoneMenu(snap, env) {
  const { t } = env;
  const phone = snap.phone || {};
  const url = phone.measuredUrl || null;
  const noUrl = t('menubar.phone.url_unmeasured');
  const bind = trayStatus.describeBind({ effectiveHost: phone.effectiveHost, configuredHost: phone.bindHost });
  const security = tlsStatus.evaluateBinding({ url: phone.publishedUrl || url });
  const items = [
    maybe(Boolean(url), 'phone.copy_url', t('menubar.phone.copy_url'), { kind: 'phone.copy_url', url }, noUrl, { sublabel: url || undefined }),
    maybe(Boolean(url), 'phone.url_qr', t('menubar.phone.url_qr'), { kind: 'phone.url_qr', url }, noUrl),
  ];
  if (!snap.joined) {
    const otp = phone.otp;
    const roll = otp && phone.otpRemaining <= OTP_ROLL_HINT_S ? t('menubar.phone.otp_rolls', { count: phone.otpRemaining }) : undefined;
    items.push(
      maybe(Boolean(otp), 'phone.copy_otp', otp ? t('menubar.phone.copy_otp', { code: otp }) : t('menubar.phone.copy_otp_none'),
        { kind: 'phone.copy_otp' }, t('menubar.phone.otp_not_configured'), { sublabel: roll }),
      act('phone.totp_qr', t('menubar.phone.totp_qr'), { kind: 'phone.totp_qr' }),
    );
  }
  items.push(
    sep(),
    off('phone.bind_state', t('menubar.phone.bind'), bind.known ? t(bind.applied ? 'menubar.phone.bind_in_effect' : 'menubar.phone.bind_pending',
      { host: phone.effectiveHost || '', configured: phone.bindHost || '' }) : t('menubar.phone.bind_unknown')),
    ...bindRadios(phone, t),
    sep(),
    { ...off('phone.security', t(`menubar.phone.security.${security.level}`)), toolTip: security.detail },
  );
  for (const item of items) if (item.sublabel === undefined) delete item.sublabel;
  return sub('phone', t('menubar.phone'), items, { toolTip: bind.detail });
}

module.exports = { OTP_ROLL_HINT_S, bindRadios, phoneMenu };
