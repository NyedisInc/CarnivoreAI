/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { createBridge, newNonce } from './bridge';
import { FRAME_OC_TOKENS, readHostTheme, readTheme, watchTheme } from './frame-theme';
import { cleanShare, createShareRelay, MAX_SHARE_BYTES } from './share-relay';
import { keepFocusOut } from './focus-return';
import { clipPath, createTerminalWatch, enabledRects, MAX_RECTS, sanitizeRects } from './hit-regions';

vi.mock('./api', () => ({
    fetchViewTicket: vi.fn(async () => ({ path: '/api/v1/cplugs/pet/view/walk/T/index.html', expires_in: 3600 })),
    callViewRoute: vi.fn(async () => ({})),
    callViewTool: vi.fn(async () => ({ ok: true, text: 'ok' })),
}));

const NONCE = 'n'.repeat(32);
const VIEWPORT = { w: 1000, h: 800 };

function rig() {
    const posted: unknown[] = [];
    const window = { postMessage: (m: unknown) => posted.push(m) };
    const callRoute = vi.fn(async (route: string, payload: unknown) => ({ route, payload }));
    const onState = vi.fn();
    const onHitRegions = vi.fn();
    const bridge = createBridge({ nonce: NONCE, frame: () => window, declared: { routes: ['feed'], tools: ['pet_say'] }, callRoute, viewport: () => VIEWPORT, onState, onHitRegions });
    return { posted, window, callRoute, onState, onHitRegions, bridge };
}
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('the bridge drops what it must and maps what it may', () => {
    test('a declared route.call from the frame with the nonce reaches callRoute and the reply carries the nonce and id', async () => {
        const r = rig();
        r.bridge.handle({ source: r.window, data: { nonce: NONCE, verb: 'route.call', id: 'a1', route: 'feed', payload: { n: 1 } } });
        await flush();
        expect(r.callRoute).toHaveBeenCalledWith('feed', { n: 1 });
        expect(r.posted).toEqual([{ nonce: NONCE, id: 'a1', ok: true, result: { route: 'feed', payload: { n: 1 } } }]);
    });

    test('a wrong nonce, a missing nonce, a wrong source and a non-object are dropped without a reply', async () => {
        const r = rig();
        const good = { nonce: NONCE, verb: 'route.call', id: 'a', route: 'feed' };
        r.bridge.handle({ source: r.window, data: { ...good, nonce: 'x'.repeat(32) } });
        r.bridge.handle({ source: r.window, data: { verb: 'route.call', id: 'a', route: 'feed' } });
        r.bridge.handle({ source: { postMessage() {} }, data: good }); // another window
        r.bridge.handle({ source: null, data: good });
        r.bridge.handle({ source: r.window, data: 'route.call' });
        r.bridge.handle({ source: r.window, data: [good] });
        await flush();
        expect(r.callRoute).not.toHaveBeenCalled();
        expect(r.posted).toEqual([]);
        r.bridge.handle({ source: r.window, data: good });
        await flush();
        expect(r.callRoute).toHaveBeenCalledTimes(1);
    });

    test('a verb outside the four is dropped, an undeclared route or tool is refused, a tool call has no browser route', async () => {
        const r = rig();
        for (const verb of ['fetch', 'init', 'route.callx', 'eval', 'storage.set', '']) r.bridge.handle({ source: r.window, data: { nonce: NONCE, verb, id: 'v', route: 'feed' } });
        r.bridge.handle({ source: r.window, data: { nonce: NONCE, verb: 'route.call', id: 'u', route: 'wipe' } });
        r.bridge.handle({ source: r.window, data: { nonce: NONCE, verb: 'tool.call', id: 't1', tool: 'rm_rf' } });
        r.bridge.handle({ source: r.window, data: { nonce: NONCE, verb: 'tool.call', id: 't2', tool: 'pet_say' } });
        await flush();
        expect(r.callRoute).not.toHaveBeenCalled();
        expect(r.posted).toEqual([
            { nonce: NONCE, id: 'u', ok: false, error: 'undeclared' },
            { nonce: NONCE, id: 't1', ok: false, error: 'undeclared' },
            { nonce: NONCE, id: 't2', ok: false, error: 'tool_action_unavailable' },
        ]);
    });

    test('tool.call forwards declared tool calls to callTool when provided and rejects undeclared tools', async () => {
        const posted: unknown[] = [];
        const win = { postMessage: (m: unknown) => posted.push(m) };
        const callTool = vi.fn(async (tool: string, args: unknown) => ({ ok: true, text: `ran ${tool}`, args }));
        const b = createBridge({
            nonce: NONCE,
            frame: () => win,
            declared: { routes: ['feed'], tools: ['pet_say'] },
            callRoute: vi.fn(async () => ({})),
            callTool,
            viewport: () => VIEWPORT,
        });
        b.handle({ source: win, data: { nonce: NONCE, verb: 'tool.call', id: 'bad', tool: 'rm_rf', args: {} } });
        b.handle({ source: win, data: { nonce: NONCE, verb: 'tool.call', id: 'good', tool: 'pet_say', args: { msg: 'woof' } } });
        await flush();
        expect(callTool).toHaveBeenCalledExactlyOnceWith('pet_say', { msg: 'woof' });
        expect(posted).toEqual([
            { nonce: NONCE, id: 'bad', ok: false, error: 'undeclared' },
            { nonce: NONCE, id: 'good', ok: true, result: { ok: true, text: 'ran pet_say', args: { msg: 'woof' } } },
        ]);
    });

    test('tool.call rejects unarmed bridges with not_armed and re-checks armed before flushing held calls', async () => {
        const posted: unknown[] = [];
        const win = { postMessage: (m: unknown) => posted.push(m) };
        const callTool = vi.fn(async (tool: string, args: unknown) => ({ ok: true, tool, args }));
        let armed = false;
        let visible = true;
        const b = createBridge({
            nonce: NONCE,
            frame: () => win,
            declared: { routes: ['feed'], tools: ['pet_say'] },
            callRoute: vi.fn(async () => ({})),
            callTool,
            armed: () => armed,
            visible: () => visible,
            viewport: () => VIEWPORT,
        });
        b.handle({ source: win, data: { nonce: NONCE, verb: 'tool.call', id: 'u1', tool: 'pet_say', args: { msg: 'nope' } } });
        await flush();
        expect(callTool).not.toHaveBeenCalled();
        expect(posted).toEqual([{ nonce: NONCE, id: 'u1', ok: false, error: 'not_armed' }]);

        armed = true;
        b.handle({ source: win, data: { nonce: NONCE, verb: 'tool.call', id: 'a1', tool: 'pet_say', args: { msg: 'ok' } } });
        await flush();
        expect(callTool).toHaveBeenCalledTimes(1);
        expect(posted.at(-1)).toEqual({ nonce: NONCE, id: 'a1', ok: true, result: { ok: true, tool: 'pet_say', args: { msg: 'ok' } } });

        visible = false;
        b.handle({ source: win, data: { nonce: NONCE, verb: 'tool.call', id: 'h1', tool: 'pet_say', args: { msg: 'late' } } });
        armed = false;
        visible = true;
        b.release();
        await flush();
        expect(callTool).toHaveBeenCalledTimes(1);
        expect(posted.at(-1)).toEqual({ nonce: NONCE, id: 'h1', ok: false, error: 'not_armed' });
    });

    test('ui.state takes a short lowercase word only and hit regions are sanitized against the viewport', () => {
        const r = rig();
        r.bridge.handle({ source: r.window, data: { nonce: NONCE, verb: 'ui.state', state: 'ready' } });
        r.bridge.handle({ source: r.window, data: { nonce: NONCE, verb: 'ui.state', state: '<b>hi</b>' } });
        expect(r.onState.mock.calls).toEqual([['ready']]);
        r.bridge.handle({ source: r.window, data: { nonce: NONCE, verb: 'overlay.hit_regions', rects: [{ x: 10, y: 10, w: 40, h: 40 }, { x: 0, y: 0, w: 5000, h: 5000 }, 'x'] } });
        expect(r.onHitRegions).toHaveBeenCalledWith([{ x: 10, y: 10, w: 40, h: 40 }]);
    });

    test('init hands the nonce to the frame window only, and nonces are unique', () => {
        const r = rig();
        r.bridge.init();
        expect(r.posted).toEqual([{ verb: 'init', nonce: NONCE, role: 'panel', features: [] }]);
        expect(newNonce()).not.toBe(newNonce());
        expect(newNonce()).toMatch(/^[0-9a-f]{32}$/);
    });
});

