
export interface DropHost {
  id: string;
  accept(kind: string, ev: PointerEvent): boolean;
  add?(kind: string): boolean;
  takes?(kind: string): boolean;
}

const hosts = new Map<HTMLElement, DropHost>();

export function registerDropHost(container: HTMLElement, host: DropHost): () => void {
  for (const [el, h] of hosts) if (h.id === host.id) hosts.delete(el);
  hosts.set(container, host);
  return () => {
    if (hosts.get(container) === host) hosts.delete(container);
  };
}

export function dropHostById(id: string): DropHost | null {
  for (const h of hosts.values()) if (h.id === id) return h;
  return null;
}

export function dropHostAt(x: number, y: number, kind?: string, doc: Document = document): { container: HTMLElement; host: DropHost } | null {
  const top = doc.elementFromPoint?.(x, y) ?? null;
  let best: { container: HTMLElement; host: DropHost } | null = null;
  for (const [container, host] of hosts) {
    const r = container.getBoundingClientRect();
    if (x < r.left || x > r.right || y < r.top || y > r.bottom) continue;
    if (kind !== undefined && host.takes && !host.takes(kind)) continue;
    if (top && !container.contains(top)) continue;
    if (!best || best.container.contains(container)) best = { container, host };
  }
  return best;
}
