import { cellSearchFor } from '../../lib/terminal-search/cell-search';
import { terminalSearchController } from '../../lib/terminal-search/mount-search';
import { PRIMARY_SLOT } from '../engine/model';
import { layoutMode } from './mode.svelte';

export interface DrivenSearch {
  query: string;
  readonly matchCount: number | null;
  drive(): void;
  release(): void;
  runQuery(): void;
  step(dir: 'next' | 'prev'): void;
}

export interface SearchTarget {
  rowId: number;
  controller: DrivenSearch;
}

export function layoutSearchTargets(): SearchTarget[] {
  const out: SearchTarget[] = [];
  for (const member of [...layoutMode.members].sort((a, b) => a.position - b.position)) {
    const anchor = member.session_row_id === layoutMode.anchorRowId;
    const controller = anchor ? terminalSearchController() : cellSearchFor(`terminal:row:${member.session_row_id}`);
    if (controller) out.push({ rowId: member.session_row_id, controller });
  }
  return out;
}

export class LayoutSearch {
  query = $state('');
  current = $state<number | null>(null);
  #within = 0;
  #targets: () => SearchTarget[];
  #driven: SearchTarget[] = [];

  constructor(targets: () => SearchTarget[] = layoutSearchTargets) {
    this.#targets = targets;
  }

  run(query: string): void {
    this.query = query;
    this.current = null;
    this.#within = 0;
    if (!query) {
      this.release();
      return;
    }
    const targets = this.#targets();
    for (const gone of this.#driven) {
      if (!targets.some((one) => one.controller === gone.controller)) gone.controller.release();
    }
    this.#driven = targets;
    for (const target of targets) {
      target.controller.drive();
      target.controller.query = query;
      target.controller.runQuery();
    }
  }

  release(): void {
    for (const target of this.#driven) target.controller.release();
    this.#driven = [];
    this.query = '';
    this.current = null;
    this.#within = 0;
  }

  countFor(rowId: number): number | null {
    if (!this.query) return null;
    return this.#driven.find((one) => one.rowId === rowId)?.controller.matchCount ?? null;
  }

  get total(): number | null {
    if (!this.query) return null;
    let sum: number | null = null;
    for (const target of this.#driven) {
      const count = target.controller.matchCount;
      if (count !== null) sum = (sum ?? 0) + count;
    }
    return sum;
  }

  get position(): number | null {
    if (this.current === null) return null;
    let before = 0;
    for (const target of this.#driven) {
      if (target.rowId === this.current) return before + this.#within + 1;
      before += target.controller.matchCount ?? 0;
    }
    return null;
  }

  step(dir: 'next' | 'prev'): void {
    const hits = this.#driven.filter((one) => (one.controller.matchCount ?? 0) > 0);
    if (!this.query || hits.length === 0) return;
    const at = hits.findIndex((one) => one.rowId === this.current);
    const here = hits[at];
    if (!here) {
      this.#land(hits[dir === 'next' ? 0 : hits.length - 1]!, dir);
      return;
    }
    const count = here.controller.matchCount ?? 0;
    if (dir === 'next' && this.#within + 1 < count) {
      here.controller.step('next');
      this.#within += 1;
      return;
    }
    if (dir === 'prev' && this.#within > 0) {
      here.controller.step('prev');
      this.#within -= 1;
      return;
    }
    const nextAt = (at + (dir === 'next' ? 1 : -1) + hits.length) % hits.length;
    this.#land(hits[nextAt]!, dir);
  }

  #land(target: SearchTarget, dir: 'next' | 'prev'): void {
    target.controller.runQuery();
    this.#within = 0;
    if (dir === 'prev') {
      // wraps to the last
      target.controller.step('prev');
      this.#within = Math.max(0, (target.controller.matchCount ?? 1) - 1);
    }
    this.current = target.rowId;
  }
}

export const layoutSearch = new LayoutSearch();
