/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import ClassifierChange from './ClassifierChange.svelte';
import { setLocale } from '../../lib/i18n/index.svelte';

setLocale('en');

const fetcher = ((connected: boolean) => async (path: string) => {
    if (path === '/argent/classifier') return { enabled: true, ask_every_time: false, connected };
    if (path === '/sessions/list') return [{ session: { id: 'ses_1' }, label: 'one', tmux_session: 'carnivore_one' }, { session: { id: 'ses_2' }, label: 'two', tmux_session: 'carnivore_two' }];
    return { items: [] };
});

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => { for (const c of mounted.splice(0)) await unmount(c); document.body.replaceChildren(); window.location.hash = ''; });

async function draw(hash: string, connected = true): Promise<HTMLElement> {
    window.location.hash = hash;
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(ClassifierChange, { target, props: { fetcher: fetcher(connected) as never } }));
    for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
    return target;
}

describe('ClassifierChange', () => {
    test('the session named in the link is preselected and the form is open', async () => {
        const target = await draw('#settings/features/argent/settings?session=carnivore_two');
        expect((target.querySelector('[data-argent="classifier-session"]') as HTMLSelectElement | null)?.value ?? target.querySelector('select')?.value).toBe('ses_2');
    });

    test('no session in the link leaves the form folded (negative control)', async () => {
        const target = await draw('#settings/features/argent/settings');
        expect(target.querySelector('select')).toBeNull();
        expect(target.querySelector('[data-argent="classifier-open"]')).not.toBeNull();
    });

    test('no byoai connection shows the helper hint', async () => {
        const target = await draw('#settings/features/argent/settings', false);
        expect(target.querySelector('[data-argent="classifier-needs-connection"]')).not.toBeNull();
    });
});
