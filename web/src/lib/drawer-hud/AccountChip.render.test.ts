/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const requireAccount = vi.hoisted(() => vi.fn((_ask: unknown) => Promise.resolve('prompted')));
vi.mock('../carnivore-account/funnel', () => ({ requireAccount }));

import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import * as Bar from '../drawer/bar';
import { versionFooterStub } from '../drawer/test-support';
import { accountChip } from './account-menu.svelte';
import { accountIdentity, displayName } from './account-identity';

const w = window as unknown as Record<string, unknown>;
const messages = enCatalog as Record<string, string>;

beforeEach(() => {
    document.body.innerHTML = '<div id="session-sidebar-bar-slot"></div>';
    Bar.reset();
    w.CloudeI18n = { t: (key: string) => messages[key] ?? key };
    w.VersionFooter = versionFooterStub('1.2.3');
});

afterEach(() => {
    accountChip.identity = null;
    delete w.CloudeI18n;
    delete w.VersionFooter;
});

const slot = (): HTMLElement => document.getElementById('session-sidebar-bar-slot')!;

describe('the account chip', () => {
    test('the spiral steps on the ambient ticker (no infinite animation) and rests under reduced motion', () => {
        const css = readFileSync(resolve(__dirname, '../../../../client/css/session-sidebar-account-chip.css'), 'utf8');
        expect(css).toMatch(/\.spiral-turn\s*\{[^}]*transform: rotate\(calc\(var\(--amb-step, 0\) \* 15deg\)\)/);
        expect(css).not.toMatch(/\.spiral-turn\s*\{[^}]*infinite/);
        expect(css).toMatch(/prefers-reduced-motion: reduce\)\s*\{[^}]*\.spiral-turn\s*\{\s*transform: none/);
    });

    test('signed out: SysOp with the turning spiral, no identicon, no status dot', () => {
        accountChip.identity = accountIdentity(null);
        Bar.paint();
        expect(slot().querySelector('.session-sidebar-bar__account-name')!.textContent).toBe('SysOp');
        const avatar = slot().querySelector('.session-sidebar-bar__avatar')!;
        expect(avatar.getAttribute('data-kind')).toBe('lurker');
        expect(avatar.querySelector('svg.spiral.spiral-turn[data-spiral] path')).not.toBeNull();
        expect(avatar.querySelector('svg.anon path[fill="currentColor"]')).toBeNull();
        expect(avatar.querySelector('svg.ident')).toBeNull();
        expect(slot().querySelector('.session-sidebar-bar__conn')).toBeNull();
        expect(slot().textContent).toContain('v1.2.3');
    });

    test('the chip has an accessible name and no hover tooltip', () => {
        accountChip.identity = accountIdentity(null);
        Bar.paint();
        const chip = slot().querySelector('[data-bar-action="account"]')!;
        expect(chip.getAttribute('aria-label')).toBe('account menu, SysOp');
        expect(chip.hasAttribute('title')).toBe(false);
    });

    test('signed in: the handle and its identicon, never the provider tier or the email', () => {
        accountChip.identity = accountIdentity({ signedIn: true, handle: 'example-owner', login: 'alex@example.com', provider: 'email' });
        Bar.paint();
        expect(slot().querySelector('.session-sidebar-bar__account-name')!.textContent).toBe('example-owner');
        const avatar = slot().querySelector('.session-sidebar-bar__avatar')!;
        expect(avatar.getAttribute('data-kind')).toBe('member');
        expect(avatar.querySelector('svg.ident rect')).not.toBeNull();
        expect(avatar.querySelector('svg.spiral')).toBeNull();
        expect(slot().querySelector('.session-sidebar-bar__account-plan')).toBeNull();
        expect(slot().textContent).not.toMatch(/max|@example\.com/i);
        expect(slot().querySelector('.session-sidebar-bar__conn')).toBeNull();
    });

    test('no handle yet: the email local part, never the address; a github login is used as is', () => {
        expect(displayName('', 'alex@example.com')).toBe('alex');
        expect(displayName('', 'octocat')).toBe('octocat');
        expect(accountIdentity({ signedIn: true, handle: '', login: null, provider: 'email' }).kind).toBe('lurker');
        expect(accountIdentity({ signedIn: false, handle: 'x', login: 'x', provider: null }).kind).toBe('lurker');
    });
});

describe('the sign in pill (#1200)', () => {
    test('signed out: a sibling gold pill, not nested in the chip, calls requireAccount with src chip', () => {
        accountChip.identity = accountIdentity(null);
        Bar.paint();
        const pill = slot().querySelector<HTMLButtonElement>('[data-bar-action="signin"]')!;
        expect(pill.textContent).toBe('sign in');
        expect(pill.closest('[data-bar-action="account"]')).toBeNull();
        expect(pill.className).toContain('session-sidebar-bar__signin');
        pill.click();
        expect(requireAccount).toHaveBeenCalledTimes(1);
        expect(requireAccount.mock.calls[0]![0]).toMatchObject({ src: 'chip' });
    });

    test('signed in: no pill', () => {
        accountChip.identity = accountIdentity({ signedIn: true, handle: 'example-owner', login: null, provider: 'email' });
        Bar.paint();
        expect(slot().querySelector('[data-bar-action="signin"]')).toBeNull();
    });

    test('the pill is gold from the locked star token', () => {
        const css = readFileSync(resolve(__dirname, '../../../../client/css/session-sidebar-account-chip.css'), 'utf8');
        expect(css).toMatch(/\.session-sidebar-bar__signin\s*\{[^}]*--_btn-ink: var\(--oc-yellow-bright\)/);
    });
});
