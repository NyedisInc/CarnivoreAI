/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import type { CplugRow } from '../../../lib/plugins-page/cplugs-adapter';

vi.mock('../../../lib/cplug-ui/api', () => ({
    fetchViewTicket: vi.fn(async () => ({ path: '/cplugs/hello/view/game/t/index.html' })),
    callViewRoute: vi.fn(),
}));

import PanelHost from './fixtures/PanelHost.svelte';
import { setPanels } from '../../../lib/cplug-ui/panel-views.svelte';
import type { FrameHeader } from '../../shell/frame-header.svelte';

const row = (unverified: boolean): CplugRow => ({
    id: 'hello', runtime: 'sidecar', enabled: true, state: 'active', name: 'Hello', install_key: 'k1', unverified,
    views: [{ name: 'game', surfaces: ['panel'] }],
} as unknown as CplugRow);

let app: ReturnType<typeof mount> | null = null;
afterEach(() => { if (app) unmount(app, { outro: false }); app = null; document.body.innerHTML = ''; setPanels([]); });

async function draw(unverified = false): Promise<FrameHeader> {
    setPanels([row(unverified)]);
    let header: FrameHeader | undefined;
    app = mount(PanelHost, { target: document.body, props: { instance: 'hello.game:panel-k1', onHeader: (h: FrameHeader) => { header = h; } } });
    await tick(); await tick();
    return header!;
}

const marks = () => document.querySelectorAll('[data-cplug-mark]');

describe('a panel widget has one header', () => {
    test('the frame draws no bar of its own and the mark goes up into the host title strip', async () => {
        const header = await draw();
        header.drawn = true;
        flushSync();
        expect(document.querySelector('.cu-frame__bar')).toBeNull();
        expect(marks().length).toBe(1);
        expect(document.querySelector('[data-host-header] [data-cplug-mark]')).not.toBeNull();
        expect(document.querySelector('[data-cplug-name]')).toBeNull();
    });

    test('with no header drawn, or the header ticked off, the mark is in the body, and a sideload reads unverified', async () => {
        const header = await draw(true);
        expect(document.querySelector('.cu-frame__bar')).toBeNull();
        expect(document.querySelector('[data-widget-controls] [data-cplug-mark]')).not.toBeNull();
        header.suppressed = true;
        flushSync();
        expect(marks().length).toBe(1);
        expect(document.querySelector('[data-host-header] [data-cplug-mark]')).toBeNull();
        expect(marks()[0]!.hasAttribute('data-unverified')).toBe(true);
    });
});
