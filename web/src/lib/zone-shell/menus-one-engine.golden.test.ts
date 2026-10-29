/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import type { LayoutMember } from '../../opscenter/layouts/api';
import { matchGolden } from './fixtures/golden';

const wire = vi.hoisted(() => ({
  toggled: [] as number[],
  layoutsData: [] as unknown[],
  openedLayouts: [] as string[],
}));

vi.mock('../../opscenter/layouts/broadcast.svelte', () => ({
  broadcastOn: (member: LayoutMember) => member.session_row_id <= 2,
  memberName: (member: LayoutMember) => `agent-${member.session_row_id}`,
  recipients: () => ({ receiving: 2, total: 3, busy: [] }),
  toggleBroadcast: async (member: LayoutMember) => { wire.toggled.push(member.session_row_id); return null; },
}));
vi.mock('../../opscenter/cells/terminal-live/Cell.svelte', async () => ({ default: (await import('./fixtures/EmptyStub.svelte')).default }));
vi.mock('../../opscenter/shell/WidgetHead.svelte', async () => ({ default: (await import('./fixtures/CornerStub.svelte')).default }));
vi.mock('../../opscenter/shell/frame-header.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../opscenter/shell/frame-header.svelte')>()),
  provideFrameHeader: () => ({ drawn: false, takesBars: true }),
}));
vi.mock('../../opscenter/api', () => ({ sessions: { data: [] } }));
vi.mock('../../opscenter/api/host', () => ({ openSession: () => {}, primarySessionId: () => null }));
vi.mock('../../opscenter/layouts/page.svelte', () => ({ openLayout: async (uuid: string) => { wire.openedLayouts.push(uuid); } }));
vi.mock('../layouts-bridge/api.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../layouts-bridge/api.svelte')>()),
  layouts: { get data() { return wire.layoutsData; }, refresh: async () => {} },
}));

import KeyHelp from '../catalog/KeyHelp.svelte';
import { CATALOG_KEY_ROWS } from '../catalog/keys';
import HitActions from '../deepsearch/HitActions.svelte';
import LayoutCommandBar from '../../opscenter/layouts/LayoutCommandBar.svelte';
import { layoutMode } from '../../opscenter/layouts/mode.svelte';
import WarroomModal from '../warroom/WarroomModal.svelte';
import { t } from '../i18n/index.svelte';

(HTMLElement.prototype as { togglePopover?: () => boolean }).togglePopover = () => true;
(HTMLElement.prototype as { showPopover?: () => void }).showPopover ??= () => {};
(HTMLElement.prototype as { hidePopover?: () => void }).hidePopover ??= () => {};
vi.stubGlobal('ResizeObserver', class { observe(): void {} disconnect(): void {} unobserve(): void {} });

const mounted: ReturnType<typeof mount>[] = [];
let host: HTMLElement;

beforeEach(() => {
  wire.toggled = [];
  wire.openedLayouts = [];
  wire.layoutsData = [];
  host = document.createElement('div');
  document.body.append(host);
});

afterEach(async () => {
  for (const one of mounted.splice(0)) await unmount(one);
  document.body.replaceChildren();
  layoutMode.uuid = '';
  layoutMode.members = [];
});

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i += 1) await tick();
  flushSync();
}

const panels = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>('[role="menu"]')];

function menu(): HTMLElement {
  const all = panels();
  expect(all, 'exactly one menu is open').toHaveLength(1);
  return all[0]!;
}

const rowIds = (): string[] => [...menu().querySelectorAll<HTMLElement>('[role^="menuitem"]')].map((el) => el.dataset['node'] ?? el.dataset['action'] ?? '');

describe('the catalog key help menu', () => {
  test('lists every binding and closes on Escape', async () => {
    mounted.push(mount(KeyHelp, { target: host, props: { t } }));
    flushSync();
    (host.querySelector('[data-keys-button]') as HTMLElement).click();
    await settle();
    expect(menu().textContent).toContain(CATALOG_KEY_ROWS[0]![0]);
    for (const [keys, label] of CATALOG_KEY_ROWS) {
      expect(menu().textContent, `row ${keys}`).toContain(t(label));
      expect(menu().textContent, `row ${keys}`).toContain(keys);
    }
    matchGolden('menu.keyhelp', menu());
    menu().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await settle();
    expect(panels()).toHaveLength(0);
  });
});

