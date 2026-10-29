/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { t } from '../i18n/index.svelte';
import { badgePlan } from './badge';
import MessagingBadge from './MessagingBadge.svelte';

const fake = (key: string, params?: Record<string, unknown>): string => (params ? `${key}:${JSON.stringify(params)}` : key);

test('an unbound or malformed mark draws nothing', () => {
    expect(badgePlan(null, fake)).toBeNull();
    expect(badgePlan(undefined, fake)).toBeNull();
    expect(badgePlan('msg', fake)).toBeNull();
    expect(badgePlan({ directions: [], held: 3 }, fake)).toBeNull();
    expect(badgePlan({ directions: 'in', held: 0 }, fake)).toBeNull();
});

test('the direction is the union of the bindings', () => {
    expect(badgePlan({ directions: ['in'], held: 0 }, fake)).toEqual({ direction: 'in', held: 0, title: 'messaging.ui.badge.title.in', tone: 'bound' });
    expect(badgePlan({ directions: ['out'], held: 0 }, fake)?.direction).toBe('out');
    expect(badgePlan({ directions: ['out', 'in'], held: 0 }, fake)?.direction).toBe('both');
});

test('held texts switch to the question tone with the count', () => {
    const plan = badgePlan({ directions: ['in', 'out'], held: 2 }, fake);
    expect(plan?.tone).toBe('held');
    expect(plan?.held).toBe(2);
    expect(plan?.title).toContain('messaging.ui.badge.title.both');
    expect(plan?.title).toContain('messaging.ui.badge.held_title:{"count":2}');
    expect(badgePlan({ directions: ['in'], held: -1 }, fake)?.tone).toBe('bound');
});

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

function draw(mark: unknown): HTMLElement {
    const host = document.createElement('div');
    document.body.appendChild(host);
    mounted = mount(MessagingBadge, { target: host, props: { mark } });
    flushSync();
    return host;
}

function arrows(host: HTMLElement): string[] {
    return Array.from(host.querySelectorAll('[data-arrow]')).map((el) => el.getAttribute('data-arrow') ?? '');
}

test.each([
    ['in', ['in'], ['in']],
    ['out', ['out'], ['out']],
    ['both', ['in', 'out'], ['in', 'out']],
])('the %s state draws its arrows, no label, no dot', (dir, directions, expected) => {
    const host = draw({ directions, held: 0 });
    const icon = host.querySelector('[data-messaging-badge]');
    expect(icon?.getAttribute('data-messaging-badge')).toBe('bound');
    expect(icon?.getAttribute('data-messaging-direction')).toBe(dir);
    expect(arrows(host)).toEqual(expected);
    expect(host.querySelector('[data-held-dot]')).toBeNull();
    expect(icon?.textContent?.trim()).toBe('');
    expect(icon?.getAttribute('role')).toBe('img');
    expect(icon?.getAttribute('aria-label')).toBe(t(`messaging.ui.badge.title.${dir}`));
    expect(icon?.getAttribute('title')).toBe(icon?.getAttribute('aria-label'));
});

test('held draws the dot and the count in the tooltip only, no text', () => {
    const host = draw({ directions: ['in'], held: 3 });
    const icon = host.querySelector('[data-messaging-badge]');
    expect(icon?.getAttribute('data-messaging-badge')).toBe('held');
    expect(icon?.getAttribute('data-messaging-held')).toBe('3');
    expect(host.querySelector('[data-held-dot]')).not.toBeNull();
    expect(icon?.textContent?.trim()).toBe('');
    expect(icon?.getAttribute('aria-label')).toContain(t('messaging.ui.badge.held_title', { count: 3 }));
});

test('an unbound row draws nothing', () => {
    const host = draw(null);
    expect(host.querySelector('[data-messaging-badge]')).toBeNull();
});
