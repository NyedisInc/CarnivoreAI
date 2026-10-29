/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const api = vi.hoisted(() => ({
  createChart: vi.fn(async (chart: { id: string }) => ({ ...chart, revision: 1 })),
  updateChart: vi.fn(async (chart: { revision: number }) => ({ ...chart, revision: chart.revision + 1 })),
}));
vi.mock('../cells/analytics/api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  createChart: api.createChart,
  updateChart: api.updateChart,
}));

import { homeLayout } from '../engine/layout.svelte';
import { analytics } from '../cells/analytics/state.svelte';
import { addAnalyticsWidget, changeAnalyticsConfig, editorSeams, enterLayoutEditor, finishLayoutEditor, layoutEditor, removeWidget } from './editor.svelte';
import LayoutEditorHost from './LayoutEditorHost.svelte';

const real = { ...editorSeams };
const placed = (): string[] => homeLayout.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));

beforeEach(() => {
  editorSeams.page = () => 'home';
  editorSeams.store = (p) => (p === 'home' ? homeLayout : null);
  editorSeams.wide = () => true;
  homeLayout.resetAll();
  analytics.charts = {};
  api.createChart.mockClear();
  api.updateChart.mockClear();
});

afterEach(() => {
  finishLayoutEditor();
  Object.assign(editorSeams, real);
  analytics.charts = {};
});

describe('Escape', () => {
  test('leaves edit mode and keeps every change, the same as Done', async () => {
    const host = mount(LayoutEditorHost, { target: document.body });
    enterLayoutEditor();
    flushSync();
    await removeWidget('stat-running');
    expect(placed()).not.toContain('stat-running');
    const esc = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    window.dispatchEvent(esc);
    flushSync();
    expect(esc.defaultPrevented).toBe(true);
    expect(layoutEditor.active).toBe(false);
    expect(placed()).not.toContain('stat-running');
    unmount(host);
  });

  test('yields to an open dialog, which answers its own Escape', () => {
    const host = mount(LayoutEditorHost, { target: document.body });
    enterLayoutEditor();
    flushSync();
    const dialog = document.createElement('div');
    dialog.setAttribute('role', 'dialog');
    document.body.append(dialog);
    dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    expect(layoutEditor.active).toBe(true);
    dialog.remove();
    unmount(host);
  });
});

describe('a chart change with no Done', () => {
  test('a new chart is created on the server at once', () => {
    enterLayoutEditor();
    expect(addAnalyticsWidget()).toBe(true);
    expect(api.createChart).toHaveBeenCalledTimes(1);
    expect(layoutEditor.active).toBe(true);
  });

  test('a config change is written at once, not held until Done', async () => {
    enterLayoutEditor();
    addAnalyticsWidget();
    const [id] = Object.keys(analytics.charts);
    await vi.waitFor(() => expect(analytics.charts[id!]!.revision).toBe(1));
    changeAnalyticsConfig({ ...analytics.charts[id!]!, title: 'renamed' });
    await vi.waitFor(() => expect(api.updateChart).toHaveBeenCalledTimes(1));
    expect(api.updateChart.mock.calls[0]![0]).toMatchObject({ id, title: 'renamed' });
    expect(layoutEditor.active).toBe(true);
  });

  test('a change made while the create is still in flight waits for it, then writes', async () => {
    enterLayoutEditor();
    addAnalyticsWidget();
    const [id] = Object.keys(analytics.charts);
    changeAnalyticsConfig({ ...analytics.charts[id!]!, title: 'quick' });
    await vi.waitFor(() => expect(api.updateChart).toHaveBeenCalledTimes(1));
    expect(api.updateChart.mock.calls[0]![0]).toMatchObject({ id, title: 'quick', revision: 1 });
  });
});
