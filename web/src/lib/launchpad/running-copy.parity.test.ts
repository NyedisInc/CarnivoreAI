import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { describe, expect, test } from 'vitest';

import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { registerPluginSlices } from '../i18n/plugin-fragments';
import { glyphSvg } from '../../../../client/js/icons/glyphs.js';
import { RUNNING_SESSION_KEYS } from '../../../../client/js/labels/running-session.js';

registerPluginSlices();

const repoRoot = fileURLToPath(new URL('../../../..', import.meta.url));

function message(key: string): string {
    const value = (enCatalog as Record<string, unknown>)[key];
    if (typeof value !== 'string') {
        throw new Error(`${key} is not a plain message`);
    }
    return value;
}

function legacyWindow(files: string[]): Record<string, any> {
    const context: Record<string, unknown> = { console };
    context.window = context;
    context.globalThis = context;
    context.CloudeGlyphs = { glyphSvg };
    vm.createContext(context);
    for (const file of files) {
        const source = fs.readFileSync(
            path.join(repoRoot, 'client', 'js', file), 'utf8');
        vm.runInContext(source, context);
    }
    return context as Record<string, any>;
}

describe('the destructive row controls say what the sidebar says', () => {
    const win = legacyWindow(['session-status-ui.js', 'session-row-actions.js']);
    const actions = win.SessionRowActions;

    test('close, remove and restart each match their catalog message', () => {
        expect(message(RUNNING_SESSION_KEYS.actionClose))
            .toBe(actions.labelFor(actions.ACTION_CLOSE));
        expect(message(RUNNING_SESSION_KEYS.actionRemove))
            .toBe(actions.labelFor(actions.ACTION_REMOVE));
        expect(message(RUNNING_SESSION_KEYS.actionRestart))
            .toBe(actions.labelFor(actions.ACTION_RESTART));
    });

    test('NEGATIVE CONTROL: the comparison is capable of failing', () => {
        expect(message(RUNNING_SESSION_KEYS.actionClose))
            .not.toBe(actions.labelFor(actions.ACTION_REMOVE));
    });

    test('A LIVE ROW EARNS RESTART, measured against the real rule', () => {
        for (const status of actions.LIVE_STATUSES) {
            const offered = actions.actionsFor(status);
            expect(offered, `status ${status}`).toContain(actions.ACTION_RESTART);
            expect(offered, `status ${status}`).toContain(actions.ACTION_CLOSE);
            expect(offered, `status ${status}`).not.toContain(actions.ACTION_REMOVE);
        }
        expect(actions.LIVE_STATUSES.length).toBeGreaterThan(3);
    });

    test('a DEAD row earns restart and remove, and no close', () => {
        expect(actions.actionsFor('dead'))
            .toEqual([actions.ACTION_RESTART, actions.ACTION_REMOVE]);
    });

    test('UNKNOWN is never treated as dead', () => {
        expect(actions.actionsFor('unknown')).toEqual([actions.ACTION_CLOSE]);
    });
});

describe('the mark-unread wording', () => {
    const win = legacyWindow(['session-status-ui.js']);

    function legacyTitle(unread: boolean): string {
        const html = win.SessionStatusUI.markUnreadHtml('cloude_api', unread);
        const match = /title="([^"]*)"/.exec(html);
        if (!match) throw new Error('markUnreadHtml emitted no title');
        return match[1]!;
    }

    test('both states match the catalog, word for word', () => {
        expect(message('cplug.unread.clear')).toBe(legacyTitle(true));
        expect(message('cplug.unread.set')).toBe(legacyTitle(false));
    });

    test('NEGATIVE CONTROL: the two states really do say different things', () => {
        expect(legacyTitle(true)).not.toBe(legacyTitle(false));
    });
});

describe('the theme swatch reads the SHARED colour rule', () => {
    const win = legacyWindow(['session-theme-tint.js']);

    test('colorsFor is exported as DATA, which is what the card consumes', () => {
        expect(typeof win.SessionThemeTint.colorsFor).toBe('function');
        expect(win.SessionThemeTint.colorsFor('dracula')).toBeNull();
        expect(win.SessionThemeTint.colorsFor(null)).toBeNull();
    });
});

describe('the five icons are ONE set of coordinates, two renderers', () => {
    const win = legacyWindow(['session-status-ui.js']);

    test('every legacy builder emits exactly the shared glyph data', () => {
        const ui = win.SessionStatusUI;
        expect(ui.closeIconSvg()).toBe(glyphSvg('close'));
        expect(ui.trashIconSvg()).toBe(glyphSvg('trash'));
        expect(ui.restartIconSvg()).toBe(glyphSvg('restart'));
        expect(ui.pencilIconSvg()).toBe(glyphSvg('pencil'));
    });

    test('NEGATIVE CONTROL: the glyphs are not all the same string', () => {
        expect(glyphSvg('close')).not.toBe(glyphSvg('trash'));
        expect(glyphSvg('envelope-outline')).not.toBe(glyphSvg('envelope-filled'));
    });

    test('the unread control draws the two envelopes by SHAPE, not colour', () => {
        const filled = win.SessionStatusUI.markUnreadHtml('cloude_api', true);
        const outline = win.SessionStatusUI.markUnreadHtml('cloude_api', false);
        expect(filled).toContain(glyphSvg('envelope-filled'));
        expect(outline).toContain(glyphSvg('envelope-outline'));
    });
});
