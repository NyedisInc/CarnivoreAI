/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, ledger: { status: 'ok', data: null, fetchedAt: null, error: null }, primarySessionId: () => '' };
});
vi.mock('../../opscenter/cells/registry', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  const { ScopeProbe } = await import('../session-rail/test-support.svelte');
  return { ...real, entryFor: () => ({ component: ScopeProbe }) };
});

import DrawerZone from './DrawerZone.svelte';
import { drawerZone } from './zone-store.svelte';
import { ZONE_FIELD } from './zone-model';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { configureSheet } from '../../opscenter/widgets/chrome/configure.svelte';
import { alertCenter } from '../app-alerts/alerts.svelte';
import { setLocale } from '../i18n/index.svelte';
import '../../opscenter/cells/questions/placement';

setLocale('en');

const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};
proto.matches = ((original) =>
  function (this: HTMLElement, selector: string) {
    return selector === ':popover-open' ? true : (original as (s: string) => boolean).call(this, selector);
  })(proto.matches);

let host: HTMLElement | null = null;
let instance: unknown = null;
let written: { items: { widget: string; instance?: string; options?: Record<string, unknown> }[] }[] = [];

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  written = [];
  alertCenter.sources = [{ id: 'backup_health', label_key: 'app_alert.source.backup_health', icon: 'database' }];
  alertCenter.status = 'ok';
  layoutEditor.active = false;
  configureSheet.slot = null;
  const stored = {
    v: 1,
    items: [
      { widget: 'core.questions', options: { kind_all: false, kind_huddle: false, kind_automations: false } },
      { widget: 'core.questions', instance: 'i2' },
    ],
  };
  (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
    read: () => stored,
    write: async (field: string, value: unknown) => {
      expect(field).toBe(ZONE_FIELD);
      written.push(value as never);
      return { status: 'committed' };
    },
    follow: () => () => {},
  };
  drawerZone.reload();
  host = document.createElement('div');
  host.id = 'session-sidebar-ledger';
  document.body.appendChild(host);
  instance = mount(DrawerZone, { target: host });
  flushSync();
});

afterEach(() => {
  if (instance) unmount(instance as never);
  instance = null;
  host?.remove();
  host = null;
  configureSheet.slot = null;
  alertCenter.sources = [];
  alertCenter.status = 'idle';
  delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
});

const cells = (): HTMLElement[] => [...host!.querySelectorAll<HTMLElement>('[data-zone-cell="core.questions"]')];

describe('two copies in the widget area', () => {
  test('each copy wears the head its own options pick', () => {
    const [first, second] = cells();
    expect(cells()).toHaveLength(2);
    expect(first!.querySelector('.oc-frame-name')?.textContent).toBe('approvals');
    expect(first!.querySelector('[data-corner] svg')?.getAttribute('data-icon')).toBe('check-circle');
    expect(second!.querySelector('.oc-frame-name')?.textContent).toBe('waiting on you');
    expect(second!.querySelector('[data-corner] svg')?.getAttribute('data-icon')).toBe('bell');
  });

  test('the icon menu of the second copy holds exactly the four ticks, all disables the rest, a tick keeps the menu open and is stored on that copy alone', () => {
    cells()[1]!.querySelector<HTMLElement>('[data-corner]')!.click();
    flushSync();
    const ticks = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>('.acm-menu [data-node^="option:"]')];
    expect(ticks()).toHaveLength(4);
    expect(ticks().every((tick) => tick.getAttribute('role') === 'menuitemcheckbox')).toBe(true);
    const at = (name: string): HTMLElement => document.querySelector<HTMLElement>(`.acm-menu [data-node="option:${name}"]`)!;
    expect(at('kind_huddle').getAttribute('aria-disabled')).toBe('true');
    at('kind_all').click();
    flushSync();
    expect(document.querySelector('.acm-menu'), 'a tick keeps the menu open').not.toBeNull();
    expect(at('kind_huddle').getAttribute('aria-disabled')).toBeNull();
    at('kind_huddle').click();
    flushSync();
    expect(drawerZone.items[0]!.options).toEqual({ kind_all: false, kind_huddle: false, kind_automations: false });
    expect(drawerZone.items[1]!.options).toEqual({ kind_all: false, kind_huddle: false });
    expect(written.at(-1)!.items[1]).toMatchObject({ instance: 'i2', options: { kind_all: false, kind_huddle: false } });
    expect(second()!.querySelector('[data-corner] svg')?.getAttribute('data-icon')).toBe('bell');
  });
});

const second = (): HTMLElement | undefined => cells()[1];