describe('hit regions', () => {
    test('count and size are bounded and the terminal grid is cut out of every rectangle', () => {
        const many = Array.from({ length: 40 }, (_, i) => ({ x: i, y: 0, w: 10, h: 10 }));
        expect(sanitizeRects(many, VIEWPORT)).toHaveLength(MAX_RECTS);
        expect(sanitizeRects([{ x: 0, y: 0, w: 700, h: 10 }, { x: 0, y: 0, w: NaN, h: 10 }, { x: 0, y: 0, w: -1, h: 10 }], VIEWPORT)).toEqual([]);
        const cut = enabledRects([{ x: 0, y: 0, w: 100, h: 100 }], [{ x: 50, y: 0, w: 100, h: 100 }]);
        expect(cut).toEqual([{ x: 0, y: 0, w: 50, h: 100 }]);
        expect(enabledRects([{ x: 0, y: 0, w: 10, h: 10 }], [{ x: 0, y: 0, w: 99, h: 99 }])).toEqual([]);
        expect(clipPath([])).toBe("path('M0 0')");
        expect(clipPath([{ x: 1, y: 2, w: 3, h: 4 }])).toBe("path('M1 2h3v4h-3z')");
    });
});

describe('a view that navigates itself loses the bridge for good (#2184)', () => {
    test('init hands the nonce once; a second load posts nothing, answers nothing and fires onReload once', async () => {
        const r = rig();
        const onReload = vi.fn();
        const bridge = createBridge({ nonce: NONCE, frame: () => r.window, declared: { routes: ['feed'], tools: [] }, callRoute: r.callRoute, viewport: () => VIEWPORT, onReload });
        bridge.init();
        expect(r.posted).toEqual([{ verb: 'init', nonce: NONCE, role: 'panel', features: [] }]);
        bridge.init();
        bridge.init();
        expect(onReload).toHaveBeenCalledTimes(1);
        expect(r.posted).toHaveLength(1);
        bridge.handle({ source: r.window, data: { nonce: NONCE, verb: 'route.call', id: 'x', route: 'feed' } });
        await flush();
        expect(r.callRoute).not.toHaveBeenCalled();
        expect(r.posted).toHaveLength(1);
    });
});

