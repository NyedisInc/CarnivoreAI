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
import { declaredActionsFor } from '../../widgets/menu/declared-actions.svelte';
import { keysOfNodes } from '../../../lib/menu-keys/menu-keys';
import { declaredGroups } from '../../../lib/widget-menu/declared-nodes';

const HOST = 'panel-host';
const row = {
    id: 'hello', runtime: 'sidecar', enabled: true, state: 'active', name: 'Hello', install_key: 'k1', unverified: false,
    views: [{ name: 'game', surfaces: ['panel'] }],
} as unknown as CplugRow;

let app: ReturnType<typeof mount> | null = null;
afterEach(() => { if (app) unmount(app, { outro: false }); app = null; document.body.innerHTML = ''; setPanels([]); });

async function rig() {
    setPanels([row]);
    app = mount(PanelHost, { target: document.body, props: { instance: 'hello.game:panel-k1' } });
    await tick(); await tick();
    const frame = document.querySelector('iframe')!;
    const posted: Record<string, unknown>[] = [];
    frame.contentWindow!.postMessage = ((m: Record<string, unknown>) => { posted.push(m); }) as Window['postMessage'];
    frame.dispatchEvent(new Event('load'));
    const nonce = posted.find((m) => m.verb === 'init')!.nonce as string;
    const say = (body: Record<string, unknown>) => {
        window.dispatchEvent(new MessageEvent('message', { source: frame.contentWindow, data: { nonce, ...body } }));
        flushSync();
    };
    const replies = () => posted.filter((m) => m.id !== undefined);
    return { posted, say, replies, nonce };
}

const list = [
    { id: 'mode:edit', label: 'edit', kind: 'choice', on: true },
    { id: 'mode:view', label: 'view', kind: 'choice', on: false },
    { id: 'grid', label: 'grid', kind: 'switch', on: false },
    { id: 'reload', label: 'reload', blocked: 'loading' },
];

describe('ui.actions, action and ui.menu', () => {
    test('a valid list reaches the widget menu, a click posts action back, and the items draw no letter', async () => {
        const r = await rig();
        expect((r.posted.find((m) => m.verb === 'init')!.features as string[])).toEqual(expect.arrayContaining(['actions', 'menu']));
        r.say({ verb: 'ui.actions', id: 'a1', actions: list });
        expect(r.replies()).toEqual([{ nonce: r.nonce, id: 'a1', ok: true }]);
        const declared = declaredActionsFor(HOST);
        expect(declared.map((d) => [d.id, d.checked, d.toggle, d.blocked, d.group])).toEqual([
            ['view:mode:edit', true, undefined, undefined, 'plugin:main'],
            ['view:mode:view', false, undefined, undefined, 'plugin:main'],
            ['view:grid', false, true, undefined, 'plugin:main'],
            ['view:reload', undefined, undefined, 'loading', 'plugin:main'],
        ]);
        const nodes = declaredGroups(declared).flat();
        expect(keysOfNodes(nodes)).toEqual(['', '', '', '']);
        declared[2]!.run();
        declared[0]!.run();
        declared[3]!.run();
        expect(r.posted.filter((m) => m.verb === 'action')).toEqual([
            { verb: 'action', nonce: r.nonce, id: 'grid', on: true },
            { verb: 'action', nonce: r.nonce, id: 'mode:edit', on: true },
            { verb: 'action', nonce: r.nonce, id: 'reload' },
        ]);
    });

    test('an empty list withdraws; a malformed, duplicate or oversized list is dropped whole and the previous one stays', async () => {
        const r = await rig();
        r.say({ verb: 'ui.actions', id: 'ok', actions: list });
        const bad: [string, unknown][] = [
            ['bad id', [{ id: 'Bad Id', label: 'x' }]],
            ['no label', [{ id: 'a', label: '  ' }]],
            ['label with a control character', [{ id: 'a', label: 'x\u0007y' }]],
            ['label over 40', [{ id: 'a', label: 'x'.repeat(41) }]],
            ['choice without on', [{ id: 'a', label: 'x', kind: 'choice' }]],
            ['action with on', [{ id: 'a', label: 'x', on: true }]],
            ['unknown kind', [{ id: 'a', label: 'x', kind: 'menu' }]],
            ['blocked over 60', [{ id: 'a', label: 'x', blocked: 'y'.repeat(61) }]],
            ['bad group', [{ id: 'a', label: 'x', group: 'No Good' }]],
            ['duplicate id', [{ id: 'a', label: 'x' }, { id: 'a', label: 'y' }]],
            ['one bad among good ones', [{ id: 'a', label: 'x' }, { id: 'b' }]],
            ['not a list', { id: 'a', label: 'x' }],
        ];
        for (const [name, actions] of bad) {
            r.say({ verb: 'ui.actions', id: name, actions });
            expect(r.replies().at(-1), name).toEqual({ nonce: r.nonce, id: name, ok: false, error: 'invalid_actions' });
        }
        r.say({ verb: 'ui.actions', id: 'many', actions: Array.from({ length: 13 }, (_, i) => ({ id: `a${i}`, label: 'x' })) });
        expect(r.replies().at(-1)).toEqual({ nonce: r.nonce, id: 'many', ok: false, error: 'too_large' });
        r.say({ verb: 'ui.actions', id: 'big', actions: Array.from({ length: 12 }, (_, i) => ({ id: `a${i}`, label: 'x', blocked: 'y'.repeat(60), pad: 'z'.repeat(300) })) });
        expect(r.replies().at(-1)).toEqual({ nonce: r.nonce, id: 'big', ok: false, error: 'too_large' });
        expect(declaredActionsFor(HOST).map((d) => d.id)).toEqual(['view:mode:edit', 'view:mode:view', 'view:grid', 'view:reload']);
        r.say({ verb: 'ui.actions', id: 'none', actions: [] });
        expect(r.replies().at(-1)).toEqual({ nonce: r.nonce, id: 'none', ok: true });
        expect(declaredActionsFor(HOST)).toEqual([]);
    });

    test('the declaration leaves with the cell', async () => {
        const r = await rig();
        r.say({ verb: 'ui.actions', id: 'a', actions: list });
        expect(declaredActionsFor(HOST).length).toBe(4);
        unmount(app!, { outro: false });
        app = null;
        expect(declaredActionsFor(HOST)).toEqual([]);
    });
});
