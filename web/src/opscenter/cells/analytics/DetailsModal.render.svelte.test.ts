/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../../api/auth.svelte', () => ({ authFetch: vi.fn() }));
vi.mock('../../api/events.svelte', () => ({ subscribe: () => () => undefined }));

import DetailsModal from './DetailsModal.svelte';
import { openModal } from '../../../lib/modal';
import type { Annotation, ChartConfig, DetailsView } from './types';

const CONFIG: ChartConfig = {
  id: 'c1', revision: 1, title: 'token history', enabled: true, series: [{ metric: 'total_tokens' }], filters: {},
  range: { mode: 'global' }, display: { type: 'line' },
};
const MARKER: Annotation = { id: 'm1', revision: 1, occurred_at: 1_790_000_000, kind: 'rule', label: 'CLAUDE.md: change observed', basis: 'observed' };

function card(): { view: DetailsView; state: { open: boolean } } {
  const state = $state({ open: true });
  const view: DetailsView = {
    id: 'c1', title: 'tokens used', period: 'past 24 hours', config: CONFIG, results: [], markers: [MARKER],
    activeSeries: CONFIG.series, units: ['tokens'], thresholds: [],
    range: { from: '2026-09-29T00:00:00Z', to: '2026-09-30T00:00:00Z' }, baseRange: { from: '2026-09-29T00:00:00Z', to: '2026-09-30T00:00:00Z' },
    quotaWindow: undefined, selectedMarker: null, comparisonHours: 24,
    get open() { return state.open; },
    selectMarker: vi.fn(), setComparisonHours: vi.fn(), setMarkers: vi.fn(),
  };
  return { view, state };
}

const overlay = (): HTMLElement | null => document.querySelector<HTMLElement>('.modal-overlay.analytics-modal');

afterEach(() => { document.body.innerHTML = ''; });

describe('analytics details dialog', () => {
  test('wears the shared chassis and title strip, naming the card and its period', () => {
    const { view } = card();
    void openModal(DetailsModal, { view });
    flushSync();
    const root = overlay();
    expect(root, 'the dialog is not on the shared chassis').not.toBeNull();
    expect(root!.classList.contains('text-prompt-modal')).toBe(true);
    expect(root!.getAttribute('role')).toBe('dialog');
    expect(root!.parentElement!.parentElement).toBe(document.body);
    const head = root!.querySelector('.text-prompt-modal__head')!;
    expect(head.querySelector('.text-prompt-modal__verb')!.textContent).toContain('details');
    expect(head.querySelector('.analytics-modal__title')!.textContent).toBe('tokens used');
    expect(head.querySelector('.analytics-modal__period')!.textContent).toBe('past 24 hours');
    expect(document.querySelectorAll('dialog').length, 'a second, native dialog frame came back').toBe(0);
    expect(root!.querySelector('.analytics-modal__event-label')!.textContent).toBe('CLAUDE.md: change observed · observed');
  });

  test('the close box, the footer close and Escape each close it', async () => {
    for (const way of ['head', 'footer', 'escape'] as const) {
      const { view } = card();
      const answer = openModal(DetailsModal, { view });
      flushSync();
      const root = overlay()!;
      if (way === 'head') root.querySelector<HTMLButtonElement>('.text-prompt-modal__head .modal-close')!.click();
      if (way === 'footer') root.querySelector<HTMLButtonElement>('.modal-footer .modal-btn-secondary')!.click();
      if (way === 'escape') root.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      await expect(answer).resolves.toBeNull();
      expect(overlay(), `${way} left the dialog open`).toBeNull();
    }
  });

  test('closes itself when its card goes away', async () => {
    const { view, state } = card();
    const answer = openModal(DetailsModal, { view });
    flushSync();
    expect(overlay()).not.toBeNull();
    state.open = false;
    flushSync();
    await expect(answer).resolves.toBeNull();
    expect(overlay()).toBeNull();
  });

  test('the body is the one scrolling box: nothing inside scrolls on its own', () => {
    const src = fs.readFileSync(path.join(process.cwd(), 'src/opscenter/cells/analytics/DetailsModal.svelte'), 'utf8');
    const css = src.slice(src.indexOf('<style>')).replace(/\/\*[\s\S]*?\*\//g, '');
    const scrollers = [...css.matchAll(/([^{}]+)\{[^}]*overflow(?:-[xy])?:\s*(?:auto|scroll)/g)].map((m) => m[1]!.trim());
    expect(scrollers).toEqual([':global(.text-prompt-modal.analytics-modal .modal-body)']);
    const controls = fs.readFileSync(path.join(process.cwd(), 'src/opscenter/cells/analytics/Controls.svelte'), 'utf8');
    expect(controls, 'the account filters grew a scroller of their own').not.toMatch(/overflow(?:-[xy])?:\s*(?:auto|scroll)/);
  });
});
