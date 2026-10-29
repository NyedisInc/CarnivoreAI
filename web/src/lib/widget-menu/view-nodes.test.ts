import { describe, expect, test, vi } from 'vitest';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import { viewMenuNodes } from './view-nodes';

const say = (key: string): string => `<${key}>`;

describe('viewMenuNodes', () => {
  test('lists the views in order, the default checked when nothing is stored', () => {
    const nodes = viewMenuNodes(CORE_MANIFESTS['core.tasks']!, undefined, say, () => {});
    expect(nodes.map((node) => [node.id, node.label, node.checked])).toEqual([
      ['session', '<widget.view.session>', true],
      ['all', '<widget.view.all>', false],
    ]);
  });

  test('checks the stored view and passes a pick to the handler', () => {
    const pick = vi.fn();
    const nodes = viewMenuNodes(CORE_MANIFESTS['core.bookmarks']!, 'all', say, pick);
    expect(nodes.map((node) => node.checked)).toEqual([false, true]);
    nodes[0]!.run!();
    expect(pick).toHaveBeenCalledWith('session');
  });

  test('a widget with one face has no menu', () => {
    expect(viewMenuNodes(CORE_MANIFESTS['core.notes']!, null, say, () => {})).toEqual([]);
  });
});
