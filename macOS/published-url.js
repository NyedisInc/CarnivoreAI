
'use strict';

function resolvePublishedUrl({ port, configuredHost, measuredHost, lanIp }) {
  if (port === null || port === undefined) return null;

  const host = measuredHost || configuredHost;

  if (host === '0.0.0.0') {
    if (!measuredHost) return `http://127.0.0.1:${port}`;
    return `http://${lanIp || '127.0.0.1'}:${port}`;
  }
  return `http://${host}:${port}`;
}

function resolveAppWindowUrl(opts) {
  if (opts.port === null || opts.port === undefined) return null;
  const host = opts.measuredHost || opts.configuredHost;
  if (host === '0.0.0.0' || host === 'localhost' || host === '::1' || host === '[::1]' || (typeof host === 'string' && host.startsWith('127.'))) {
    return `http://127.0.0.1:${opts.port}`;
  }
  return resolvePublishedUrl(opts);
}

module.exports = { resolvePublishedUrl, resolveAppWindowUrl };
