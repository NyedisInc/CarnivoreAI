import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';
import { LETTERS } from '../../../../client/js/menu-keys.js';
import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { barMenuNodes, areaMenuNodes } from '../widget-menu/bar-menu';
import { buildWidgetMenu, type WidgetMenuCtx } from '../widget-menu/model';
import { railMenuNodes } from '../widget-menu/rail-menu';
import { assignMenuKeys, registeredKey } from './menu-keys';

const leaf = (id: string, extra: Partial<MenuNode> = {}): MenuNode => ({ id, label: id, run: () => {}, ...extra });
const noop = (): void => {};

function builtMenus(): Record<string, MenuNode[]> {
  const out: Record<string, MenuNode[]> = {};
  for (const editing of [false, true]) {
    const ctx: WidgetMenuCtx = {
      editing, onClose: noop,
      content: [[leaf('sort:name'), leaf('sort:recent'), leaf('sort:last_used'), leaf('sort:activity'), leaf('sort:project')], [leaf('zoom'), leaf('search')]],
      settings: [[leaf('settings')]],
      popOut: noop, focusMain: noop, header: { shown: true, toggle: noop },
      arrange: (['extendRow', 'pullBackRow', 'moveUp', 'moveDown', 'moveToDrawer'] as const).map((item) => ({ item, run: noop })),
      editLayout: noop, close: { run: noop },
    };
    out[`widget ${editing ? 'edit' : 'normal'}`] = buildWidgetMenu(ctx);
    out[`widget ${editing ? 'edit' : 'normal'} on a bar`] = buildWidgetMenu({ ...ctx, arrange: [{ item: 'moveToBar', run: noop }, { item: 'moveUp', run: noop }, { item: 'moveDown', run: noop }] });
    out[`bar ${editing}`] = barMenuNodes({ size: 'cozy', pinned: true, editing, setSize: noop, togglePin: noop, toggleEdit: noop, onClose: noop });
    out[`area ${editing}`] = areaMenuNodes({ state: 'glance', editing, setState: noop, toggleEdit: noop, onClose: noop });
    for (const mini of [false, true]) {
      out[`rail ${editing} ${mini}`] = railMenuNodes({ pin: mini ? null : { pinned: false, toggle: noop }, openDrawer: mini ? noop : null, editing, toggleEdit: noop, close: { label: 'close tab', run: noop }, onClose: noop });
    }
  }
  return out;
}

const COMPONENT_MENUS: Record<string, { files: string[]; ids: string[] }> = {
  'view menu': {
    files: ['../session-list/view-choices.ts'],
    ids: ['density-compact', 'density-cozy', 'density-detailed', 'show-leaders', 'show-archived', 'show-stats', 'show-open', 'show-sleeping'],
  },
  'new (+) menu': { files: ['../drawer-tabs/NewSessionButton.svelte'], ids: ['agent', 'terminal', 'browser', 'project', 'group'] },
  'account menu': {
    files: ['../drawer-hud/AccountMenu.svelte'],
    ids: ['account_page', 'layout', 'master_all', 'signout', 'logout'],
  },
  'row menu plus its plugins': {
    files: ['../item-menu/menus/row-items.ts', '../../cplugs/huddle/session-roles-action.ts', '../../cplugs/unread/index.ts', '../../cplugs/share/index.ts'],
    ids: ['rename', 'add-to', 'pin', 'mark-unread', 'huddle-project-lead', 'share-read-only', 'send-to', 'close', 'fork', 'sleep'],
  },
};

function lettersOf(ids: { id: string; label: string; skip?: boolean }[]): string[] {
  return assignMenuKeys(ids);
}

