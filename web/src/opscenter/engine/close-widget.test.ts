/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';

import { closeOffered, closeWidget } from './close-widget';
import { terminalLayout } from './layout.svelte';
import { PRIMARY_SLOT } from './model';
import type { SlotId } from './types';

afterEach(() => {
  terminalLayout.resetAll();
  localStorage.clear();
});

describe('closeOffered', () => {
  test('never offers the x on the terminal page own pane, even on a closable record', () => {
    expect(closeOffered({ closable: true }, PRIMARY_SLOT as SlotId)).toBe(false);
  });

  test('offers the x on any other copy of a closable record', () => {
    expect(closeOffered({ closable: true }, 'notes' as SlotId)).toBe(true);
  });
});

describe('closeWidget', () => {
  test('leaves the terminal page own pane where it is', () => {
    const before = terminalLayout.state.layout;
    closeWidget(terminalLayout, PRIMARY_SLOT as SlotId, { editing: false, from: null });
    expect(terminalLayout.state.layout).toBe(before);
  });

  test('a closed copy takes its header tick with it, so the next copy has its header on', async () => {
    const slot = 'browser:probe' as SlotId;
    expect(terminalLayout.add('browser', 'probe')).toBeNull();
    terminalLayout.setHeaderShown(slot, false);
    expect(terminalLayout.isHeaderShown(slot)).toBe(false);

    closeWidget(terminalLayout, slot, { editing: false, from: null });
    await Promise.resolve();
    expect(terminalLayout.state.layout.headerOff).toBeUndefined();

    expect(terminalLayout.add('browser', 'probe')).toBeNull();
    expect(terminalLayout.isHeaderShown(slot)).toBe(true);
  });
});
