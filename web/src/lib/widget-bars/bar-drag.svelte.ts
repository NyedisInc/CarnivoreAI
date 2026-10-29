import type { RailEdge } from '../session-rail/rail-model';
import { barLead } from './bar-lead.svelte';
import { widgetBars, type BarSettings, type BarSize } from './bar-settings.svelte';
import type { BarVisual } from './bar-state';
import { BAR_SIZES } from './bar-size';

export type BarPreview = BarSize | 'closed';

export const DRAG_SLOP_PX = 4;

const STEPS: readonly BarPreview[] = ['closed', 'compact', 'cozy', 'detailed'];

export function snapBar(edge: RailEdge, extent: number): BarPreview {
  const e = (size: BarSize): number => BAR_SIZES[size][edge].bar;
  if (extent < e('compact') / 2) return 'closed';
  if (extent < (e('compact') + e('cozy')) / 2) return 'compact';
  if (extent < (e('cozy') + e('detailed')) / 2) return 'cozy';
  return 'detailed';
}

const placeOf = (bar: BarSettings): BarPreview => (bar.mode === 'pinned' ? bar.size : 'closed');

/*  hidden  */
export function dragLook(look: BarVisual, preview: BarPreview | null): BarVisual {
  if (preview === null || look === 'absent' || look === 'edit' || look === 'held') return look;
  return preview === 'closed' ? 'handle' : 'pinned';
}

export class BarDrag {
  preview = $state<BarPreview | null>(null);
  #from: { pos: number; extent: number } | null = null;
  #lead: RailEdge | null = null;
  #swallow = false;

  constructor(
    private readonly edge: RailEdge,
    private readonly read: () => BarSettings,
    private readonly onclosed: () => void = () => {},
  ) {}

  begin(pos: number, extent: number): void {
    this.#from = { pos, extent };
    this.#swallow = false;
    this.#lead = barLead.edge;
    window.addEventListener('pointermove', this.#move);
    window.addEventListener('pointerup', this.#up);
    window.addEventListener('pointercancel', this.cancel);
    window.addEventListener('keydown', this.#esc, true);
  }

  move(pos: number): void {
    if (!this.#from) return;
    if (this.preview === null && Math.abs(pos - this.#from.pos) < DRAG_SLOP_PX) return;
    this.preview = snapBar(this.edge, this.#from.extent + (this.#from.pos - pos));
    if (this.preview !== 'closed') barLead.take(this.edge);
  }

  end(): void {
    const preview = this.preview;
    this.#stop();
    if (preview === null) return;
    this.#swallow = true;
    this.#settle(preview);
    if (preview === 'closed') this.onclosed();
  }

  cancel = (): void => {
    if (this.preview !== null) {
      this.#swallow = true;
      barLead.edge = this.#lead;
    }
    this.#stop();
  };

  consumeClick(): boolean {
    const swallowed = this.#swallow;
    this.#swallow = false;
    return swallowed;
  }

  key(key: string): boolean {
    const grow = this.edge === 'side' ? 'ArrowLeft' : 'ArrowUp';
    const shrink = this.edge === 'side' ? 'ArrowRight' : 'ArrowDown';
    const at = STEPS.indexOf(placeOf(this.read()));
    let to: BarPreview;
    if (key === grow) to = STEPS[Math.min(at + 1, STEPS.length - 1)]!;
    else if (key === shrink) to = STEPS[Math.max(at - 1, 0)]!;
    else if (key === 'Home') to = 'cozy';
    else if (key === 'End') to = 'detailed';
    else return false;
    this.#settle(to);
    if (to === 'closed') this.onclosed();
    return true;
  }

  #settle(to: BarPreview): void {
    const now = this.read();
    if (to === 'closed') {
      if (now.mode !== 'autohide') void widgetBars.set(this.edge, { mode: 'autohide' });
    } else if (now.mode !== 'pinned' || now.size !== to) {
      void widgetBars.set(this.edge, { size: to, mode: 'pinned' });
      barLead.take(this.edge);
    }
  }

  #stop(): void {
    this.preview = null;
    this.#from = null;
    window.removeEventListener('pointermove', this.#move);
    window.removeEventListener('pointerup', this.#up);
    window.removeEventListener('pointercancel', this.cancel);
    window.removeEventListener('keydown', this.#esc, true);
  }

  #move = (event: PointerEvent): void => this.move(this.edge === 'side' ? event.clientX : event.clientY);
  #up = (): void => this.end();
  #esc = (event: KeyboardEvent): void => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    this.cancel();
  };
}
