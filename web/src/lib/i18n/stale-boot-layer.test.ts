import { afterEach, describe, expect, test, vi } from 'vitest';

function staleLayer() {
    const known: Record<string, string> = { 'drawer.account.lurker': 'SysOp' };
    return {
        locale: 'en',
        t: (key: string) => known[key] ?? key,
        setLocale: () => false,
        onLocaleChange: () => () => {},
        availableLocales: () => ['en'],
        problems: [],
    };
}

describe('t() against a stale boot layer', () => {
    afterEach(() => {
        delete (globalThis as { CloudeI18n?: unknown }).CloudeI18n;
        vi.resetModules();
    });

    test('the account pill and the menu row render their words, never their keys', async () => {
        vi.resetModules();
        (globalThis as { CloudeI18n?: unknown }).CloudeI18n = staleLayer();
        const { t } = await import('./index.svelte');
        expect(t('account.chip.signin')).toBe('sign in');
        expect(t('account.menu.signin')).toBe('sign in or create your free account');
    });

    test('a key no catalog has still renders as the key, loudly', async () => {
        vi.resetModules();
        (globalThis as { CloudeI18n?: unknown }).CloudeI18n = staleLayer();
        const { t } = await import('./index.svelte');
        expect(t('no.such.key.anywhere')).toBe('no.such.key.anywhere');
    });
});
