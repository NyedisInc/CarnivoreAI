/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import TaskManagerBubble from './TaskManagerBubble.svelte';
import { BUBBLES, BUBBLE_KINDS, bubbleKindOf, threadTone } from './task-manager-bubbles';

let app: ReturnType<typeof mount> | null = null;
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; });

async function draw(props: Record<string, unknown>): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(TaskManagerBubble as never, { target: host, props });
  await tick();
  flushSync();
  return host.firstElementChild as HTMLElement;
}

describe('the registry', () => {
  test('every kind declares a token, an icon and slots, and the registry lists them all', () => {
    expect(BUBBLE_KINDS.length).toBeGreaterThanOrEqual(7);
    for (const kind of BUBBLE_KINDS) {
      const v = BUBBLES[kind];
      expect(v.tone.color).toMatch(/^var\(--oc-/);
      expect(v.icon.length).toBeGreaterThan(0);
      expect(Array.isArray(v.slots)).toBe(true);
    }
  });

  test('a message maps to a kind and its token', () => {
    expect(bubbleKindOf({ author: 'joe', kind: 'reply' })).toBe('owner');
    expect(bubbleKindOf({ author: 'claude', kind: 'attention' })).toBe('look');
    expect(bubbleKindOf({ author: 'claude', kind: 'reply' })).toBe('claude');
    expect(threadTone({ author: 'claude', kind: 'info' })).toBe(BUBBLES.info.tone.color);
  });
});

describe.each(BUBBLE_KINDS)('kind %s through the base', (kind) => {
  test('thread layout: the shared frame, the header row and the markdown body', async () => {
    const el = await draw({ kind, layout: 'thread', author: kind === 'owner' ? 'joe' : 'claude', time: 1700000000, text: 'a **bold** word' });
    expect(el.classList.contains('hb')).toBe(true);
    expect(el.classList.contains('hb--thread')).toBe(true);
    expect(el.classList.contains(`hb--${kind}`)).toBe(true);
    expect(el.dataset.hb).toBe(kind);
    expect(el.style.getPropertyValue('--_post')).toBe(BUBBLES[kind].tone.color);
    expect([...el.children].map((c) => c.className.split(' ')[0])).toEqual(['hb-head', 'hb-body']);
    expect(el.querySelector('.hb-who')).not.toBeNull();
    expect(el.querySelector('time.hb-time')).not.toBeNull();
    expect(el.querySelector('.hb-kind') !== null).toBe(BUBBLES[kind].labelKey !== null);
    expect(el.querySelector('.hb-body strong')?.textContent).toBe('bold');
    expect(el.textContent).not.toContain('*');
  });

  test('row layout: a mark column, then the main column; a cut keeps its styling and shows no marker', async () => {
    const el = await draw({ kind, layout: 'row', header: true, text: `**${'word '.repeat(80)}**`, limit: 40, more: true });
    expect(el.classList.contains('hb--row')).toBe(true);
    expect(el.querySelector(':scope > .hb-mark')).not.toBeNull();
    expect(el.querySelector(':scope > .hb-main > .hb-head')).not.toBeNull();
    expect(el.querySelector('.hb-body strong')).not.toBeNull();
    expect(el.textContent).not.toContain('*');
  });
});

describe('waiting', () => {
  test('a waiting bubble takes the full-token edge class', async () => {
    const el = await draw({ kind: 'question', waiting: true, text: 'x' });
    expect(el.classList.contains('hb--waiting')).toBe(true);
  });
});
