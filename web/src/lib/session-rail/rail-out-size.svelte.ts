import type { RailEdge } from './rail-model';
import { OUT_DEFAULT_PX, clampOut, readOutSize, writeOutSize } from './rail-size';
import { sideBudget } from './side-budget.svelte';
import { widgetBars } from '../widget-bars/bar-settings.svelte';
import type { BarSize } from '../widget-bars/bar-settings.svelte';

export function roomFor(edge: RailEdge, win: { innerWidth: number; innerHeight: number } = window): number {
  return edge === 'side' ? win.innerWidth : win.innerHeight;
}

class RailOutSizes {
  #px = $state<Record<RailEdge, number | null>>({ side: readOutSize('side'), bottom: readOutSize('bottom') });

  reload(): void {
    this.#px = { side: readOutSize('side'), bottom: readOutSize('bottom') };
  }

  raw(edge: RailEdge): number {
    return this.#px[edge] ?? OUT_DEFAULT_PX[edge];
  }

  size(edge: RailEdge): BarSize {
    return widgetBars.view[edge].size;
  }

  available(edge: RailEdge, room: number): number {
    return edge === 'side' ? room - sideBudget.otherThan('slideout') : room;
  }

  max(edge: RailEdge, room: number): number {
    return clampOut(Number.MAX_SAFE_INTEGER, this.available(edge, room), edge, this.size(edge));
  }

  shown(edge: RailEdge, room: number): number {
    return clampOut(this.raw(edge), this.available(edge, room), edge, this.size(edge));
  }

  set(edge: RailEdge, px: number, room: number): number {
    const next = clampOut(px, this.available(edge, room), edge, this.size(edge));
    this.#px[edge] = next;
    return next;
  }

  remember(edge: RailEdge): void {
    writeOutSize(edge, this.raw(edge));
  }

  reset(edge: RailEdge): void {
    this.#px[edge] = null;
    writeOutSize(edge, OUT_DEFAULT_PX[edge]);
  }
}

export const railOutSizes = new RailOutSizes();
