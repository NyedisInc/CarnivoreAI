/** @vitest-environment jsdom */
import { expect, test, vi } from 'vitest';
import { pendingFor } from './pending';
import { DEFAULT_LAYOUT } from '../model';

vi.mock('../../cells/analytics/state.svelte', () => ({ addChart: vi.fn((copy?: { viz?: string }) => ({ id: `chart-${copy?.viz ?? 'blank'}` })) }));

test('a chart kind becomes that chart as the pending slot', () => {
  const placed = pendingFor(DEFAULT_LAYOUT, 'analytics:abc', '');
  expect(placed?.id).toBe('analytics:abc');
  expect(placed!.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id))).toContain('analytics:abc');
});

test('a gallery card kind is accepted before it has a chart, and resolves to a real chart slot', async () => {
  const { PRESETS } = await import('../../viz/presets');
  const { resolveDropKind } = await import('../../layout-editor/drop-kind');
  const kind = `analytics:preset:${PRESETS[0]!.id}`;
  expect(pendingFor(DEFAULT_LAYOUT, kind, '')).not.toBeNull();
  expect(resolveDropKind(kind)).toBe(`analytics:chart-${PRESETS[0]!.viz}`);
  expect(resolveDropKind('analytics:new')).toBe('analytics:chart-blank');
  expect(resolveDropKind('notes')).toBe('notes');
});
