/* <script */
import { createI18n } from './runtime.js';
import { bindDocumentLang } from './document-lang.js';
import { sessionSummaryLabel } from '../labels/session-summary.js';
import { headerActionLabels } from '../labels/header-actions.js';
import { terminalKeyBarLabels } from '../labels/terminal-key-bar.js';
import { glyphSvg } from '../icons/glyphs.js';
import { iconSvg } from '../icons/icon-registry.js';
import { assignMenuKeys } from '../menu-keys.js';

if (!globalThis.CloudeI18n) {
    globalThis.CloudeI18n = createI18n();
}

if (!globalThis.CloudeLabels) {
    globalThis.CloudeLabels = {
        sessionSummaryLabel,
        headerActionLabels,
        terminalKeyBarLabels,
    };
}

// the legacy twin
if (!globalThis.CloudeGlyphs) {
    globalThis.CloudeGlyphs = { glyphSvg, iconSvg };
}

if (!globalThis.CloudeMenuKeys) {
    globalThis.CloudeMenuKeys = { assignMenuKeys };
}

if (typeof document !== 'undefined') bindDocumentLang(globalThis.CloudeI18n, document);