describe('the deep search hit "more" menu', () => {
  test('offers the same actions and runs the same handler', async () => {
    const calls: string[] = [];
    const controller = {
      layout: 'best',
      pickHit: () => calls.push('read'),
      go: () => calls.push('go'),
      branch: () => calls.push('branch'),
      copyLink: () => calls.push('link'),
      bookmark: () => calls.push('bookmark'),
      scopeTo: () => calls.push('scope'),
      showContext: () => calls.push('closest'),
    };
    const group = { sessionUuid: 's-1', conversationId: 'c-1' };
    const hit = { line: 3, entryUuid: 'u-3', bookmark: { id: 9 } };
    mounted.push(mount(HitActions, { target: host, props: { controller: controller as never, group: group as never, hit: hit as never, conv: 'live', name: 'nightly' } }));
    flushSync();
    (host.querySelector('[data-action="more"]') as HTMLElement).click();
    await settle();
    expect(rowIds().map((id) => id.replace(/^fork$/, 'branch'))).toEqual(['read', 'go', 'branch', 'link', 'bookmark', 'scope', 'closest']);
    matchGolden('menu.hit-more', menu());
    (menu().querySelector('[data-node="bookmark"], [data-action="bookmark"]') as HTMLElement).click();
    await settle();
    expect(calls).toEqual(['bookmark']);
    expect(panels(), 'a pick closes the menu').toHaveLength(0);
  });
});

describe('the layout command bar recipients menu', () => {
  test('one checkbox per member, a pick flips that member and the menu stays open', async () => {
    layoutMode.uuid = 'L1';
    layoutMode.name = 'work';
    layoutMode.members = [1, 2, 3].map((n) => ({ session_row_id: n, position: n }) as unknown as LayoutMember);
    mounted.push(mount(LayoutCommandBar, { target: host }));
    flushSync();
    (host.querySelector('[data-bar-toggle="command"]') as HTMLElement).click();
    flushSync();
    (host.querySelector('[data-bar-tool="recipients"]') as HTMLElement).click();
    await settle();
    const rows = [...document.querySelectorAll<HTMLElement>('[role="menuitemcheckbox"]')];
    expect(rows).toHaveLength(3);
    expect(rows.map((el) => el.getAttribute('aria-checked'))).toEqual(['true', 'true', 'false']);
    expect(rows.map((el) => el.textContent)).toEqual(expect.arrayContaining([expect.stringContaining('agent-1'), expect.stringContaining('agent-2'), expect.stringContaining('agent-3')]));
    matchGolden('menu.recipients', document.querySelector('[role="menu"]'));
    rows[2]!.click();
    await settle();
    expect(wire.toggled).toEqual([3]);
  });
});

describe('the war room modal layout picker', () => {
  test('lists every layout the session is in and opens the picked one', async () => {
    const member = { session_row_id: 7, session_uuid: 'su-7' };
    wire.layoutsData = [
      { layout_uuid: 'La', name: 'alpha', members: [member] },
      { layout_uuid: 'Lb', name: 'bravo', members: [member] },
    ];
    const info = { session: { id: 'ses_7' }, session_row_id: 7, tmux_session: 'carnivore_x', label: 'seven' };
    mounted.push(mount(WarroomModal, { target: host, props: { info: info as never, close: () => {} } }));
    await settle();
    (document.querySelector('[data-warroom-go="layout"]') as HTMLElement).click();
    await settle();
    expect([...menu().querySelectorAll('[role="menuitem"]')].map((el) => el.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
      expect.stringContaining('alpha'),
      expect.stringContaining('bravo'),
    ]);
    matchGolden('menu.warroom-layouts', menu());
    (menu().querySelectorAll('[role="menuitem"]')[1] as HTMLElement).click();
    await settle();
    expect(wire.openedLayouts).toEqual(['Lb']);
  });
});
