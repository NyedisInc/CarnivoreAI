/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('./switch-store.svelte', () => ({
  accountSwitch: { data: { auto_switch: true, threshold_percent: 95 } },
  switchActivity: { busy: null },
  setAutoSwitch: vi.fn(),
}));

import BotCycleMark from './BotCycleMark.svelte';
import AutoSwitchIcon from './AutoSwitchIcon.svelte';

let host: HTMLElement;
let instance: unknown;
afterEach(() => {
  unmount(instance as never);
  host.remove();
});
const draw = (component: typeof BotCycleMark | typeof AutoSwitchIcon, props: Record<string, unknown> = {}): void => {
  host = document.createElement('div');
  document.body.appendChild(host);
  instance = mount(component as never, { target: host, props });
  flushSync();
};

describe('BotCycleMark', () => {
  test('is one svg at the asked size, the ring behind and the robot nested inside it, centred', () => {
    draw(BotCycleMark, { size: 18 });
    const outer = [...host.children];
    expect(outer).toHaveLength(1);
    const svg = outer[0] as SVGSVGElement;
    expect(svg.tagName.toLowerCase()).toBe('svg');
    expect(svg.getAttribute('data-icon')).toBe('bot-cycle');
    expect(svg.getAttribute('width')).toBe('18');
    expect(svg.getAttribute('aria-hidden')).toBe('true');
    const ring = svg.querySelector('.bcm-ring')!;
    const bot = svg.querySelector('svg.bcm-bot')!;
    expect(ring.querySelectorAll('path').length).toBeGreaterThan(0);
    expect(bot.querySelector('rect')).not.toBeNull();
    expect(ring.compareDocumentPosition(bot) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const x = Number(bot.getAttribute('x'));
    const w = Number(bot.getAttribute('width'));
    expect(x + w / 2).toBe(12);
    expect(Number(bot.getAttribute('y')) + Number(bot.getAttribute('height')) / 2).toBe(12);
    expect(w).toBeLessThan(16);
  });

  test('the auto switch toggle draws exactly one icon, not a robot and a recycle side by side', () => {
    draw(AutoSwitchIcon);
    const button = host.querySelector('button.asw-icon')!;
    const icons = [...button.children].filter((child) => child.tagName.toLowerCase() === 'svg');
    expect(icons).toHaveLength(1);
    expect(icons[0]!.getAttribute('data-icon')).toBe('bot-cycle');
    expect(button.querySelector('[data-icon="recycle"]')).toBeNull();
    expect(button.querySelector('[data-icon="bot"]')).toBeNull();
    expect(button.getAttribute('aria-pressed')).toBe('true');
  });
});
