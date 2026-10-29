/** @vitest-environment jsdom */
import { expect, test } from 'vitest';
import { alertCountSource } from './alert-counts';
import { openTasks } from './alert-count-sources.svelte';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import type { SessionTasks } from '../../opscenter/api/session-tasks.svelte';

test('open tasks are pending plus in progress, not completed', () => {
  expect(openTasks({ counts: { pending: 2, in_progress: 1, completed: 9 } } as SessionTasks)).toBe(3);
});

test('tasks, tasks-all and automations-all publish a source and know nothing before the first read', () => {
  for (const id of ['core.tasks', 'core.tasks-all', 'core.automations-all']) {
    const source = alertCountSource(id);
    expect(source, id).toBeDefined();
    expect(source?.read(null), id).toBeNull();
  }
});

test('the three manifests declare showBadge, on by default', () => {
  const manifests = CORE_MANIFESTS as Record<string, { settings?: { fields: Record<string, { default: unknown }> } }>;
  for (const id of ['core.tasks', 'core.tasks-all', 'core.automations-all']) {
    expect(manifests[id]?.settings?.fields['showBadge']?.default, id).toBe(true);
  }
});
