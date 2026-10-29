/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MENU_CHOOSE, MENU_CLOSE, MENU_HIDE, MENU_SHOW } from '../lib/drawer-tabs/menu-remote-messages';
import { remoteMenuHost, setRemoteMenuHost } from '../lib/drawer-tabs/menu-remote';
import { installRemoteMenus, remoteMenuOpen } from './remote-menu';

afterEach(() => setRemoteMenuHost(null));

describe('installRemoteMenus', () => {
  it('does nothing on a page that is not framed', () => {
    installRemoteMenus();
    expect(remoteMenuHost()).toBeNull();
  });

  it('posts a menu to the parent, runs a choice from the parent by its path, closes on the parent\'s close, and tells the parent when it is hidden', () => {
    const parent = { postMessage: vi.fn() };
    const real = Object.getOwnPropertyDescriptor(window, 'parent');
    Object.defineProperty(window, 'parent', { configurable: true, value: parent });
    try {
      installRemoteMenus();
      const choose = vi.fn();
      const close = vi.fn();
      remoteMenuHost()!.show(3, { label: 'm', anchor: null, nodes: [{ id: 'a', label: 'a', runs: true }] }, { choose, close });
      expect(parent.postMessage).toHaveBeenCalledWith({ type: MENU_SHOW, id: 3, label: 'm', anchor: null, nodes: [{ id: 'a', label: 'a', runs: true }] }, location.origin);
      expect(remoteMenuOpen()).toBe(true);
      const say = (data: object, source: unknown = parent) => window.dispatchEvent(new MessageEvent('message', { data, origin: location.origin, source: source as Window }));
      say({ type: MENU_CHOOSE, id: 3, path: ['a'] }, window);
      expect(choose).not.toHaveBeenCalled();
      say({ type: MENU_CHOOSE, id: 3, path: ['a'] });
      expect(choose).toHaveBeenCalledWith(['a']);
      const now = vi.spyOn(performance, 'now').mockReturnValue(10_000);
      window.dispatchEvent(new Event('pointerdown'));
      say({ type: MENU_CLOSE, id: 3 });
      expect(close).not.toHaveBeenCalled();
      now.mockReturnValue(10_000 + 1_000);
      say({ type: MENU_CLOSE, id: 3 });
      expect(close).toHaveBeenCalledTimes(1);
      now.mockRestore();
      remoteMenuHost()!.hide(3);
      expect(parent.postMessage).toHaveBeenLastCalledWith({ type: MENU_HIDE, id: 3 }, location.origin);
      expect(remoteMenuOpen()).toBe(false);
    } finally {
      if (real) Object.defineProperty(window, 'parent', real);
    }
  });
});