describe('the terminal cut follows a grid that moved without a window resize (#2184)', () => {
    test('the watch fires only when the grids differ from the last look', () => {
        let grids = [{ x: 0, y: 0, w: 100, h: 100 }];
        const onChange = vi.fn();
        const w = createTerminalWatch(() => grids, onChange);
        w.look();
        w.look();
        expect(onChange).not.toHaveBeenCalled();
        grids = [{ x: 0, y: 0, w: 100, h: 100 }, { x: 100, y: 0, w: 50, h: 50 }];
        w.look();
        expect(onChange).toHaveBeenCalledTimes(1);
        w.look();
        expect(onChange).toHaveBeenCalledTimes(1);
    });
});

describe('the terminal keeps keyboard focus (#2184)', () => {
    afterEach(() => { document.body.innerHTML = ''; });

    test('when the window blurs with the frame active, focus goes back to the element that held it', () => {
        const input = document.createElement('input');
        const frame = document.createElement('iframe');
        document.body.append(input, frame);
        const stop = keepFocusOut(document, window, () => frame);
        input.focus();
        frame.focus();
        expect(document.activeElement).toBe(frame);
        window.dispatchEvent(new Event('blur'));
        expect(document.activeElement).toBe(input);
        stop();
        frame.focus();
        window.dispatchEvent(new Event('blur'));
        expect(document.activeElement).toBe(frame);
    });
});

