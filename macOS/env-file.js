
'use strict';

const fs = require('fs');
const path = require('path');

const CRITICAL_FIELDS = ['DEFAULT_WORKING_DIR', 'LOG_DIRECTORY'];

const AUTH_FIELDS = ['TOTP_SECRET', 'JWT_SECRET'];

function rawEnvValue(envText, key) {
  const match = envText.match(new RegExp(`^${key}=(.*)$`, 'm'));
  return match ? match[1] : null;
}

function readEnvValue(envText, key) {
  const raw = rawEnvValue(envText, key);
  return raw === null ? null : raw.trim().replace(/^['"]|['"]$/g, '').trim();
}

function validateEnvFile(baseDir, getPort) {
  const envPath = path.join(baseDir, '.env');
  const result = { isValid: true, missingRequired: [], emptyRequired: [], errors: [] };
  if (!fs.existsSync(envPath)) {
    result.isValid = false;
    result.errors.push('.env file not found. Run setup first.');
    return result;
  }
  const envContent = fs.readFileSync(envPath, 'utf8');
  CRITICAL_FIELDS.concat(AUTH_FIELDS).forEach((field) => {
    const value = rawEnvValue(envContent, field);
    if (value === null) {
      result.missingRequired.push(field);
      result.isValid = false;
    } else if (value.trim() === '') {
      result.emptyRequired.push(field);
      result.isValid = false;
    }
  });
  if (result.missingRequired.length > 0) result.errors.push(`Missing required fields: ${result.missingRequired.join(', ')}`);
  if (result.emptyRequired.length > 0) result.errors.push(`Empty required fields: ${result.emptyRequired.join(', ')}`);
  try {
    getPort();
  } catch (err) {
    result.isValid = false;
    result.errors.push(err.message);
  }
  return result;
}

module.exports = { rawEnvValue, readEnvValue, validateEnvFile };
