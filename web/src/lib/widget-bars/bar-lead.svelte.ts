import type { RailEdge } from '../session-rail/rail-model';

class BarLead {
  edge = $state<RailEdge | null>(null);

  take(edge: RailEdge): void {
    this.edge = edge;
  }

  takeIfFree(edge: RailEdge): void {
    if (this.edge === null) this.edge = edge;
  }

  /* no longer holds */
  release(edge: RailEdge): void {
    if (this.edge === edge) this.edge = null;
  }
}

export const barLead = new BarLead();
