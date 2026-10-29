/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';

vi.mock('../../../../client/js/labels/usage-panel.js', async () => {
  const actual = await vi.importActual<typeof import('../../../../client/js/labels/usage-panel.js')>(
    '../../../../client/js/labels/usage-panel.js',
  );
  return { ...actual, usagePanelLabels: vi.fn() };
});

afterEach(() => {
  vi.clearAllMocks();
  vi.resetModules();
});

test('a malformed assembler result degrades to the unchecked shape, not a thrown error', async () => {
  const usagePanel = await import('../../../../client/js/labels/usage-panel.js');
  (usagePanel.usagePanelLabels as ReturnType<typeof vi.fn>).mockReturnValue({
    state: 'ok',
    title: 'a session',
    lines: [],
    context: {},
    windows: [],
  });
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
  const { sessionUsageLabels } = await import('./session-usage.svelte');
  const result = sessionUsageLabels({ state: 'ok' } as never, 'a session');
  expect(result.state).toBe('unchecked');
  expect(result.title).toBe('a session');
  expect(warn).toHaveBeenCalled();
  warn.mockRestore();
});

test('a well-formed "ok" result passes straight through, untouched', async () => {
  const usagePanel = await import('../../../../client/js/labels/usage-panel.js');
  const ok = {
    state: 'ok' as const,
    title: 'a session',
    rows: [{ key: 'model', label: 'model', text: 'Opus 4' }],
    context: { title: 'context', captionLabel: 'context:', segments: 20, filled: 1, scale: 1, percentText: '1%', meterText: 'context, 1 percent used', detail: '' },
    windows: [],
  };
  (usagePanel.usagePanelLabels as ReturnType<typeof vi.fn>).mockReturnValue(ok);
  const { sessionUsageLabels } = await import('./session-usage.svelte');
  expect(sessionUsageLabels({ state: 'ok' } as never, 'a session')).toEqual(ok);
});

test('an absent/unchecked result passes straight through', async () => {
  const usagePanel = await import('../../../../client/js/labels/usage-panel.js');
  const absent = { state: 'absent' as const, title: 'a session', message: 'no transcript yet' };
  (usagePanel.usagePanelLabels as ReturnType<typeof vi.fn>).mockReturnValue(absent);
  const { sessionUsageLabels } = await import('./session-usage.svelte');
  expect(sessionUsageLabels(null, 'a session')).toEqual(absent);
});
