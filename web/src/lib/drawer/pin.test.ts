// @vitest-environment jsdom
import assert from 'node:assert/strict';
import { afterEach, it, vi } from 'vitest';
import { fakeStorage, freshDrawer } from './test-support';

afterEach(() => {
    vi.restoreAllMocks();
    document.body.className = '';
});

async function makeSandbox({ width = 1280, throws = false } = {}) {
    const store = fakeStorage({}, throws);
    const backdrop = { hidden: true };
    const closeCalls = { count: 0 };
    const resizeHandlers: Array<() => void> = [];
    Object.defineProperty(window, 'innerWidth', { value: width, configurable: true, writable: true });
    vi.spyOn(window, 'addEventListener').mockImplementation(((type: string, fn: () => void) => {
        if (type === 'resize') resizeHandlers.push(fn);
    }) as typeof window.addEventListener);
    document.body.className = '';
    const d = await freshDrawer({ localStorage: store });
    const sidebar = {
        isOpen: true,
        backdrop: backdrop as unknown as HTMLElement,
        toggleBtn: null,
        _transientOpen: false,
        close() { closeCalls.count++; this.isOpen = false; },
    };
    d.env.SessionSidebar = sidebar;
    function resizeTo(nextWidth: number): void {
        (window as unknown as { innerWidth: number }).innerWidth = nextWidth;
        resizeHandlers.forEach((fn) => fn());
    }
    return {
        env: d.env,
        Pin: d.Pin as typeof d.Pin & Record<string, unknown>,
        sidebar,
        bodyClasses: { has: (c: string) => document.body.classList.contains(c) },
        backdrop,
        closeCalls,
        store,
        resizeTo,
        resizeHandlerCount: () => resizeHandlers.length,
    };
}

it('A WIDE VIEWPORT DOCKS, with nothing stored and nothing to store', async () => {
    const { Pin, bodyClasses } = await makeSandbox({ width: 1280 });
    Pin.init();
    assert.equal(bodyClasses.has('session-sidebar-pinned'), true,
        'a desktop drawer must dock so it never covers the terminal');
    assert.equal(Pin.isEffectivelyPinned(), true);
});

it('NOTHING IS READ FROM STORAGE: storage that throws still docks', async () => {
    // there is nothing
    const { Pin, bodyClasses } = await makeSandbox({ width: 1280, throws: true });
    Pin.init();
    assert.equal(bodyClasses.has('session-sidebar-pinned'), true);
});

it('THE PREFERENCE IS GONE: no toggle and no storage key are exported', async () => {
    const { Pin } = await makeSandbox();
    assert.equal(typeof Pin.toggle, 'undefined',
        'docking is derived now; a toggle would be a second source of truth');
    assert.equal(typeof Pin.STORAGE_KEY, 'undefined');
});

it('a phone OVERLAYS rather than docking', async () => {
    const { Pin, bodyClasses } = await makeSandbox({ width: 390 });
    Pin.init();
    assert.equal(bodyClasses.has('session-sidebar-pinned'), false,
        'a docked 320px bar on a phone leaves nothing for the terminal');
    assert.equal(Pin.isEffectivelyPinned(), false);
});

it('crossing the breakpoint live re-evaluates without a reload', async () => {
    const { Pin, bodyClasses, resizeTo } = await makeSandbox({ width: 1280 });
    Pin.init();
    assert.equal(bodyClasses.has('session-sidebar-pinned'), true);

    resizeTo(390);
    assert.equal(bodyClasses.has('session-sidebar-pinned'), false, 'rotating to a phone undocks');
    assert.equal(Pin.isEffectivelyPinned(), false);

    resizeTo(1280);
    assert.equal(bodyClasses.has('session-sidebar-pinned'), true, 'back to wide re-docks');
    assert.equal(Pin.isEffectivelyPinned(), true);
});

it('a viewport with NO reported width is not treated as a phone', async () => {
    const { Pin, bodyClasses } = await makeSandbox({ width: 0 });
    Pin.init();
    assert.equal(Pin.isEffectivelyPinned(), true);
    assert.equal(bodyClasses.has('session-sidebar-pinned'), true);
});

it('the breakpoint is the app-wide 700px, inclusive', async () => {
    const { Pin } = await makeSandbox();
    assert.equal(Pin.MOBILE_MAX_PX, 700);
    const at = await makeSandbox({ width: 700 });
    at.Pin.init();
    assert.equal(at.Pin.isEffectivelyPinned(), false, '700 is still mobile');
    const over = await makeSandbox({ width: 701 });
    over.Pin.init();
    assert.equal(over.Pin.isEffectivelyPinned(), true);
});

it('a docked bar survives a conversation switch; an overlaid one closes', async () => {
    const docked = await makeSandbox({ width: 1280 });
    docked.Pin.init();
    docked.Pin.closeAfterSwitch();
    assert.equal(docked.closeCalls.count, 0,
        'a docked bar covers nothing, so switching must leave it alone');
    assert.equal(docked.sidebar.isOpen, true);

    const overlaid = await makeSandbox({ width: 390 });
    overlaid.Pin.init();
    overlaid.Pin.closeAfterSwitch();
    assert.equal(overlaid.closeCalls.count, 1,
        'an overlay is covering the conversation the user just picked');
});

it('a docked bar drops its backdrop; an overlaid open one keeps it', async () => {
    const docked = await makeSandbox({ width: 1280 });
    docked.Pin.init();
    assert.equal(docked.backdrop.hidden, true, 'a docked bar covers nothing to click away');

    const overlaid = await makeSandbox({ width: 390 });
    overlaid.Pin.init();
    assert.equal(overlaid.backdrop.hidden, false, 'an overlay still needs its dismiss target');
});

it('a closed bar never applies the layout shift, docked or not', async () => {
    const { Pin, sidebar, bodyClasses, backdrop } = await makeSandbox();
    Pin.init();
    sidebar.isOpen = false;
    Pin.apply();
    assert.equal(bodyClasses.has('session-sidebar-pinned'), false);
    assert.equal(backdrop.hidden, true);
});

it('init is idempotent - re-entering the terminal screen rewires nothing', async () => {
    const { Pin, resizeHandlerCount } = await makeSandbox();
    Pin.init();
    assert.equal(resizeHandlerCount(), 1);
    Pin.init();
    Pin.init();
    assert.equal(resizeHandlerCount(), 1, 'must not stack duplicate resize listeners');
    assert.equal(Pin.isEffectivelyPinned(), true);
});


it('DOCKING OR UNDOCKING REFITS THE TERMINAL ONCE PER CHANGE (the refit the retired pin script owned, FE-6)', async () => {
    const { Pin, env, resizeTo } = await makeSandbox({ width: 1280 });
    const requestFit = vi.fn();
    env.TerminalLayout = { requestFit };
    Pin.init();
    assert.deepEqual(requestFit.mock.calls, [['sidebar-pin']], 'first dock refits');
    resizeTo(1300);
    assert.equal(requestFit.mock.calls.length, 1, 'same layout, no second refit');
    resizeTo(390);
    assert.equal(requestFit.mock.calls.length, 2, 'undocking refits');
});
