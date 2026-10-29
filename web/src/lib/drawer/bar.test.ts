/** @vitest-environment jsdom */
import assert from 'node:assert/strict';
import { afterEach, beforeEach, describe, it, vi } from 'vitest';
import * as Bar from './bar';
import { accountChip } from '../drawer-hud/account-menu.svelte';
import { versionFooterStub } from './test-support';

let slot: HTMLElement;
let problems: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
    problems = vi.spyOn(console, 'error').mockImplementation(() => {});
    document.body.innerHTML = '<div id="session-sidebar-bar-slot"></div>';
    slot = document.getElementById('session-sidebar-bar-slot') as HTMLElement;
    Bar.reset();
    delete (window as unknown as Record<string, unknown>).CloudeWeb;
});

afterEach(() => problems.mockRestore());

describe('the drawer bottom bar', () => {
    it('a repaint that changes nothing leaves the bar element alone', () => {
        Bar.paint();
        const chip = slot.querySelector('[data-bar-action="account"]');
        assert.ok(chip, 'setup: the bar is drawn');
        Bar.paint(); Bar.paint();
        assert.equal(slot.querySelector('[data-bar-action="account"]'), chip, 'the same button after a repaint; a panel anchored to it survives');
        assert.deepEqual(problems.mock.calls, [], 'no [i18n] problem is reported while drawing the chip');
    });

    it('the bar holds the account chip and the sign in pill (signed out) and nothing else to press while master all is off and nothing is armed, at any width', () => {
        for (const width of [900, 1400]) {
            Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
            Bar.reset();
            Bar.paint();
            const actions = [...slot.querySelectorAll('[data-bar-action]')].map((el) => el.getAttribute('data-bar-action'));
            assert.deepEqual(actions, ['account', 'signin'], `at ${width}px`);
        }
    });

    it('the chip names the catalog account and escapes what a user typed', () => {
        accountChip.identity = { kind: 'member', name: 'Joe <b>', provider: 'github' };
        try {
            Bar.paint();
            const chip = slot.querySelector('[data-bar-action="account"]') as HTMLElement;
            assert.equal(chip.querySelector('.session-sidebar-bar__account-name')!.textContent, 'Joe <b>');
            assert.equal(chip.querySelector('b'), null, 'a typed name is text, never markup');
            assert.equal(chip.getAttribute('aria-haspopup'), 'menu');
            assert.equal(chip.getAttribute('aria-label'), 'account menu, Joe <b>');
        } finally {
            accountChip.identity = null;
        }
    });

    it('the version sits at the right, after the chip', () => {
        (window as unknown as Record<string, unknown>).VersionFooter = versionFooterStub('1.2.3');
        try {
            Bar.paint();
            const bar = slot.querySelector('.session-sidebar-bar') as HTMLElement;
            const parts = [...bar.children].map((el) => el.className);
            assert.deepEqual(parts, ['session-sidebar-bar__group', 'session-sidebar-bar__version']);
            assert.match(bar.lastElementChild!.textContent!, /v1\.2\.3/);
        } finally {
            delete (window as unknown as Record<string, unknown>).VersionFooter;
        }
    });

    it('the lit crown is drawn only while master all is on, and its click turns it off', () => {
        let on = true;
        (window as unknown as Record<string, unknown>).CloudeWeb = {
            masterAllEnabled: () => on,
            setMasterAll: (v: boolean) => { on = v; },
        };
        Bar.paint();
        const crown = slot.querySelector('#sidebarMasterAllBtn') as HTMLElement;
        assert.ok(crown, 'drawn while on');
        crown.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        assert.equal(on, false);
        assert.equal(slot.querySelector('#sidebarMasterAllBtn'), null, 'gone once off');
    });

    it('run() still opens settings and the documentation page and toggles the layout editor (the menu calls it)', () => {
        let settings = 0;
        let docs = 0;
        let toggles = 0;
        (window as unknown as Record<string, unknown>).CloudeWeb = {
            openSettingsScreen: () => { settings += 1; return true; },
            openDocsScreen: () => { docs += 1; return true; },
            layoutEditor: { active: () => false, available: () => true, toggle: () => { toggles += 1; } },
        };
        Bar.run('settings', null);
        Bar.run('help', null);
        Bar.run('layout', null);
        assert.deepEqual([settings, docs, toggles], [1, 1, 1]);
    });

    it('the edit layout entry: desktop only, kept but unavailable with nothing to edit', () => {
        let on = false;
        let available = true;
        const w = window as unknown as Record<string, unknown>;
        w.CloudeWeb = { layoutEditor: { active: () => on, available: () => available, toggle: () => {} } };
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1400 });
        assert.deepEqual(Bar.layoutEntry(), { active: false, available: true });
        available = false;
        assert.deepEqual(Bar.layoutEntry(), { active: false, available: false }, 'nothing to edit');
        on = true;
        assert.deepEqual(Bar.layoutEntry(), { active: true, available: true }, 'a running edit can always be finished');
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 900 });
        assert.equal(Bar.layoutEntry(), null, 'below 1024');
        delete w.CloudeWeb;
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1400 });
        assert.equal(Bar.layoutEntry(), null, 'no bridge');
    });
});
