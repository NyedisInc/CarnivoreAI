'use strict';

const fs = require('fs');
const path = require('path');
const { ENV_PREFIX } = require('../product-identity');
const { STRATEGIES, DEFAULT_STRATEGY } = require('./constants');

const SETTING_FILE = 'engine-host.json';
const LEGACY_PREFIX = 'CLOUDE_';

function envStrategy(env) {
  const value = env[`${ENV_PREFIX}ENGINE_HOST`] || env[`${LEGACY_PREFIX}ENGINE_HOST`];
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

const MAX_LOGGED = 64;

function pickStrategy({ env = process.env, userData = null, fsImpl = fs } = {}) {
  let raw = envStrategy(env);
  let source = 'env';
  if (raw === null && userData) {
    try {
      const parsed = JSON.parse(fsImpl.readFileSync(path.join(userData, SETTING_FILE), 'utf8'));
      raw = parsed && typeof parsed.strategy === 'string' ? parsed.strategy.trim() : null;
      source = 'file';
    } catch (err) {
      raw = null;
    }
  }
  if (raw === null || raw === '') return { name: DEFAULT_STRATEGY, source: 'default', warning: null };
  if (!STRATEGIES.includes(raw)) {
    return { name: DEFAULT_STRATEGY, source: 'default', warning: `unknown engine host ${JSON.stringify(raw.slice(0, MAX_LOGGED))} (${source}); using ${DEFAULT_STRATEGY}` };
  }
  return { name: raw, source, warning: null };
}

module.exports = { SETTING_FILE, envStrategy, pickStrategy };