describe('keepFocusOut with an allow gate', () => {
    afterEach(() => { document.body.innerHTML = ''; });

    test('the frame keeps focus only while allow() says so', () => {
        const input = document.createElement('input');
        const frame = document.createElement('iframe');
        document.body.append(input, frame);
        let ok = false;
        const stop = keepFocusOut(document, window, () => frame, () => ok);
        input.focus();
        frame.focus();
        window.dispatchEvent(new Event('blur'));
        expect(document.activeElement).toBe(input);
        ok = true;
        frame.focus();
        window.dispatchEvent(new Event('blur'));
        expect(document.activeElement).toBe(frame);
        stop();
    });
});

describe('ViewFrame draws only an allow-scripts sandbox', () => {
    afterEach(() => { document.body.innerHTML = ''; });

    test('the iframe is sandbox="allow-scripts" exactly, inside the host frame for a panel, bare and clipped for an overlay', async () => {
        const { default: ViewFrame } = await import('./ViewFrame.svelte');
        const plugin = { cplugId: 'pet', name: 'Pet', unverified: false, declared: { routes: ['feed'], tools: [] } };
        const t = (k: string) => k;
        const panel = document.createElement('div');
        const overlay = document.createElement('div');
        document.body.append(panel, overlay);
        const a = mount(ViewFrame, { target: panel, props: { plugin, view: 'walk', surface: 'panel', t } });
        const b = mount(ViewFrame, { target: overlay, props: { plugin, view: 'walk', surface: 'overlay', t } });
        await tick();
        await flush();
        flushSync();
        const frames = [panel, overlay].map((c) => c.querySelector('iframe'));
        for (const f of frames) {
            expect(f?.getAttribute('sandbox')).toBe('allow-scripts');
            expect(f?.getAttribute('src')).toBe('/api/v1/cplugs/pet/view/walk/T/index.html');
        }
        expect(panel.querySelector('[data-cplug-box] iframe')).not.toBeNull();
        expect(panel.querySelector('[data-cplug-mark]')).not.toBeNull();
        expect(overlay.querySelector('[data-cplug-frame]')).toBeNull();
        expect(frames[1]?.getAttribute('style')).toContain("clip-path: path('M0 0')");
        unmount(a);
        unmount(b);
    });

    test('a panel frame sits behind a host gate until the owner clicks it; an overlay has none (#2184 review)', async () => {
        const { default: ViewFrame } = await import('./ViewFrame.svelte');
        const plugin = { cplugId: 'pet', name: 'Pet', unverified: false, declared: { routes: [], tools: [] } };
        const panel = document.createElement('div');
        const overlay = document.createElement('div');
        document.body.append(panel, overlay);
        const a = mount(ViewFrame, { target: panel, props: { plugin, view: 'walk', surface: 'panel', t: (k: string) => k } });
        const b = mount(ViewFrame, { target: overlay, props: { plugin, view: 'walk', surface: 'overlay', t: (k: string) => k } });
        await tick();
        await flush();
        flushSync();
        expect(overlay.querySelector('[data-cplug-gate]')).toBeNull();
        const gate = panel.querySelector<HTMLButtonElement>('[data-cplug-gate]');
        expect(gate).not.toBeNull();
        gate?.click();
        flushSync();
        expect(panel.querySelector('[data-cplug-gate]')).toBeNull();
        window.dispatchEvent(new Event('focus'));
        flushSync();
        expect(panel.querySelector('[data-cplug-gate]')).not.toBeNull();
        unmount(a);
        unmount(b);
    });

    test('primary pointerdown arms the panel gate synchronously on 1 click while secondary/ctrl pointerdown leaves it armed off', async () => {
        const { default: ViewFrame } = await import('./ViewFrame.svelte');
        const { callViewTool } = await import('./api');
        const toolMock = vi.mocked(callViewTool);
        toolMock.mockClear();

        const plugin = { cplugId: 'pet', name: 'Pet', unverified: false, declared: { routes: [], tools: ['pet_say'] } };
        const host = document.createElement('div');
        document.body.append(host);
        const m = mount(ViewFrame, { target: host, props: { plugin, view: 'walk', surface: 'panel', t: (k: string) => k } });
        await tick();
        await flush();
        flushSync();

        const frame = host.querySelector('iframe')!;
        const posted: Record<string, unknown>[] = [];
        vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation((msg: unknown) => {
            posted.push(msg as Record<string, unknown>);
        });
        frame.dispatchEvent(new Event('load'));
        const nonce = posted.find((x) => x.verb === 'init')?.nonce as string;
        const focusSpy = vi.spyOn(frame, 'focus');

        const gate = host.querySelector<HTMLButtonElement>('[data-cplug-gate]')!;
        expect(gate).not.toBeNull();

        gate.dispatchEvent(new PointerEvent('pointerdown', { button: 2, bubbles: true }));
        expect(host.querySelector('.cu-gate__shield')).not.toBeNull();
        gate.dispatchEvent(new PointerEvent('pointerdown', { button: 0, ctrlKey: true, bubbles: true }));
        gate.dispatchEvent(new MouseEvent('click', { button: 0, ctrlKey: true, bubbles: true }));
        flushSync();
        expect(host.querySelector('.cu-gate__shield')).not.toBeNull();

        expect(gate.getAttribute('title')).toBeNull();
        expect(gate.getAttribute('aria-label')).toBe('cplug_ui.panel_activate');
        const pd = new PointerEvent('pointerdown', { button: 0, ctrlKey: false, bubbles: true, cancelable: true });
        gate.dispatchEvent(pd);
        expect(pd.defaultPrevented).toBe(true);
        expect(host.querySelector('[data-cplug-gate]')).toBeNull();
        expect(focusSpy).toHaveBeenCalledTimes(1);

        window.dispatchEvent(new MessageEvent('message', {
            source: frame.contentWindow,
            data: { nonce, verb: 'tool.call', id: 'pd-1', tool: 'pet_say', args: { msg: 'one-click' } },
        }));
        await flush();
        expect(toolMock).toHaveBeenCalledExactlyOnceWith('pet', 'pet_say', { msg: 'one-click' });
        unmount(m);
    });

    test('an overlay whose frame loads a second document is unmounted (#2184)', async () => {
        const { default: ViewFrame } = await import('./ViewFrame.svelte');
        const plugin = { cplugId: 'pet', name: 'Pet', unverified: false, declared: { routes: [], tools: [] } };
        const host = document.createElement('div');
        document.body.append(host);
        const m = mount(ViewFrame, { target: host, props: { plugin, view: 'walk', surface: 'overlay', t: (k: string) => k } });
        await tick();
        await flush();
        flushSync();
        const frame = host.querySelector('iframe');
        expect(frame).not.toBeNull();
        frame?.dispatchEvent(new Event('load'));
        frame?.dispatchEvent(new Event('load'));
        await tick();
        flushSync();
        expect(host.querySelector('iframe')).toBeNull();
        unmount(m);
    });

    test('ViewFrame blocks tool.call until owner click for panel/page, allows menu on open, and always blocks overlay', async () => {
        const { default: ViewFrame } = await import('./ViewFrame.svelte');
        const { callViewTool } = await import('./api');
        const toolMock = vi.mocked(callViewTool);
        toolMock.mockClear();

        const plugin = { cplugId: 'pet', name: 'Pet', unverified: false, declared: { routes: [], tools: ['pet_say'] } };
        const t = (k: string) => k;

        const mountAndInit = async (props: { surface: 'panel' | 'overlay'; viewRole?: 'panel' | 'page' | 'menu' | 'overlay' }) => {
            const host = document.createElement('div');
            document.body.append(host);
            const m = mount(ViewFrame, { target: host, props: { plugin, view: 'walk', ...props, t } });
            await tick();
            await flush();
            flushSync();
            const frame = host.querySelector('iframe')!;
            expect(frame).not.toBeNull();
            const posted: Record<string, unknown>[] = [];
            vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation((msg: unknown) => {
                posted.push(msg as Record<string, unknown>);
            });
            frame.dispatchEvent(new Event('load'));
            const initMsg = posted.find((x) => x.verb === 'init');
            expect(typeof initMsg?.nonce).toBe('string');
            const sendTool = (id: string) => {
                window.dispatchEvent(new MessageEvent('message', {
                    source: frame.contentWindow,
                    data: { nonce: initMsg!.nonce, verb: 'tool.call', id, tool: 'pet_say', args: { msg: id } },
                }));
            };
            return { host, m, posted, nonce: initMsg!.nonce as string, sendTool };
        };

        const panel = await mountAndInit({ surface: 'panel' });
        panel.sendTool('p-unarmed');
        await flush();
        expect(toolMock).not.toHaveBeenCalled();
        expect(panel.posted.find((x) => x.id === 'p-unarmed')).toEqual({ nonce: panel.nonce, id: 'p-unarmed', ok: false, error: 'not_armed' });

        panel.host.querySelector<HTMLButtonElement>('[data-cplug-gate]')!.click();
        flushSync();
        panel.sendTool('p-armed');
        await flush();
        expect(toolMock).toHaveBeenCalledExactlyOnceWith('pet', 'pet_say', { msg: 'p-armed' });
        expect(panel.posted.find((x) => x.id === 'p-armed')).toEqual({ nonce: panel.nonce, id: 'p-armed', ok: true, result: { ok: true, text: 'ok' } });

        window.dispatchEvent(new Event('focus'));
        flushSync();
        panel.sendTool('p-disarmed');
        await flush();
        expect(toolMock).toHaveBeenCalledTimes(1);
        expect(panel.posted.find((x) => x.id === 'p-disarmed')).toEqual({ nonce: panel.nonce, id: 'p-disarmed', ok: false, error: 'not_armed' });
        unmount(panel.m);

        toolMock.mockClear();
        const page = await mountAndInit({ surface: 'panel', viewRole: 'page' });
        page.sendTool('pg-unarmed');
        await flush();
        expect(toolMock).not.toHaveBeenCalled();
        expect(page.posted.find((x) => x.id === 'pg-unarmed')).toEqual({ nonce: page.nonce, id: 'pg-unarmed', ok: false, error: 'not_armed' });
        page.host.querySelector<HTMLButtonElement>('[data-cplug-gate]')!.click();
        flushSync();
        page.sendTool('pg-armed');
        await flush();
        expect(toolMock).toHaveBeenCalledExactlyOnceWith('pet', 'pet_say', { msg: 'pg-armed' });
        unmount(page.m);

        toolMock.mockClear();
        const menu = await mountAndInit({ surface: 'panel', viewRole: 'menu' });
        menu.sendTool('m-open');
        await flush();
        expect(toolMock).toHaveBeenCalledExactlyOnceWith('pet', 'pet_say', { msg: 'm-open' });
        window.dispatchEvent(new Event('focus'));
        flushSync();
        menu.sendTool('m-disarmed');
        await flush();
        expect(toolMock).toHaveBeenCalledTimes(1);
        expect(menu.posted.find((x) => x.id === 'm-disarmed')).toEqual({ nonce: menu.nonce, id: 'm-disarmed', ok: false, error: 'not_armed' });
        unmount(menu.m);

        toolMock.mockClear();
        const overlay = await mountAndInit({ surface: 'overlay' });
        overlay.sendTool('ov-1');
        await flush();
        expect(toolMock).not.toHaveBeenCalled();
        expect(overlay.posted.find((x) => x.id === 'ov-1')).toEqual({ nonce: overlay.nonce, id: 'ov-1', ok: false, error: 'not_armed' });
        unmount(overlay.m);
    });
});

