/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import DetailActions from './DetailActions.svelte';
import type { CatalogHost } from './catalog';
import type { InstalledItem } from './types';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

const i18n = createI18n({ locale: 'en' }) as { t(k: string, p?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

const ROW: InstalledItem = {
    install_id: 'i1', item_id: 'alex/deploy', name: 'deploy', scope: 'global', revision: 2, version: '1.0.0',
    drift: { state: 'drifted', changed_files: ['SKILL.md'] },
} as InstalledItem;

let mounted: Record<string, unknown> | null = null;
afterEach(async () => {
    for (let guard = 0; guard < 8 && document.querySelector('.modal-overlay'); guard += 1) {
        document.querySelector('.modal-overlay')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        await settle();
    }
    if (mounted) unmount(mounted as never);
    mounted = null;
    document.body.innerHTML = '';
});

const primary = () => {
    const all = [...document.querySelectorAll('.modal-btn-primary')];
    return all[all.length - 1] as HTMLButtonElement;
};

test('a script-bearing restore shows the script sheet unticked, then sends the consent to restore', async () => {
    const sent: Array<Record<string, unknown>> = [];
    const host = {
        restoreInstalled: async (_id: string, body: Record<string, unknown>) => {
            sent.push(body);
            if (sent.length === 1) {
                const error = new Error('HTTP 409') as Error & { status: number; body: unknown };
                error.status = 409;
                error.body = { code: 'consent_required', body: '# skill', body_sha: 'sha1', digest: 'dig1',
                    script_files: ['scripts/go.sh'] };
                throw error;
            }
            return { ...ROW, revision: 3 };
        },
    } as unknown as CatalogHost;
    const target = document.createElement('div');
    document.body.appendChild(target);
    mounted = mount(DetailActions, { target, props: {
        card: { id: 'alex/deploy', headline: 'deploy' }, installed: ROW, rowState: { kind: 'installed' },
        host, t, onInstall() {}, onLedgerChange() {},
    } as never }) as never;
    (document.querySelector('[data-act="restore"]') as HTMLButtonElement).click();
    await settle();
    primary().click();
    await settle();
    expect(sent).toHaveLength(1);
    const tick = document.querySelector('.confirm__accept input') as HTMLInputElement;
    expect(tick, 'the consent sheet is up').not.toBeNull();
    expect(tick.checked).toBe(false);
    expect(primary().disabled).toBe(true);
    expect(document.body.textContent).toContain('scripts/go.sh');
    tick.click();
    await settle();
    primary().click();
    await settle();
    expect(sent).toHaveLength(2);
    expect(sent[1]).toMatchObject({ expected_revision: 2, consent: { body_sha: 'sha1', digest: 'dig1', scripts: true } });
});
