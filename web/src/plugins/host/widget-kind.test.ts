import { expect, test } from 'vitest';
import taskManagerManifest from '../../../../src/plugins/taskmanager/carnivore.toml';
import type { CplugManifest } from '../sdk';
import { popoutWidgetFor } from './popout-widgets';
import { widgetKind } from './widget-kind';

const manifest = taskManagerManifest as unknown as CplugManifest;

test('the renamed Task Manager keeps the huddle.chat widget id', () => {
  expect(manifest.renamed_from).toBe('huddle');
  expect(widgetKind({ id: 'taskmanager', manifest }, 'huddle.chat')).toBe('huddle.chat');
});

test('a plugin that does not keep its widgets, or was never renamed, gets <id>.<name>', () => {
  const noKeep = { ...manifest, renamed_from_keeps: ['strings'] };
  expect(widgetKind({ id: 'taskmanager', manifest: noKeep }, 'chat')).toBe('taskmanager.chat');
  expect(widgetKind({ id: 'flow', manifest: { ...manifest, renamed_from: undefined } }, 'board')).toBe('flow.board');
});

test('a stored huddle.chat slot still resolves to the Task Manager chat widget in the pop-out', () => {
  expect(popoutWidgetFor('huddle.chat:agent:5')?.widget.name).toBe('huddle.chat');
  expect(popoutWidgetFor('taskmanager.huddle.chat:agent:5')).toBeNull();
});
