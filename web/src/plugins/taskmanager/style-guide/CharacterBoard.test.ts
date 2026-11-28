/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { contrastIndex, seriesIndex } from '../swarm/characters/look';
import CharacterBoard from './CharacterBoard.svelte';

let app: ReturnType<typeof mount> | null = null;
let target: HTMLElement;

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(Math, 'random').mockReturnValue(0);
  target = document.createElement('div');
  document.body.append(target);
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  vi.restoreAllMocks();
  vi.useRealTimers();
  document.body.innerHTML = '';
});

function draw(part: 'theme' | 'pixel' = 'theme'): void {
  app = mount(CharacterBoard, { target, props: { part } });
  flushSync();
}

const squares = (st: string): Element[] => [...target.querySelectorAll(`[data-row="${st}"] .pk-sq`)];

function wait(ms: number): void {
  vi.advanceTimersByTime(ms);
  flushSync();
}

describe('the Swarm characters board', () => {
  test('every state has a row: sizes 28, 40 and 64 plus the still column; the pixel board is 40 only; a state shows its kind', () => {
    draw();
    expect(target.querySelectorAll('[data-row]')).toHaveLength(20);
    expect(squares('idle').map((e) => (e as HTMLElement).style.getPropertyValue('--s'))).toEqual(['28px', '40px', '64px', '40px']);
    expect(squares('idle').map((e) => e.hasAttribute('data-still'))).toEqual([false, false, false, true]);
    expect(squares('talking')).toHaveLength(8);
    expect(target.querySelector('[data-row="working"] .sg-pack-name span')?.textContent).toBe('loop');
    unmount(app!);
    app = null;
    target.innerHTML = '';
    draw('pixel');
    expect(squares('idle')).toHaveLength(1);
    expect(squares('idle')[0]!.getAttribute('data-pack')).toBe('pixel');
  });

  test('working_subagent draws three ribbons, each a contrast color off its subagent series, never the body color', () => {
    draw();
    const body = seriesIndex('mworking_subagent');
    for (const sq of squares('working_subagent')) {
      expect((sq as HTMLElement).style.getPropertyValue('--c')).toBe(`var(--oc-series-${body})`);
      const back = [...sq.querySelectorAll<HTMLElement>('.pk-fxb .pk-orb')].map((o) => o.style.getPropertyValue('--k'));
      expect(back).toEqual(
        [2, 4, 6].map((shift) => {
          const c = contrastIndex(seriesIndex('mworking_subagent', shift));
          return `var(--oc-series-${c === body ? (c % 8) + 1 : c})`;
        }),
      );
      expect(back).not.toContain(`var(--oc-series-${body})`);
    }
  });

  test('a one-shot row replays on its period; a loop, a rest and the still column never do; a hidden tab skips the replay', () => {
    draw();
    const dead = squares('dead');
    const idle = squares('idle');
    const priority = squares('alert_priority');
    wait(3199);
    expect(squares('dead').slice(0, 3)).toEqual(dead.slice(0, 3));
    wait(2);
    const first = squares('dead');
    expect(first.slice(0, 3).every((e, i) => e !== dead[i])).toBe(true);
    expect(first[3]).toBe(dead[3]);
    wait(8000);
    expect(squares('dead').slice(0, 3).every((e, i) => e !== first[i])).toBe(true);
    wait(120000);
    expect(squares('idle')).toEqual(idle);
    expect(squares('alert_priority')).toEqual(priority);
    Object.defineProperty(document, 'hidden', { value: true, configurable: true });
    const parked = squares('question');
    wait(60000);
    expect(squares('question')).toEqual(parked);
    Object.defineProperty(document, 'hidden', { value: false, configurable: true });
    wait(12000);
    expect(squares('question').slice(0, 3).every((e, i) => e !== parked[i])).toBe(true);
  });

  test('every replaying state of the mockup replays, and only those', () => {
    draw();
    const before = new Map([...new Set([...target.querySelectorAll('[data-row]')].map((r) => r.getAttribute('data-row')!))].map((st) => [st, squares(st)[0]!]));
    wait(12000);
    const replayed = [...before].filter(([st, el]) => squares(st)[0] !== el).map(([st]) => st);
    expect(replayed.sort()).toEqual(
      ['alert_routine', 'asleep', 'dead', 'done', 'escalating', 'finished_unread', 'learning', 'notice', 'promoted', 'question', 'question_waiting', 'working', 'working_subagent'].sort(),
    );
  });
});
