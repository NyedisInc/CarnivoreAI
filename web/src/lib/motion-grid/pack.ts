
export interface PackItem {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PackPin {
  id: string;
  x: number;
  y: number;
}

const MAX_PASSES = 80;

interface Indexed extends PackItem {
  i: number;
}

function clamp(v: number, a: number, b: number): number {
  return v < a ? a : v > b ? b : v;
}

export function hit(
  a: Pick<PackItem, 'x' | 'y' | 'w' | 'h'>,
  b: Pick<PackItem, 'x' | 'y' | 'w' | 'h'>,
): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

function byYX(a: Indexed, b: Indexed): number {
  return a.y - b.y || a.x - b.x || a.i - b.i;
}

function indexed(items: readonly PackItem[], cols: number): Indexed[] {
  return items.map((it, i) => ({ id: it.id, x: it.x, y: it.y, w: Math.min(it.w, cols), h: it.h, i }));
}

export function pack(items: readonly PackItem[], cols: number, pin: PackPin | null = null): PackItem[] {
  const list = indexed(items, cols);
  let pinned: Indexed | null = null;
  if (pin) {
    pinned = list.find((o) => o.id === pin.id) ?? null;
    if (pinned) {
      pinned.x = clamp(pin.x, 0, cols - pinned.w);
      pinned.y = Math.max(0, pin.y);
    }
  }
  const rest = list.filter((o) => o !== pinned).sort(byYX);
  let placed: PackItem[] = [];
  for (let iter = 0; iter < MAX_PASSES; iter += 1) {
    placed = pinned ? [pinned] : [];
    const others: PackItem[] = [];
    for (const o of rest) {
      const c: PackItem = { id: o.id, x: clamp(o.x, 0, cols - o.w), y: 0, w: o.w, h: o.h };
      for (;;) {
        let m = Infinity;
        for (const p of placed) if (hit(c, p)) m = Math.min(m, p.y + p.h);
        if (m === Infinity) break;
        c.y = m;
      }
      placed.push(c);
      others.push(c);
    }
    if (!pinned) break;
    let bottom = 0;
    for (const c of others) bottom = Math.max(bottom, c.y + c.h);
    let py = pinned.y;
    if (py > bottom) py = bottom;
    while (py > 0 && !others.some((c) => hit({ x: pinned!.x, y: py - 1, w: pinned!.w, h: pinned!.h }, c))) py -= 1;
    if (py === pinned.y) break;
    pinned.y = py;
  }
  const out = new Map<string, PackItem>();
  for (const c of placed) out.set(c.id, c);
  return list.map((o) => {
    const c = out.get(o.id) as PackItem;
    return { id: o.id, x: c.x, y: c.y, w: c.w, h: c.h };
  });
}

export function flow(items: readonly PackItem[], cols: number): PackItem[] {
  const placed: PackItem[] = [];
  for (const it of indexed(items, cols).sort(byYX)) {
    search: for (let y = 0; ; y += 1) {
      for (let x = 0; x <= cols - it.w; x += 1) {
        const c: PackItem = { id: it.id, x, y, w: it.w, h: it.h };
        if (!placed.some((p) => hit(c, p))) {
          placed.push(c);
          break search;
        }
      }
    }
  }
  return placed;
}

export function firstFit(
  items: readonly Pick<PackItem, 'x' | 'y' | 'w' | 'h'>[],
  cols: number,
  w: number,
  h: number,
): { x: number; y: number } {
  for (let y = 0; ; y += 1) {
    for (let x = 0; x <= cols - w; x += 1) {
      const c = { x, y, w, h };
      if (!items.some((p) => hit(c, p))) return { x, y };
    }
  }
}