describe('ui.share (#2562): the menu-to-page link', () => {
    function frameOf(relay: ReturnType<typeof createShareRelay>, install: string, id: string) {
        const posted: Record<string, unknown>[] = [];
        const window = { postMessage: (m: unknown) => posted.push(m as Record<string, unknown>) };
        const bridge = createBridge({
            nonce: id, frame: () => window, declared: { routes: [], tools: [] }, callRoute: async () => ({}), viewport: () => VIEWPORT,
            features: () => ['share'], onShare: (value) => relay.share(install, id, value),
        });
        const off = relay.register(install, id, (value) => bridge.send('shared', { value }));
        const share = (value: unknown) => bridge.handle({ source: window, data: { nonce: id, verb: 'ui.share', id: 's1', value } });
        return { bridge, posted, window, share, off, shared: () => posted.filter((m) => m.verb === 'shared').map((m) => m.value) };
    }

    test('a share reaches the other frame of the same install, not the sender and not another plugin\'s frame', () => {
        const relay = createShareRelay();
        const a = frameOf(relay, 'install-1', 'a'.repeat(32));
        const b = frameOf(relay, 'install-1', 'b'.repeat(32));
        const other = frameOf(relay, 'install-2', 'c'.repeat(32));
        for (const f of [a, b, other]) f.bridge.init();
        a.share({ run: 'r1' });
        expect(b.shared()).toEqual([{ run: 'r1' }]);
        expect(a.shared()).toEqual([]);
        expect(other.shared()).toEqual([]);
        expect(a.posted.find((m) => m.id === 's1')).toEqual({ nonce: 'a'.repeat(32), id: 's1', ok: true });
        expect(b.posted.find((m) => m.verb === 'init')?.features).toEqual(['share']);
    });

    test('the 4 KiB cap counts UTF-8 bytes: 1500 euro signs (4502 bytes, 1502 UTF-16 units) are too large, ascii of the same length is not', () => {
        expect(cleanShare('\u20ac'.repeat(1500))).toEqual({ ok: false, error: 'too_large' });
        expect(cleanShare('a'.repeat(1500)).ok).toBe(true);
        expect(cleanShare('\u20ac'.repeat(1000)).ok).toBe(true);
    });

    test('a value over 4 KiB is refused with too_large, a value that is not JSON with not_json, and neither is relayed', () => {
        const relay = createShareRelay();
        const a = frameOf(relay, 'install-1', 'a'.repeat(32));
        const b = frameOf(relay, 'install-1', 'b'.repeat(32));
        a.bridge.init(); b.bridge.init();
        a.share('x'.repeat(MAX_SHARE_BYTES + 1000));
        expect(a.posted.find((m) => m.id === 's1')).toMatchObject({ ok: false, error: 'too_large' });
        const cyclic: Record<string, unknown> = {};
        cyclic.self = cyclic;
        expect(relay.share('install-1', 'a'.repeat(32), cyclic)).toEqual({ ok: false, error: 'not_json' });
        let deep: unknown = 1;
        for (let i = 0; i < 12; i++) deep = { d: deep };
        expect(relay.share('install-1', 'a'.repeat(32), deep)).toEqual({ ok: false, error: 'too_large' });
        expect(b.shared()).toEqual([]);
        expect(relay.last('install-1')).toBeUndefined();
    });

    test('a frame that mounts later gets the last value when its init runs, and a dropped install forgets it', () => {
        const relay = createShareRelay();
        const a = frameOf(relay, 'install-1', 'a'.repeat(32));
        a.bridge.init();
        a.share({ run: 'r2' });
        const late = frameOf(relay, 'install-1', 'd'.repeat(32));
        expect(late.shared()).toEqual([]);
        late.bridge.init();
        relay.replay('install-1', 'd'.repeat(32));
        expect(late.shared()).toEqual([{ run: 'r2' }]);
        relay.retain(new Set());
        expect(relay.last('install-1')).toBeUndefined();
    });

    test('a burst is relayed at most 10 a second and its last value goes out as one trailing message', () => {
        vi.useFakeTimers();
        try {
            const relay = createShareRelay();
            const a = frameOf(relay, 'install-1', 'a'.repeat(32));
            const b = frameOf(relay, 'install-1', 'b'.repeat(32));
            a.bridge.init(); b.bridge.init();
            for (let i = 0; i < 25; i++) a.share({ n: i });
            expect(b.shared()).toHaveLength(10);
            vi.advanceTimersByTime(1100);
            expect(b.shared()).toHaveLength(11);
            expect(b.shared().at(-1)).toEqual({ n: 24 });
        } finally {
            vi.useRealTimers();
        }
    });

    test('with no share offered by the host the verb answers unavailable', () => {
        const r = rig();
        r.bridge.handle({ source: r.window, data: { nonce: NONCE, verb: 'ui.share', id: 'z', value: 1 } });
        expect(r.posted).toEqual([{ nonce: NONCE, id: 'z', ok: false, error: 'unavailable' }]);
    });
});

