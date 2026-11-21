/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';
import TaskManagerTagged from './TaskManagerTagged.svelte';
import { TAGGED_OPEN } from './task-manager-tagged-open';
import type { HuddleItem } from './huddle-model';

const item = (extra: Partial<HuddleItem>): HuddleItem => ({ id: 5, list: '7', tagged_session_key: 'uuid-9', ...extra }) as HuddleItem;
let handle: Record<string, unknown> | null = null;
afterEach(() => { if (handle) void unmount(handle); handle = null; document.body.innerHTML = ''; });

function draw(it: HuddleItem, opener?: (uuid: string) => void): void {
  const context = new Map<unknown, unknown>(opener ? [[TAGGED_OPEN, opener]] : []);
  handle = mount(TaskManagerTagged, { target: document.body, props: { item: it }, context });
}

describe('TaskManagerTagged opener', () => {
  test('live agent with an opener: a button, and a click passes the tagged session key', () => {
    const open = vi.fn();
    draw(item({ tagged_by: 'api agent' }), open);
    const button = document.querySelector<HTMLButtonElement>('button[data-task-manager-tagged-open]');
    expect(button?.textContent).toBe('@api agent');
    button?.click();
    expect(open).toHaveBeenCalledWith('uuid-9');
  });

  test('agent not running: a plain label, no button', () => {
    draw(item({ tagged_by: null }), vi.fn());
    expect(document.querySelector('button')).toBeNull();
    expect(document.querySelector('p[data-task-manager-tagged]')?.textContent).toBe('@agent not running');
  });

  test('no opener provided (the original Task Manager): a plain label even when live', () => {
    draw(item({ tagged_by: 'api agent' }));
    expect(document.querySelector('button')).toBeNull();
    expect(document.querySelector('p[data-task-manager-tagged]')?.textContent).toBe('@api agent');
  });
});
