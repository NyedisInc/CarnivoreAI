/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import Character from './characters/Character.svelte';
import LimitGauge from '../../../opscenter/ui/LimitGauge.svelte';

const here = path.dirname(fileURLToPath(import.meta.url));

describe('UIFIX-E', () => {
  test('the finished_unread glow is inside the squashed body layer, still or moving', () => {
    for (const still of [true, false]) {
      const target = document.createElement('div');
      document.body.append(target);
      const app = mount(Character, { target, props: { state: 'finished_unread', size: 40, still } });
      flushSync();
      const gw = target.querySelector('.pk-gw');
      expect(gw?.parentElement?.classList.contains('pk-sz')).toBe(true);
      unmount(app);
    }
  });

  test('a 2px context bar drops the frame ring and uses the quiet theme-border track; a tall one keeps the ring', () => {
    const thin = document.createElement('div');
    const tall = document.createElement('div');
    document.body.append(thin, tall);
    const a = mount(LimitGauge, { target: thin, props: { variant: 'fill', pct: null, scale: null, height: 2, meterText: 'x' } });
    const b = mount(LimitGauge, { target: tall, props: { variant: 'fill', pct: 10, scale: 1, height: 7, meterText: 'x' } });
    flushSync();
    expect(thin.querySelector('.oc-gauge')!.getAttribute('style')).toContain('--oc-gauge-ring: none');
    expect(tall.querySelector('.oc-gauge')!.getAttribute('style')).not.toContain('--oc-gauge-ring');
    unmount(a);
    unmount(b);
  });

  test('the seat buttons use the shared small oc-btn family, no component button rules', () => {
    for (const f of ['SwarmPanel.svelte']) {
      const src = fs.readFileSync(path.join(here, f), 'utf8');
      expect(src).toContain('oc-btn oc-btn--sm');
      expect(src).not.toMatch(/modal-btn/);
      expect(src.slice(src.indexOf('<style>'))).not.toMatch(/\n {2}\.pk[pg]-[a-z-]+ button/);
    }
  });
});
