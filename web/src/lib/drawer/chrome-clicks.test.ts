/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { claim, onGroupToggleClick } from './chrome-clicks';
import * as Store from './store';

const win = window as unknown as Record<string, unknown>;

function target(selectorAttrs: Record<string, string>): HTMLElement {
    const btn = document.createElement('button');
    for (const [k, v] of Object.entries(selectorAttrs)) btn.setAttribute(k, v);
    const inner = document.createElement('span');
    btn.append(inner);
    document.body.append(btn);
    return inner;
}

function clickOn(el: Element, ctrl: { repaint: () => void }): { claimed: boolean; stopped: boolean } {
    let stopped = false;
    const e = new MouseEvent('click', { bubbles: true });
    e.stopPropagation = () => { stopped = true; };
    Object.defineProperty(e, 'target', { value: el });
    return { claimed: claim(ctrl, e), stopped };
}

let ctrl: { repaint: () => void };
beforeEach(() => {
    document.body.innerHTML = '<div id="session-sidebar-live"></div>';
    ctrl = { repaint: vi.fn() as () => void };
});
afterEach(() => { delete win.CloudeWeb; vi.restoreAllMocks(); });

describe('chrome claim', () => {
    it('a fold button is claimed, stopped, folded, repainted and announced', () => {
        vi.spyOn(Store, 'toggleCollapsed').mockReturnValue(true);
        const r = clickOn(target({ 'data-group-toggle': 'pinned' }), ctrl);
        expect(r).toEqual({ claimed: true, stopped: true });
        expect(Store.toggleCollapsed).toHaveBeenCalledWith('pinned');
        expect(ctrl.repaint as ReturnType<typeof vi.fn>).toHaveBeenCalledTimes(1);
        expect(document.getElementById('session-sidebar-live')!.textContent).toBe('pinned group collapsed');
    });
    it('a Layout fold key announces the inverted word', () => {
        vi.spyOn(Store, 'toggleCollapsed').mockReturnValue(true);
        onGroupToggleClick(ctrl, target({ 'data-group-toggle': 'layout:u1' }).parentElement!);
        expect(document.getElementById('session-sidebar-live')!.textContent).toBe('layout:u1 group expanded');
    });
    it('an open rename box inside the fold button owns the click and folds nothing', () => {
        const spy = vi.spyOn(Store, 'toggleCollapsed');
        const r = clickOn(target({ class: 'session-sidebar-rename-edit' }), ctrl);
        expect(r).toEqual({ claimed: true, stopped: true });
        expect(spy).not.toHaveBeenCalled();
    });
    it('a shell-drawn target is claimed without stopping or folding', () => {
        win.CloudeWeb = { sidebarShell: { owns: () => true } };
        const spy = vi.spyOn(Store, 'toggleCollapsed');
        expect(clickOn(target({}), ctrl)).toEqual({ claimed: true, stopped: false });
        expect(spy).not.toHaveBeenCalled();
    });
    it('a plain row click is not claimed', () => {
        expect(clickOn(target({ class: 'session-sidebar-row' }), ctrl)).toEqual({ claimed: false, stopped: false });
    });
});
