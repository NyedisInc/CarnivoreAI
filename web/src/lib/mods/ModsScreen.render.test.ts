/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const stub = vi.hoisted(() => ({
  listMods: vi.fn(),
  setEnabled: vi.fn(),
  removeLocal: vi.fn(),
  uninstallCatalog: vi.fn(),
}));
vi.mock('./mods-api', () => stub);
const openCatalogScreen = vi.hoisted(() => vi.fn());
vi.mock('../catalog/screen-host', () => ({ openCatalogScreen }));

import ModsScreen from './ModsScreen.svelte';
import { data } from './store.svelte';

const entry = { description: null, path: '/p', is_mod: true, present: true, registered_in: 2, groups_total: 2 };
const catalogMod = { ...entry, mod_id: 'm_cat', name: 'fancy', version: '1.0.0', source: 'catalog', install_id: 'inst_9', item_id: 'a/fancy', state: 'on', removable: false };
const localMod = { ...entry, mod_id: 'm_loc', name: 'working-on', version: '0.1.0', source: 'local', install_id: null, item_id: null, state: 'off', registered_in: 0, removable: true };
const partialMod = { ...localMod, mod_id: 'm_par', name: 'half', state: 'partial', registered_in: 1 };
const response = (over: Record<string, unknown> = {}, mods: unknown[] = [catalogMod, localMod]) => ({
  mods, groups: [{ label: 'a', members: ['a'], real_path_display: '/a', status: 'ok' }], claude: { version: '2.1.295', ok: true }, accounts: { status: 'ok' }, ...over,
});

let app: ReturnType<typeof mount> | null = null;
const settle = async () => {
  for (let i = 0; i < 6; i++) await tick();
  flushSync();
};
const q = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

async function open(body = response()) {
  stub.listMods.mockResolvedValue(body);
  data.status = 'loading';
  data.list = null;
  app = mount(ModsScreen, { target: document.body, props: { embedded: true } });
  await settle();
}

beforeEach(() => {
  Object.values(stub).forEach((fn) => fn.mockReset());
  openCatalogScreen.mockReset();
  stub.setEnabled.mockResolvedValue({ results: [{ real: '/a', members: ['a'], status: 'ok' }] });
  stub.removeLocal.mockResolvedValue({ results: [] });
  stub.uninstallCatalog.mockResolvedValue({});
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

test('a catalog and a local mod render as the one warez card, with no source tag or state word', async () => {
  await open();
  expect(q('[data-mod="m_cat"] .catalog-card__brief')).not.toBeNull();
  expect(q('[data-mod="m_loc"] .catalog-card__brief')).not.toBeNull();
  expect(document.querySelector('[data-mod-source]')).toBeNull();
  expect(document.querySelector('[data-mod="m_loc"] [data-mod-state-label]')).toBeNull();
});

test('the switch asks for the other state', async () => {
  await open();
  q('[data-mod="m_loc"] [data-mod-switch]').click();
  await settle();
  expect(stub.setEnabled).toHaveBeenCalledWith('m_loc', true);
  q('[data-mod="m_cat"] [data-mod-switch]').click();
  await settle();
  expect(stub.setEnabled).toHaveBeenCalledWith('m_cat', false);
});

test('remove uses the catalog uninstall for a catalog row and the mod route for a local row, after a confirm', async () => {
  await open();
  q('[data-mod="m_cat"] [data-mod-remove]').click();
  await settle();
  expect(stub.uninstallCatalog).not.toHaveBeenCalled();
  q('[data-mod="m_cat"] [data-mod-remove-confirm]').click();
  await settle();
  expect(stub.uninstallCatalog).toHaveBeenCalledWith('inst_9');
  expect(stub.removeLocal).not.toHaveBeenCalled();
  q('[data-mod="m_loc"] [data-mod-remove]').click();
  await settle();
  q('[data-mod="m_loc"] [data-mod-remove-confirm]').click();
  await settle();
  expect(stub.removeLocal).toHaveBeenCalledWith('m_loc');
  expect(stub.uninstallCatalog).toHaveBeenCalledTimes(1);
});

test('get more on warez opens warez on the mod kind', async () => {
  await open();
  q('[data-mods-get-more]').click();
  expect(openCatalogScreen).toHaveBeenCalledWith({ kind: 'mod' });
});

test('a partial mod reads on in 1 of 2', async () => {
  await open(response({}, [partialMod]));
  expect(q('[data-mod="m_par"] [data-mod-state-label]').textContent).toBe('on in 1 of 2');
});

test('accounts_unreadable says so and disables every switch and remove', async () => {
  await open(response({ accounts: { status: 'accounts_unreadable' } }));
  expect(q('[data-mods-locked]')).not.toBeNull();
  for (const sel of ['[data-mod-switch]', '[data-mod-remove]']) {
    const all = [...document.querySelectorAll<HTMLButtonElement>(sel)];
    expect(all).toHaveLength(2);
    expect(all.every((b) => b.disabled)).toBe(true);
  }
});

test('a settings file that did not take a write is named, not hidden', async () => {
  await open();
  stub.setEnabled.mockResolvedValue({ results: [{ real: '/home/x/settings.json', members: [], status: 'settings_unwritable' }] });
  q('[data-mod="m_loc"] [data-mod-switch]').click();
  await settle();
  expect(q('[data-mods-notice]').textContent).toContain('could not be written');
});