describe('the registry table', () => {
  test('an id is listed under exactly one meaning, and every letter is one character', () => {
    const seen = new Map<string, string>();
    for (const entry of LETTERS) {
      expect(entry.letter, entry.meaning).toHaveLength(1);
      for (const id of entry.ids) {
        expect(seen.get(id), `${id} listed under two meanings`).toBeUndefined();
        seen.set(id, entry.letter);
        expect(registeredKey(id), id).toBe(entry.letter);
      }
    }
    expect(seen.size, 'population').toBeGreaterThan(80);
  });

  test('a letter carried by two meanings states why no menu draws both', () => {
    const byLetter = new Map<string, typeof LETTERS[number][]>();
    for (const entry of LETTERS) byLetter.set(entry.letter, [...(byLetter.get(entry.letter) ?? []), entry]);
    for (const [letter, entries] of byLetter) {
      if (entries.length > 1) for (const e of entries) expect(e.shares, `${letter}: ${e.meaning}`).toBeTruthy();
    }
  });

  test('the destructive letters mean only their verbs', () => {
    const meaningOf = (letter: string): string[] => LETTERS.filter((e) => e.letter === letter).map((e) => e.meaning);
    expect(meaningOf('d').join()).toMatch(/delete/);
    for (const letter of ['d', 'k', 'v']) {
      for (const entry of LETTERS.filter((e) => e.letter === letter)) {
        expect(entry.meaning + entry.ids.join(), `${letter} stays a destructive verb`).toMatch(/delete|close|kill|remove|archive/);
      }
    }
  });
});

describe('the real menus draw the registry', () => {
  test('every built menu: each registered id draws its registry letter and no level repeats a letter', () => {
    const menus = builtMenus();
    expect(Object.keys(menus).length, 'population').toBeGreaterThan(10);
    for (const [name, nodes] of Object.entries(menus)) {
      expect(nodes.length, `${name}: has items`).toBeGreaterThan(1);
      const keys = lettersOf(nodes.map((n) => ({ id: n.id, label: n.label, skip: !!n.blocked || !!n.swatches })));
      nodes.forEach((n, at) => {
        const want = registeredKey(n.id);
        if (want && !n.blocked) expect(keys[at], `${name}: ${n.id}`).toBe(want);
      });
      const drawn = keys.filter(Boolean);
      expect(new Set(drawn).size, `${name}: ${drawn.join('')}`).toBe(drawn.length);
    }
  });

  test('every component menu: its ids are registered, on distinct letters, and really are in its source', () => {
    const templated: Record<string, string> = {
      'density-compact': 'density-${mode}', 'density-cozy': 'density-${mode}', 'density-detailed': 'density-${mode}',
      'show-open': '`show-${id}`', 'show-sleeping': '`show-${id}`',
      agent: 'newSessionKinds()', terminal: 'newSessionKinds()', browser: 'newSessionKinds()',
    };
    for (const [name, { files, ids }] of Object.entries(COMPONENT_MENUS)) {
      const src = files.map((f) => readFileSync(new URL(f, import.meta.url), 'utf8')).join('\n');
      const letters = ids.map((id) => {
        const key = registeredKey(id);
        expect(key, `${name}: ${id} is registered`).not.toBeNull();
        expect(src.includes(`'${id}'`) || src.includes(templated[id] ?? '\0'), `${name}: ${id} is in its source`).toBe(true);
        return key;
      });
      expect(new Set(letters).size, `${name}: ${letters.join('')}`).toBe(letters.length);
    }
  });
});

function docRows(): string[][] {
  const doc = readFileSync(new URL('../../../../docs/widget-system.md', import.meta.url), 'utf8');
  const at = doc.indexOf('### 25.2');
  expect(at, 'docs/widget-system.md has section 25.2').toBeGreaterThan(0);
  const rest = doc.slice(at).split('\n').slice(1);
  const rows: string[][] = [];
  for (const line of rest) {
    if (/^#{1,3} /.test(line)) break;
    if (!line.startsWith('| `')) continue;
    rows.push(line.split(' | ').map((cell) => cell.replace(/^\| /, '').replace(/ \|$/, '').trim()));
  }
  return rows;
}

export function expectedRows(): string[] {
  return LETTERS.map((e) => `| \`${e.letter}\` | ${e.meaning} | ${e.ids.length ? e.ids.map((id) => `\`${id}\``).join(' ') : '(any id by its verb)'} |`);
}

test('docs/widget-system.md 25.2 carries the registry, row for row', () => {
  const want = expectedRows();
  const got = docRows().map((cells) => `| ${cells.join(' | ')} |`);
  expect(got, `paste this table into 25.2:\n${want.join('\n')}`).toEqual(want);
});
