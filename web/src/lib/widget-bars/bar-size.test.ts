/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { flushSync, mount, unmount } from 'svelte';
import { join } from 'node:path';
import { fakeActive } from '../session-rail/test-support.svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('../session-rail/test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../../opscenter/cells/registry', async () => {
  const { ScopeProbe } = await import('../session-rail/test-support.svelte');
  return { entryFor: () => ({ component: ScopeProbe }) };
});

import { BAR_SIZES, FOOT_H_PX, HANDLE_PX, barLabel, barThickness, barVars } from './bar-size';
import { outMinPx } from '../session-rail/rail-size';
import RailResizeHandle from '../session-rail/RailResizeHandle.svelte';
import { RAIL_BOTTOM_ID, RAIL_FIELD, RAIL_ID } from '../session-rail/rail-model';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import { BOTTOM_FIELD, follow, mountRails, unmountRails } from '../session-rail/rail-test-harness';

const source = (file: string): string => readFileSync(join(process.cwd(), 'src', file), 'utf8');
const rail = (id: string): HTMLElement => document.getElementById(id)!;
const key = (id: string): HTMLElement => rail(id).querySelector<HTMLElement>('[data-zone-item]')!;
const prop = (el: HTMLElement, name: string): string => el.style.getPropertyValue(name);

beforeEach(() => {
  fakeActive.id = 'ses_1';
  mountRails();
  follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.files' }, { widget: 'core.notes' }] });
  follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.notes' }] });
});
afterEach(() => {
  follow('widget_bars', null);
  unmountRails();
});

describe('the table', () => {
  test('compact is the status bar: --oc-foot-h in tokens.css equals FOOT_H_PX, and .oc-tf floors at the token', () => {
    const tokens = source('opscenter/tokens.css');
    const declared = /--oc-foot-h:\s*(\d+)px;/.exec(tokens);
    expect(declared, 'tokens.css must declare --oc-foot-h').not.toBeNull();
    expect(Number(declared![1])).toBe(FOOT_H_PX);
    expect(source('opscenter/cells/terminal-live/TerminalFoot.svelte')).toMatch(/\.oc-tf \{[^}]*box-sizing: border-box;[^}]*min-height: var\(--oc-foot-h\);/);
    expect(source('opscenter/cells/terminal-live/ShellFoot.svelte')).not.toContain('--oc-foot-h');
    expect(HANDLE_PX).toBe(10);
  });

  test('thickness per edge and size', () => {
    expect(barThickness('side', 'compact')).toBe(20);
    expect(barThickness('bottom', 'compact')).toBe(20);
    expect(barThickness('side', 'cozy')).toBe(36);
    expect(barThickness('bottom', 'cozy')).toBe(36);
    expect(barThickness('side', 'detailed')).toBe(68);
    expect(barThickness('bottom', 'detailed')).toBe(44);
    expect(BAR_SIZES.compact.side).toMatchObject({ keyW: 16, keyH: 16, icon: 12, gap: 2, pad: 2, label: 'none' });
    expect(BAR_SIZES.cozy.bottom).toMatchObject({ keyW: 28, keyH: 28, icon: 15, gap: 4, pad: 8, label: 'none' });
    expect(BAR_SIZES.detailed.side).toMatchObject({ keyW: 60, keyMinH: 46, label: 'under', labelMaxW: 56 });
    expect(BAR_SIZES.detailed.bottom).toMatchObject({ keyH: 32, keyMinW: 32, label: 'beside' });
    expect(barVars('bottom', 'compact')).toContain('--rail-h:20px;');
    expect(barVars('side', 'detailed')).toContain('--rail-w:68px;');
  });

  test('no widget title is ever broken or clipped in the right bar label (words wrap, a long word widens its box inside the bar)', () => {
    const perChar = 6;
    const { labelMaxW, bar } = BAR_SIZES.detailed.side;
    const perLine = Math.floor(labelMaxW / perChar);
    const lines = (title: string): number => {
      let count = 1;
      let used = 0;
      for (const word of title.split(' ')) {
        expect(word.length * perChar, `"${title}": the word "${word}" must fit inside the bar`).toBeLessThanOrEqual(bar);
        if (used === 0) used = word.length;
        else if (used + 1 + word.length <= perLine) used += 1 + word.length;
        else { count += 1; used = word.length; }
      }
      return count;
    };
    const titles = Object.values(CORE_MANIFESTS).map((manifest) => barLabel(manifest));
    expect(titles.length).toBeGreaterThan(5);
    for (const title of titles) expect(lines(title), title).toBeLessThanOrEqual(3);
    expect(titles.filter((title) => lines(title) > 2).sort()).toEqual(['all session tasks', 'recently closed sessions']);
    expect(source('lib/zone-shell/TabKey.svelte')).toMatch(/\.rail__key-label \{[^}]*\}[\s\S]*max-width: var\(--rail-label-maxw\);\s*min-width: min-content;/);
  });
});

