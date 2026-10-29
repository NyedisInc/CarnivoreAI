import { zoneItemKey } from '../drawer-zone/zone-model';
import { manifestById } from '../../opscenter/widgets/core-manifests';
import { RAIL_EDGES, type RailEdge } from './rail-model';
import { pressKey, readLastUsed, readOpenKeys, shownKeys, writeLastUsed, writeOpenKeys, type LastUsed } from './rail-open';
import { railHolding, railStores } from './rail-store.svelte';
import { panelPins } from '../widget-bars/panel-pins.svelte';

function sectionKeys(edge: RailEdge): string[][] {
  return railStores[edge].sections.map((section) => section.filter((item) => manifestById(item.widget)).map((item) => zoneItemKey(item)));
}

function restoredOpen(): Record<RailEdge, string[]> {
  return { side: readOpenKeys('side'), bottom: readOpenKeys('bottom') };
}

class RailSlideout {
  #restored = restoredOpen();
  #open = $state<Record<RailEdge, string[]>>(this.#restored);
  restoring = $state(RAIL_EDGES.some((edge) => this.#restored[edge].length > 0));
  lastOpenedByPress = $state<RailEdge | null>(null);
  #last = $state<Record<RailEdge, LastUsed>>({ side: readLastUsed('side'), bottom: readLastUsed('bottom') });

  shown(edge: RailEdge): string[] {
    if (!this.#open[edge].length) return [];
    return shownKeys(sectionKeys(edge), this.#open[edge], this.#last[edge]);
  }

  get edge(): RailEdge | null {
    return RAIL_EDGES.find((edge) => this.shown(edge).length > 0) ?? null;
  }

  get key(): string | null {
    for (const edge of RAIL_EDGES) {
      const shown = this.shown(edge);
      if (shown.length) return shown[0]!;
    }
    return null;
  }

  isOpen(key: string): boolean {
    return RAIL_EDGES.some((edge) => this.shown(edge).includes(key));
  }

  press(edge: RailEdge, key: string): boolean {
    const wasOut = this.shown(edge).length > 0;
    const result = pressKey(sectionKeys(edge), this.shown(edge), key, this.#last[edge]);
    if (!result) return wasOut;
    this.#last[edge] = result.last;
    writeLastUsed(edge, result.last);
    this.#open[edge] = result.open;
    this.#persist();
    const out = this.shown(edge).length > 0;
    if (!out || !wasOut) panelPins.unpin(edge);
    if (out && !wasOut) this.lastOpenedByPress = edge;
    return out;
  }

  takePressFocus(edge: RailEdge): boolean {
    if (this.lastOpenedByPress !== edge) return false;
    this.lastOpenedByPress = null;
    return true;
  }

  open(key: string): void {
    const edge = railHolding(key);
    if (edge && !this.shown(edge).includes(key)) this.press(edge, key);
  }

  close(edge?: RailEdge): void {
    for (const one of edge ? [edge] : RAIL_EDGES) {
      this.#open[one] = [];
      panelPins.unpin(one);
    }
    if (!edge || this.lastOpenedByPress === edge) this.lastOpenedByPress = null;
    this.#persist();
  }

  #persist(): void {
    this.restoring = false;
    for (const edge of RAIL_EDGES) writeOpenKeys(edge, this.shown(edge));
  }

  reload(): void {
    this.#last = { side: readLastUsed('side'), bottom: readLastUsed('bottom') };
    this.#open = restoredOpen();
    this.restoring = RAIL_EDGES.some((edge) => this.#open[edge].length > 0);
  }
}

export const railSlideout = new RailSlideout();
