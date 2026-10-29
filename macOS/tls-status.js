// could not

'use strict';

const LEVEL_SECURE = 'secure';
const LEVEL_INSECURE = 'insecure';
const LEVEL_UNKNOWN = 'unknown';

/* could not */
function parseUrlParts(url) {
  try {
    const parsed = new URL(String(url));
    return {
      scheme: parsed.protocol.replace(/:$/, '').toLowerCase(),
      host: parsed.hostname.toLowerCase(),
    };
  } catch (error) {
    return { scheme: null, host: null };
  }
}

function isIpLiteral(host) {
  if (!host) return false;
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(host)) return true;
  return host.includes(':');
}

function nameMatches(host, candidate) {
  const name = String(candidate || '').toLowerCase().replace(/\.$/, '');
  const target = String(host || '').toLowerCase().replace(/\.$/, '');
  if (!name || !target) return false;
  if (name === target) return true;
  if (!name.startsWith('*.')) return false;

  const suffix = name.slice(2);
  if (!target.endsWith('.' + suffix)) return false;
  const label = target.slice(0, target.length - suffix.length - 1);
  return label.length > 0 && !label.includes('.');
}

function certCoversHost(host, cert) {
  const sans = (cert && cert.subjectAltNames) || [];
  if (sans.length > 0) return sans.some((san) => nameMatches(host, san));
  if (cert && cert.commonName) return nameMatches(host, cert.commonName);
  return false;
}

function evaluateBinding(input) {
  const now = (input && input.now) || Date.now();
  const { scheme, host } = parseUrlParts(input && input.url);

  if (!scheme) {
    return {
      level: LEVEL_UNKNOWN,
      label: 'Connection: cannot determine',
      detail: 'The server URL could not be parsed, so its security was never measured.',
    };
  }

  if (scheme !== 'https') {
    return {
      level: LEVEL_INSECURE,
      label: 'Connection: not secure (plain HTTP)',
      detail:
        'Traffic to ' + host + ' is unencrypted. Anything on the network path ' +
        'can read it, including the TOTP code and the session token.',
    };
  }

  if (input && input.certError) {
    return {
      level: LEVEL_UNKNOWN,
      label: 'Connection: cannot determine',
      detail: 'TLS is configured but the certificate could not be read: ' + input.certError,
    };
  }

  const cert = input && input.cert;
  if (!cert) {
    return {
      level: LEVEL_UNKNOWN,
      label: 'Connection: cannot determine',
      detail: 'TLS is configured but no certificate was observed on the endpoint.',
    };
  }

  if (isIpLiteral(host)) {
    return {
      level: LEVEL_UNKNOWN,
      label: 'Connection: cannot determine',
      detail:
        'The server is bound to the IP address ' + host + ', which a ' +
        'certificate cannot be issued for. Bind to a hostname to get a ' +
        'verifiable identity.',
    };
  }

  if (!certCoversHost(host, cert)) {
    const names = (cert.subjectAltNames || []).join(', ') || cert.commonName || 'none';
    return {
      level: LEVEL_INSECURE,
      label: 'Connection: not secure (wrong certificate)',
      detail:
        'The certificate served for ' + host + ' is valid for ' + names +
        ' instead. Every browser rejects this, so it is broken now, not later.',
    };
  }

  const notAfter = Number(cert.notAfter);
  if (!Number.isFinite(notAfter)) {
    return {
      level: LEVEL_UNKNOWN,
      label: 'Connection: cannot determine',
      detail: 'The certificate for ' + host + ' has no readable expiry date.',
    };
  }

  if (notAfter <= now) {
    return {
      level: LEVEL_INSECURE,
      label: 'Connection: not secure (certificate expired)',
      detail: 'The certificate for ' + host + ' expired on ' +
        new Date(notAfter).toISOString().slice(0, 10) + '.',
    };
  }

  const daysLeft = Math.floor((notAfter - now) / 86400000);
  return {
    level: LEVEL_SECURE,
    label: 'Connection: secure (HTTPS)',
    detail:
      'TLS to ' + host + ' using a certificate valid for that exact name, ' +
      daysLeft + ' days remaining.',
  };
}

module.exports = {
  LEVEL_SECURE,
  LEVEL_INSECURE,
  LEVEL_UNKNOWN,
  parseUrlParts,
  isIpLiteral,
  nameMatches,
  certCoversHost,
  evaluateBinding,
};