describe('frame-theme forwards --oc-* frame tokens for opaque-origin views', () => {
    afterEach(() => {
        document.documentElement.removeAttribute('style');
        document.documentElement.removeAttribute('data-theme');
        document.body.innerHTML = '';
    });

    test('readHostTheme and readTheme forward --oc-* vars alongside legacy tokens and font-mono', () => {
        expect(FRAME_OC_TOKENS).toEqual(expect.arrayContaining([
            '--oc-border', '--oc-font', '--oc-fs-body', '--oc-ground-page', '--oc-ground-hover',
            '--oc-line-button', '--oc-radius-control', '--oc-space-4', '--oc-text-bright',
        ]));
        const rootStyle = document.documentElement.style;
        rootStyle.setProperty('--font-mono', "'JetBrains Mono', monospace");
        rootStyle.setProperty('--oc-ground-page', '#02161e');
        rootStyle.setProperty('--oc-text-bright', '#ffffff');
        rootStyle.setProperty('--oc-font', 'var(--font-mono, ui-monospace, monospace)');
        rootStyle.setProperty('--oc-fs-body', '12px');
        rootStyle.setProperty('--oc-space-4', '16px');
        rootStyle.setProperty('--oc-border', '1px');
        rootStyle.setProperty('--oc-radius-control', 'clamp(0px, 2px, 4px)');
        rootStyle.setProperty('--oc-line-button', 'color-mix(in srgb, #02161e, #cbd6d9 65%)');
        rootStyle.setProperty('--oc-ground-hover', 'url(https://evil.example/leak.png)');

        const theme = readHostTheme();
        expect(theme).toEqual(readTheme());
        expect(theme['ground-page']).toBe('#02161e');
        expect(theme['font-mono']).toBe("'JetBrains Mono', monospace");
        expect(theme['--oc-ground-page']).toBe('#02161e');
        expect(theme['--oc-text-bright']).toBe('#ffffff');
        expect(theme['--oc-font']).toBe('var(--font-mono, ui-monospace, monospace)');
        expect(theme['--oc-fs-body']).toBe('12px');
        expect(theme['--oc-space-4']).toBe('16px');
        expect(theme['--oc-border']).toBe('1px');
        expect(theme['--oc-radius-control']).toBe('clamp(0px, 2px, 4px)');
        expect(theme['--oc-line-button']).toBe('color-mix(in srgb, #02161e, #cbd6d9 65%)');
        expect(theme['--oc-ground-hover']).toBeUndefined();
    });

    test('ViewFrame includes --oc-* vars in init.theme and emits theme updates on host theme changes', async () => {
        const { default: ViewFrame } = await import('./ViewFrame.svelte');
        document.documentElement.style.setProperty('--oc-ground-page', '#02161e');
        document.documentElement.style.setProperty('--oc-fs-body', '12px');

        const host = document.createElement('div');
        document.body.append(host);
        const plugin = { cplugId: 'pet', name: 'Pet', unverified: false, declared: { routes: [], tools: [] } };
        const m = mount(ViewFrame, { target: host, props: { plugin, view: 'walk', surface: 'panel', t: (k: string) => k } });
        await tick();
        await flush();
        flushSync();

        const frame = host.querySelector('iframe')!;
        const posted: Record<string, unknown>[] = [];
        vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation((msg: unknown) => {
            posted.push(msg as Record<string, unknown>);
        });
        frame.dispatchEvent(new Event('load'));

        const initMsg = posted.find((x) => x.verb === 'init') as { theme?: Record<string, string> } | undefined;
        expect(initMsg?.theme?.['ground-page']).toBe('#02161e');
        expect(initMsg?.theme?.['--oc-ground-page']).toBe('#02161e');
        expect(initMsg?.theme?.['--oc-fs-body']).toBe('12px');

        const updates: Record<string, string>[] = [];
        const stop = watchTheme((vals) => updates.push(vals));
        document.documentElement.setAttribute('data-theme', 'light');
        document.documentElement.style.setProperty('--oc-ground-page', '#f4f6f8');
        await flush();
        expect(updates.at(-1)?.['--oc-ground-page']).toBe('#f4f6f8');
        expect(posted.some((x) => x.verb === 'theme' && (x.theme as Record<string, string>)?.['--oc-ground-page'] === '#f4f6f8')).toBe(true);

        stop();
        unmount(m);
    });
});
