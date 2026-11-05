
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { createI18n } from '../../client/js/i18n/runtime.js';

const TR_JS = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'client', 'js', 'i18n', 'tr.js');

export function installCatalogTr(context) {
    context.CloudeI18n = createI18n();
    vm.runInContext(fs.readFileSync(TR_JS, 'utf8'), context, { filename: 'i18n/tr.js' });
}

export function installTrOnly(context) {
    vm.runInContext(fs.readFileSync(TR_JS, 'utf8'), context, { filename: 'i18n/tr.js' });
}
