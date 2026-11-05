/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const held = vi.hoisted(() => ({ page: { id: 'p1', key: 'k', src: '/s', title: 'T' } }));
vi.mock('../../browser/pages.svelte', () => ({ pageById: (id: string) => (id === held.page.id ? held.page : null) }));

import './all';
import { itemMenu } from '../registry';
import type { RowMenuCtx } from '../row-context';
import { registerPageRowAction, resetPageRowActions, type PageRowAction } from '../../../cplugs/sdk/page-row-actions';

const env = { close: vi.fn(), glyph: () => '' };
const ctx = { name: 'browser:p1', label: 'row', kind: 'browser', isPage: true, owned: true, status: 'unknown', pluginItems: '' } as unknown as RowMenuCtx;
const good = (plugin: string, id: string): PageRowAction => ({ plugin, id, label: () => id, enabled: () => true, targetOf: () => 'target', run: () => {} });
const ids = (): string[] => itemMenu('page', ctx, env)!.nodes.map((n) => n.id);

let errors: ReturnType<typeof vi.spyOn>;
beforeEach(() => { errors = vi.spyOn(console, 'error').mockImplementation(() => {}); });
afterEach(() => { resetPageRowActions(); errors.mockRestore(); });

describe('plugin entries on a page row menu', () => {
  it('adds the entry of an action that recognizes the page', () => {
    registerPageRowAction(good('a', 'ok-one'));
    expect(ids()).toContain('ok-one');
  });

  it('skips an action whose targetOf throws, logs its plugin, and keeps every other entry', () => {
    registerPageRowAction({ ...good('buggy', 'bad-one'), targetOf: () => { throw new Error('boom'); } });
    registerPageRowAction(good('fine', 'ok-two'));
    const out = ids();
    expect(out).toContain('ok-two');
    expect(out).not.toContain('bad-one');
    expect(out).toContain('popout');
    expect(String(errors.mock.calls[0]![0])).toContain('plugin "buggy"');
  });

  it('skips an action whose label throws', () => {
    registerPageRowAction({ ...good('buggy2', 'bad-two'), label: () => { throw new Error('boom'); } });
    registerPageRowAction(good('fine', 'ok-three'));
    expect(ids()).toContain('ok-three');
    expect(ids()).not.toContain('bad-two');
    expect(String(errors.mock.calls[0]![0])).toContain('plugin "buggy2"');
  });

  it('adds nothing for a row whose page is not held', () => {
    registerPageRowAction(good('a', 'ok-one'));
    const gone = { ...ctx, name: 'browser:nope' } as RowMenuCtx;
    expect(itemMenu('page', gone, env)!.nodes.map((n) => n.id)).not.toContain('ok-one');
  });
});
