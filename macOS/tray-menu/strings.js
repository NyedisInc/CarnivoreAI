
'use strict';

const path = require('path');
const { pathToFileURL } = require('url');

const MAX_LABEL = 44;

function resolveClientDir(where) {
  return where.isPackaged ? path.join(where.resourcesPath, 'client') : path.join(where.appDir, '..', 'client');
}

function createTranslator(messages, format) {
  return function t(key, params) {
    const entry = messages ? messages[key] : undefined;
    if (entry === undefined) return key;
    return format(entry, params || {});
  };
}

async function loadTranslator(clientDir) {
  const i18nDir = path.join(clientDir, 'js', 'i18n');
  const catalog = await import(pathToFileURL(path.join(i18nDir, 'catalog.en.js')).href);
  const format = await import(pathToFileURL(path.join(i18nDir, 'format.js')).href);
  return createTranslator(catalog.default, (entry, params) => format.formatEntry(entry, params, catalog.intlLocale));
}

function clip(text, max) {
  const width = max || MAX_LABEL;
  const clean = (typeof text === 'string' ? text : '').replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ').trim();
  return clean.length > width ? clean.slice(0, width - 3) + '...' : clean;
}

module.exports = { MAX_LABEL, resolveClientDir, createTranslator, loadTranslator, clip };
