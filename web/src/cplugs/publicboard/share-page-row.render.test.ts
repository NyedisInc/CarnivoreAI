/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const host = vi.hoisted(() => ({ cplugEnabled: vi.fn(), openModal: vi.fn(async () => null), pages: [] as Array<{ id: string; key: string; src: string | null; title: string }> }));
vi.mock('../sdk', async (importOriginal) => ({ ...(await importOriginal<typeof import('../sdk')>()), cplugEnabled: host.cplugEnabled, openModal: host.openModal }));
vi.mock('../../lib/browser/pages.svelte', () => ({ pageById: (id: string) => host.pages.find((p) => p.id === id) ?? null }));

import '../../lib/item-menu/menus/all';
import { itemMenu } from '../../lib/item-menu/registry';
import type { RowMenuCtx } from '../../lib/item-menu/row-context';
import { resetPageRowActions } from '../sdk/page-row-actions';
import { publicboardCplug } from './index';
import ShareLinkModal from './ShareLinkModal.svelte';

const BOARD = { id: 'p1', key: 'app:/static/popout.html?tab=reviewboard&board=20261013-nav', src: '/static/popout.html?tab=reviewboard&board=20261013-nav', title: 'nav' };
const OTHER = { id: 'p2', key: 'app:/static/popout.html?tab=flow&page=f1', src: '/static/popout.html?tab=flow&page=f1', title: 'flow' };
const env = { close: vi.fn(), glyph: () => '' };

function pageCtx(id: string): RowMenuCtx {
  return { name: `browser:${id}`, label: 'row', kind: 'browser', isPage: true, owned: true, status: 'unknown', pluginItems: '' } as unknown as RowMenuCtx;
}
const menuIds = (id: string): string[] => (itemMenu('page', pageCtx(id), env)?.nodes ?? []).map((n) => n.id);

beforeEach(() => {
  host.pages = [BOARD, OTHER];
  host.openModal.mockClear();
  publicboardCplug.start?.();
});

afterEach(() => resetPageRowActions());

describe('the share entry on a board row', () => {
  it('is in the board row menu while the plugin is on', () => {
    host.cplugEnabled.mockReturnValue(true);
    expect(menuIds('p1')).toContain('share-link');
  });

  it('is absent while the plugin is off', () => {
    host.cplugEnabled.mockReturnValue(false);
    expect(menuIds('p1')).not.toContain('share-link');
  });

  it('is absent on a page row that is not a review board', () => {
    host.cplugEnabled.mockReturnValue(true);
    expect(menuIds('p2')).not.toContain('share-link');
  });

  it('opens the share window for the right board when selected', () => {
    host.cplugEnabled.mockReturnValue(true);
    const node = itemMenu('page', pageCtx('p1'), env)!.nodes.find((n) => n.id === 'share-link')!;
    expect(node.label).toBe('share link');
    node.run!();
    expect(host.openModal).toHaveBeenCalledWith(ShareLinkModal, { slug: '20261013-nav' });
  });
});
