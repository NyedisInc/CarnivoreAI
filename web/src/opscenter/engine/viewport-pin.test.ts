import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { pinGridViewport, viewport } from './viewport.svelte';

describe('pinGridViewport', () => {
  it('holds the desktop content set', () => {
    viewport.wide = false;
    viewport.phone = true;
    viewport.narrow = true;
    pinGridViewport();
    expect(viewport).toEqual({ wide: true, phone: false, narrow: false });
  });

  it('is what the preview frame starts with, instead of watching its own (box-sized) window', () => {
    const source = readFileSync(new URL('../../widget-preview/main.ts', import.meta.url), 'utf8');
    expect(source).toMatch(/pinGridViewport\(\);/);
    expect(source).not.toMatch(/watchViewport\(/);
  });
});
