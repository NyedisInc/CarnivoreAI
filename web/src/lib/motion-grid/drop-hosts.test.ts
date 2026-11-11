/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { dropHostAt, dropHostById, registerDropHost, type DropHost } from './drop-hosts';

function box(l: number, t: number, r: number, b: number, parent?: HTMLElement): HTMLElement {
  const el = document.createElement('div');
  el.getBoundingClientRect = () => ({ left: l, top: t, right: r, bottom: b, width: r - l, height: b - t, x: l, y: t, toJSON() {} }) as DOMRect;
  (parent ?? document.body).appendChild(el);
  return el;
}
const host = (id: string, extra: Partial<DropHost> = {}): DropHost => ({ id, accept: () => true, ...extra });
const offs: (() => void)[] = [];
afterEach(() => {
  offs.splice(0).forEach((f) => f());
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

describe('drop hosts', () => {
  it('returns the innermost host under the point and none outside', () => {
    const outer = box(0, 0, 400, 400);
    const inner = box(100, 100, 200, 200, outer);
    const ho = host('outer');
    const hi = host('inner');
    offs.push(registerDropHost(outer, ho), registerDropHost(inner, hi));
    expect(dropHostAt(150, 150)?.host).toBe(hi);
    expect(dropHostAt(50, 50)?.host).toBe(ho);
    expect(dropHostAt(500, 500)).toBeNull();
  });

  it('skips a covered host when elementFromPoint names an element it does not contain', () => {
    const a = box(0, 0, 100, 100);
    const popup = box(0, 0, 100, 100);
    offs.push(registerDropHost(a, host('a')));
    document.elementFromPoint = () => popup;
    expect(dropHostAt(50, 50)).toBeNull();
    document.elementFromPoint = () => a;
    expect(dropHostAt(50, 50)?.container).toBe(a);
    document.elementFromPoint = undefined as never;
  });

  it('skips a host whose takes() refuses the kind', () => {
    const outer = box(0, 0, 400, 400);
    const inner = box(100, 100, 200, 200, outer);
    const ho = host('outer');
    offs.push(registerDropHost(outer, ho), registerDropHost(inner, host('inner', { takes: (k) => k !== 'files' })));
    expect(dropHostAt(150, 150, 'files')?.host).toBe(ho);
    expect(dropHostAt(150, 150, 'notes')?.host.id).toBe('inner');
  });

  it('unregisters, finds by id, and a second host under an id replaces the first', () => {
    const a = box(0, 0, 100, 100);
    const b = box(200, 0, 300, 100);
    const h1 = host('dashboard');
    const h2 = host('dashboard');
    const off1 = registerDropHost(a, h1);
    expect(dropHostById('dashboard')).toBe(h1);
    const off2 = registerDropHost(b, h2);
    offs.push(off2);
    expect(dropHostById('dashboard')).toBe(h2);
    expect(dropHostAt(50, 50)).toBeNull();
    off1();
    expect(dropHostById('dashboard')).toBe(h2);
    off2();
    expect(dropHostById('dashboard')).toBeNull();
    expect(dropHostAt(250, 50)).toBeNull();
  });
});
