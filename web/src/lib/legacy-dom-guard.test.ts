import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { knownListRatchet, stripComments, walkSources } from '../test-support/source-scan';

/** `client/js`, from web/src/lib. */
const LEGACY = path.resolve(__dirname, '../../../client/js');

export const LEGACY_DOM_KNOWN: readonly string[] = [
    'app.js', 'auth.js', 'clipboard-compat.js', 'config-editor-modal.js', 'config-editor-new-file.js',
    'config-editor-panel.js', 'config-editor-rows.js', 'copy-output.js', 'fab-menu.js', 'folder-picker-modal.js', 'header-menu.js',
    'header-title-fit.js', 'modal-ring.js', 'module-loader.js', 'paste-fallback.js', 'session-header-led.js', 'session-restart-direct.js',
    'session-restart-options.js', 'session-restart-picker.js', 'session-restore-offer.js', 'session-row-actions.js', 'session-theme-menu.js',
    'sidebar-help.js', 'slash-commands.js', 'slash-favorites.js', 'terminal-client-factory.js', 'terminal-header-rename.js',
    'terminal-key-bar.js', 'terminal-mascot.js', 'text-prompt-modal.js', 'themes/registry.js',
    'touch-select.js',
];

const DOM_WRITE = /\b(createElement|createElementNS|createDocumentFragment|insertAdjacentHTML)\s*\(|\b(innerHTML|outerHTML)\s*\+?=(?!=)/;

export function writesDom(text: string): boolean {
    return DOM_WRITE.test(stripComments(text));
}

describe('client/js gets no new DOM-writing file', () => {
    const writers = walkSources(LEGACY, /\.m?js$/).filter((file) => writesDom(fs.readFileSync(path.join(LEGACY, file), 'utf8')));

    it('looked at the legacy tree (a scan of nothing is not a pass)', () => {
        expect(writers.length).toBeGreaterThan(20);
    });

    it('has no DOM-writing file outside LEGACY_DOM_KNOWN (build new UI in web/)', () => {
        expect(knownListRatchet(writers, LEGACY_DOM_KNOWN).unlisted).toEqual([]);
    });

    it('keeps every LEGACY_DOM_KNOWN row true (a ported or cleaned file leaves the list)', () => {
        expect(knownListRatchet(writers, LEGACY_DOM_KNOWN).stale).toEqual([]);
    });

    it('goes red on a fixture (negative control)', () => {
        expect(writesDom("const d = document.createElement('div');")).toBe(true);
        expect(writesDom('el.innerHTML = html;')).toBe(true);
        expect(writesDom('el.innerHTML == html; // innerHTML = x')).toBe(false);
        expect(writesDom('/* createElement(x) */ const a = 1;')).toBe(false);
    });
});