describe('the rails draw the stored size', () => {
  test('absent is cozy: 36px bars, 28px keys, no label', () => {
    expect(prop(rail(RAIL_ID), '--rail-w')).toBe('36px');
    expect(prop(rail(RAIL_BOTTOM_ID), '--rail-h')).toBe('36px');
    expect(rail(RAIL_ID).dataset['barSize']).toBe('cozy');
    expect(prop(rail(RAIL_ID), '--rail-key-w')).toBe('28px');
    expect(rail(RAIL_ID).querySelector('.rail__key-label')).toBeNull();
  });

  test('compact: 20px bars, 16px keys, 12px icons', () => {
    follow('widget_bars', { v: 1, side: { size: 'compact' }, bottom: { size: 'compact' } });
    expect(prop(rail(RAIL_ID), '--rail-w')).toBe('20px');
    expect(prop(rail(RAIL_BOTTOM_ID), '--rail-h')).toBe('20px');
    expect(prop(key(RAIL_ID), '--rail-key-w') || prop(rail(RAIL_ID), '--rail-key-w')).toBe('16px');
    expect(prop(rail(RAIL_BOTTOM_ID), '--rail-key-h')).toBe('16px');
    expect(key(RAIL_ID).querySelector('svg')?.getAttribute('width')).toBe('12');
    expect(rail(RAIL_ID).querySelector('.rail__key-label')).toBeNull();
  });

  test('detailed: right 68 with 60px keys and a label under the icon, bottom 44 with 32px keys and a label beside it', () => {
    follow('widget_bars', { v: 1, side: { size: 'detailed' }, bottom: { size: 'detailed' } });
    expect(prop(rail(RAIL_ID), '--rail-w')).toBe('68px');
    expect(prop(rail(RAIL_ID), '--rail-key-w')).toBe('60px');
    expect(prop(rail(RAIL_ID), '--rail-key-minh')).toBe('46px');
    expect(key(RAIL_ID).dataset['label']).toBe('under');
    expect(key(RAIL_ID).querySelector('.rail__key-label')?.textContent).toBe(barLabel(CORE_MANIFESTS['core.files']!));
    expect(key(RAIL_ID).querySelector('.rail__key-label')?.getAttribute('aria-hidden')).toBe('true');
    expect(prop(rail(RAIL_BOTTOM_ID), '--rail-h')).toBe('44px');
    expect(prop(rail(RAIL_BOTTOM_ID), '--rail-key-h')).toBe('32px');
    expect(key(RAIL_BOTTOM_ID).dataset['label']).toBe('beside');
    expect(key(RAIL_BOTTOM_ID).getAttribute('aria-label')).toBe(barLabel(CORE_MANIFESTS['core.notes']!));
  });

  test('the bottom resize handle announces the bar itself as its minimum at every size', () => {
    for (const [size, min] of [['compact', '20'], ['cozy', '36'], ['detailed', '44']] as const) {
      follow('widget_bars', { v: 1, bottom: { size } });
      const host = document.createElement('div');
      document.body.appendChild(host);
      const instance = mount(RailResizeHandle, { target: host, props: { edge: 'bottom', label: 'resize' } });
      flushSync();
      expect(host.querySelector('[data-rail-grip="bottom"]')!.getAttribute('aria-valuemin'), size).toBe(min);
      unmount(instance);
      host.remove();
    }
  });

  test('a compact key shows the alert count as a 6px dot, not a bubble over its 12px icon', () => {
    expect(source('lib/zone-shell/ZoneBadge.svelte')).toMatch(/:global\(\[data-bar-size='compact'\]\) \.zone-badge \{[^}]*width: 6px;[^}]*height: 6px;/);
  });

  test('the bottom slide-out floor is the bar itself at every size', () => {
    expect(outMinPx('bottom', 'compact')).toBe(20);
    expect(outMinPx('bottom', 'cozy')).toBe(36);
    expect(outMinPx('bottom', 'detailed')).toBe(44);
    expect(outMinPx('side', 'detailed')).toBe(44);
  });
});
