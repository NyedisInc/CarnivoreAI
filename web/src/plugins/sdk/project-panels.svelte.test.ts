/** @vitest-environment jsdom */
import { afterEach, describe, expect, it } from 'vitest';
import { flushSync } from 'svelte';
import type { Component } from 'svelte';
import { projectPanels, registerProjectPanel, resetProjectPanels, type ProjectPanelProps } from './project-panels';

const Blank = (() => undefined) as unknown as Component<ProjectPanelProps>;

afterEach(() => resetProjectPanels());

describe('project panels', () => {
  it('lists nothing until a plugin registers', () => {
    expect(projectPanels()).toEqual([]);
  });

  it('lists enabled panels in registration order and leaves a disabled one out', () => {
    registerProjectPanel({ id: 'a.one', labelKey: 'cplug.a.one', component: Blank, enabled: () => true });
    registerProjectPanel({ id: 'b.two', labelKey: 'cplug.b.two', component: Blank, enabled: () => false });
    registerProjectPanel({ id: 'c.three', labelKey: 'cplug.c.three', component: Blank, enabled: () => true });
    expect(projectPanels().map((p) => p.id)).toEqual(['a.one', 'c.three']);
  });

  it('replaces a panel registered again under the same id (a second start is harmless)', () => {
    registerProjectPanel({ id: 'a.one', labelKey: 'cplug.a.first', component: Blank, enabled: () => true });
    registerProjectPanel({ id: 'a.one', labelKey: 'cplug.a.second', component: Blank, enabled: () => true });
    expect(projectPanels().map((p) => p.labelKey)).toEqual(['cplug.a.second']);
  });

  it('follows the switch the panel reads: off withdraws it, on brings it back', () => {
    let on = true;
    registerProjectPanel({ id: 'a.one', labelKey: 'cplug.a.one', component: Blank, enabled: () => on });
    expect(projectPanels()).toHaveLength(1);
    on = false;
    expect(projectPanels()).toHaveLength(0);
    on = true;
    expect(projectPanels()).toHaveLength(1);
  });

  it('is reactive: a registration after a reader ran is seen by that reader', () => {
    let seen = -1;
    const stop = $effect.root(() => {
      $effect(() => {
        seen = projectPanels().length;
      });
    });
    flushSync();
    expect(seen).toBe(0);
    registerProjectPanel({ id: 'late.one', labelKey: 'cplug.late.one', component: Blank, enabled: () => true });
    flushSync();
    expect(seen).toBe(1);
    stop();
  });
});
