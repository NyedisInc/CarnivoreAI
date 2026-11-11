/** @vitest-environment jsdom */
import { afterEach, describe, expect, it } from 'vitest';
import { mountStack } from './stack-motion';

const observers: { target: HTMLElement | null; live: boolean }[] = [];

afterEach(() => {
  observers.length = 0;
  delete (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
});

describe('mountStack cell.update', () => {
  it('observes the first child again under the new id', () => {
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
      rec: { target: HTMLElement | null; live: boolean } = { target: null, live: true };
      constructor() {
        observers.push(this.rec);
      }
      observe(el: HTMLElement): void {
        this.rec.target = el;
      }
      unobserve(): void {}
      disconnect(): void {
        this.rec.live = false;
      }
    };
    const column = document.createElement('div');
    document.body.appendChild(column);
    const wrapper = document.createElement('div');
    const inner = document.createElement('div');
    wrapper.appendChild(inner);
    column.appendChild(wrapper);
    const stack = mountStack(column, { axis: 'y', order: () => ['a'], place: () => {}, label: (id: string) => id });
    const cell = stack.cell(wrapper, 'a');
    expect(observers.filter((o) => o.live && o.target === inner)).toHaveLength(1);
    cell.update('b');
    expect(observers.filter((o) => o.live && o.target === inner)).toHaveLength(1);
    cell.destroy();
    stack.destroy();
    expect(observers.some((o) => o.live)).toBe(false);
  });
});
