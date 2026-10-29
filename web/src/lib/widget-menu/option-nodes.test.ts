import { describe, expect, test, vi } from 'vitest';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import { copyOptionNodes, hasOptions, lookNodes, railTip, settingNodes, type OptionNodesInput } from './option-nodes';

const say = (key: string): string => `<${key}>`;

function input(id: string, extra: Partial<OptionNodesInput> = {}): OptionNodesInput {
  const manifest = CORE_MANIFESTS[id]!;
  return { manifest, cell: manifest, view: null, values: undefined, translate: say, pickView: () => {}, write: () => {}, openForm: () => {}, ...extra };
}

describe('settingNodes (edit mode)', () => {
  test('files: a tick for show global folder and a branch of radios for the top folder', () => {
    const write = vi.fn();
    const groups = settingNodes(input('core.files', { write }));
    const nodes = groups.flat();
    expect(nodes.map((n) => n.id)).toEqual(['showGlobalFolder', 'topFolder']);
    expect(nodes[0]!.checked).toBe(true);
    expect(nodes[0]!.toggle).toBe(true);
    nodes[0]!.run!();
    expect(write).toHaveBeenCalledWith('showGlobalFolder', false);
    expect(nodes[1]!.children!.map((c) => [c.id, c.checked])).toEqual([['topFolder:global', true], ['topFolder:project', false]]);
    nodes[1]!.children![1]!.run!();
    expect(write).toHaveBeenCalledWith('topFolder', 'project');
  });

  test('a stored value is what is checked', () => {
    const nodes = settingNodes(input('core.files', { values: { showGlobalFolder: false, topFolder: 'project' } })).flat();
    expect(nodes[0]!.checked).toBe(false);
    expect(nodes[1]!.children!.map((c) => c.checked)).toEqual([false, true]);
  });

  test('a number field adds one settings... item that opens the form', () => {
    const openForm = vi.fn();
    const last = settingNodes(input('core.bookmarks', { openForm })).flat().pop()!;
    expect(last.id).toBe('settings');
    last.run!();
    expect(openForm).toHaveBeenCalled();
  });

  test('a widget with no settings has none', () => {
    expect(settingNodes(input('core.crosstalk'))).toEqual([]);
  });
});

describe('lookNodes (edit mode)', () => {
  test('bookmarks: one radio per view; a widget with one face has none', () => {
    expect(lookNodes(input('core.bookmarks')).map((n) => n.id)).toEqual(['session', 'all']);
    expect(lookNodes(input('core.files'))).toEqual([]);
  });

  test('the options rule: views or settings in edit layout, per-copy options any time', () => {
    const files = CORE_MANIFESTS['core.files']!;
    const tasks = CORE_MANIFESTS['core.tasks']!;
    const questions = CORE_MANIFESTS['core.questions']!;
    expect(hasOptions(CORE_MANIFESTS['core.crosstalk']!, CORE_MANIFESTS['core.crosstalk']!, true)).toBe(false);
    expect(hasOptions(files, files, true)).toBe(true);
    expect(hasOptions(files, files, false)).toBe(false);
    expect(hasOptions(tasks, tasks, true)).toBe(true);
    expect(hasOptions(questions, questions, false)).toBe(true);
  });
});

describe('railTip', () => {
  test('every key has a menu, so the hint is always the last line', () => {
    const tasks = CORE_MANIFESTS['core.tasks']!;
    expect(railTip(tasks, 'all', say).split('\n')).toEqual([`<${tasks.titleKey}>`, '<widget.view.all>', '<session_rail.tip.options>']);
    const crosstalk = CORE_MANIFESTS['core.crosstalk']!;
    expect(railTip(crosstalk, null, say).split('\n')).toHaveLength(3);
  });
});

describe('copyOptionNodes', () => {
  const schema = {
    fields: {
      kind_all: { kind: 'boolean' as const, labelKey: 'a', default: true },
      kind_huddle: { kind: 'boolean' as const, labelKey: 'h', default: true, disabledWhen: 'kind_all' },
    },
  };

  test('a tick per switch, on unless the copy turned it off; a click writes the opposite for this copy only and the tick keeps the menu open', () => {
    const write = vi.fn();
    const checks = copyOptionNodes(input('core.questions', { placement: { schema, values: { kind_all: false, kind_huddle: false }, write } }));
    expect(checks.map((n) => [n.id, n.checked])).toEqual([['option:kind_all', false], ['option:kind_huddle', false]]);
    expect(checks.map((n) => [n.toggle, n.keepOpen])).toEqual([[true, true], [true, true]]);
    checks[0]!.run!();
    expect(write).toHaveBeenCalledWith('kind_all', true);
  });

  test('a tick its master has taken over (all on) is inert; it frees up when the master is off', () => {
    const on = copyOptionNodes(input('core.questions', { placement: { schema, values: {}, write: () => {} } }));
    expect(on.find((n) => n.id === 'option:kind_huddle')!.blocked).toBeTruthy();
    expect(on.find((n) => n.id === 'option:kind_all')!.blocked).toBeUndefined();
    const off = copyOptionNodes(input('core.questions', { placement: { schema, values: { kind_all: false }, write: () => {} } }));
    expect(off.find((n) => n.id === 'option:kind_huddle')!.blocked).toBeUndefined();
  });

  test('a widget that names a heading gets one branch of that name; ticks inside it keep the menu open', () => {
    const branch = copyOptionNodes(input('core.task-list', { placement: { schema, values: {}, write: () => {} } }), 'show in list');
    expect(branch).toHaveLength(1);
    expect(branch[0]!.label).toBe('show in list');
    expect(branch[0]!.children!.every((c) => c.keepOpen)).toBe(true);
  });

  test('a widget whose copies carry no options offers none', () => {
    expect(copyOptionNodes(input('core.files'))).toEqual([]);
  });
});
