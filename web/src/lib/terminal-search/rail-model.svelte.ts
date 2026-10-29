import { matchFullTexts } from './prompt-full-text';
import { headerControlsFor, headerPromptFor } from './prompt-header';
import type { HeaderControls, PlacedPrompt } from './prompt-header';
import { lineOf, markerFor, releaseMarkers } from './rail-markers';
import { TerminalListeners } from './terminal-listeners';
import { tickViews } from './tick-views';
import type { TickView } from './tick-views';
import type { PromptScanApi, RailPrompt, TermLike, Tick } from './types';

export type { TickView };

export interface RailHost {
    term(): TermLike | null;
    promptScan(): PromptScanApi | null;
    isRule(): ((text: string) => boolean) | undefined;
    onTerminal?(listener: () => void): () => void;
    promptTexts?(): Promise<string[] | null>;
}

export class RailModel {
    prompts = $state.raw<RailPrompt[]>([]);
    ticks = $state.raw<Tick[]>([]);
    currentOrdinal = $state(0);
    viewportTop = $state(0);
    maxViewportTop = $state(0);
    railHeight = $state(0);

    #host: RailHost;
    #retained = 0;
    #onJump: (prompt: RailPrompt) => void;
    #el: HTMLElement | null = null;
    #shown = $state(false);
    #filter: ((text: string) => boolean) | null = null;
    #bufferLength = 0;
    #listeners: TerminalListeners;

    constructor(host: RailHost, onJump?: (prompt: RailPrompt) => void) {
        this.#host = host;
        this.#onJump = onJump ?? (() => {});
        this.#listeners = new TerminalListeners(host, {
            rescan: () => this.refresh(),
            viewportMoved: () => this.#readViewport(),
            held: () => this.#shown || this.#retained > 0,
        });
    }

    get hidden(): boolean {
        return !this.#shown || this.prompts.length === 0;
    }

    get headerPrompt(): RailPrompt | null {
        const ordinal = headerPromptFor(this.#placed(), this.viewportTop);
        return ordinal === 0 ? null : this.#byOrdinal(ordinal);
    }

    async fullTextOf(ordinal: number): Promise<string | null> {
        const load = this.#host.promptTexts;
        if (!load) return null;
        const scanned = this.prompts.map((p) => ({ ordinal: p.ordinal, text: p.text }));
        try {
            const transcript = await load.call(this.#host);
            if (!transcript || transcript.length === 0) return null;
            return matchFullTexts(scanned, transcript).get(ordinal) ?? null;
        } catch {
            return null;
        }
    }

    get headerControls(): HeaderControls {
        const current = this.headerPrompt;
        return current
            ? headerControlsFor(this.#placed(), current.ordinal, this.maxViewportTop)
            : { hasPrev: false, hasNext: false };
    }

    get filtered(): number {
        return this.prompts.filter((p) => p.matches).length;
    }

    get tickViews(): TickView[] {
        return tickViews(this.ticks, this.prompts, this.currentOrdinal);
    }

    setElement(el: HTMLElement | null): void {
        this.#el = el;
    }

    refresh(): void {
        const term = this.#host.term();
        const buf = term?.buffer?.active;
        releaseMarkers(this.prompts);
        if (!term || !buf || buf.type === 'alternate') {
            this.prompts = [];
            this.ticks = [];
            return;
        }
        const scanner = this.#host.promptScan();
        const found = scanner
            ? scanner.scan(buf, {
                cols: term.cols,
                baseY: buf.baseY,
                rows: term.rows,
                isRule: this.#host.isRule(),
            })
            : [];
        this.prompts = found.map((p) => ({
            ...p,
            marker: markerFor(term, buf.baseY ?? 0, buf.cursorY ?? 0, p.line),
            matches: this.#verdict(p.text),
        }));
        this.#bufferLength = typeof buf.length === 'number' ? buf.length : 0;
        this.maxViewportTop = typeof buf.baseY === 'number' ? buf.baseY : 0;
        this.#relayout();
        this.setViewport(typeof buf.viewportY === 'number' ? buf.viewportY : 0);
    }

    setFilter(pred: ((text: string) => boolean) | null): void {
        this.#filter = typeof pred === 'function' ? pred : null;
        this.prompts = this.prompts.map((p) => ({ ...p, matches: this.#verdict(p.text) }));
    }

    setViewport(y: number): void {
        this.viewportTop = y;
        this.currentOrdinal = this.#ordinalAt(y);
    }

    ordinalNear(offsetY: number): number {
        if (!Number.isFinite(offsetY)) return 0;
        let best: Tick | null = null;
        let bestGap = Infinity;
        for (const tick of this.ticks) {
            const gap = Math.abs(tick.y - offsetY);
            if (gap < bestGap) {
                bestGap = gap;
                best = tick;
            }
        }
        return best?.ordinals[0] ?? 0;
    }

    jumpTo(ordinal: number): boolean {
        const p = this.#byOrdinal(ordinal);
        if (!p || p.marker?.isDisposed) return false;
        const term = this.#host.term();
        if (!term || typeof term.scrollToLine !== 'function') return false;
        try {
            term.scrollToLine(lineOf(p));
        } catch {
            return false;
        }
        this.currentOrdinal = ordinal;
        this.#onJump(p);
        return true;
    }

    jump(delta: number): boolean {
        const list = this.prompts.filter((p) => p.matches);
        if (list.length === 0) return false;
        const at = list.findIndex((p) => p.ordinal === this.currentOrdinal);
        let next: number;
        if (at === -1) next = delta < 0 ? list.length - 1 : 0;
        else {
            next = at + (delta < 0 ? -1 : 1);
            if (next < 0) next = list.length - 1;
            if (next >= list.length) next = 0;
        }
        const target = list[next];
        return target ? this.jumpTo(target.ordinal) : false;
    }

    show(): void {
        this.#shown = true;
        this.#attach();
    }

    hide(): void {
        this.#shown = false;
        if (this.#retained === 0) this.#detach();
    }

    retain(): void {
        this.#retained += 1;
        this.#attach();
    }

    release(): void {
        this.#retained = Math.max(0, this.#retained - 1);
        if (this.#retained === 0 && !this.#shown) this.#detach();
    }

    dispose(): void {
        this.#retained = 0;
        this.hide();
        releaseMarkers(this.prompts);
        this.prompts = [];
        this.ticks = [];
    }

    #relayout(): void {
        const kept = this.prompts.filter((p) => !p.marker?.isDisposed);
        if (kept.length !== this.prompts.length) this.prompts = kept;
        this.railHeight = this.#measureHeight();
        const scanner = this.#host.promptScan();
        this.ticks = scanner
            ? scanner.layoutTicks(
                kept.map((p) => ({ ordinal: p.ordinal, line: lineOf(p) })),
                this.#bufferLength,
                this.railHeight,
            )
            : [];
    }

    #measureHeight(): number {
        const own = this.#el?.clientHeight ?? 0;
        if (own > 0) return own;
        return this.#el?.parentElement?.clientHeight ?? 0;
    }

    #verdict(text: string): boolean {
        if (!this.#filter) return true;
        try {
            return !!this.#filter(text);
        } catch {
            return true;
        }
    }

    #placed(): PlacedPrompt[] {
        return this.prompts.map((p) => ({ ordinal: p.ordinal, line: lineOf(p) }));
    }

    #ordinalAt(y: number): number {
        const scanner = this.#host.promptScan();
        return scanner ? scanner.currentOrdinalFor(this.prompts, y) : 0;
    }

    #byOrdinal(ordinal: number): RailPrompt | null {
        return this.prompts.find((p) => p.ordinal === ordinal) ?? null;
    }

    #attach(): void {
        this.#listeners.attach();
        this.refresh();
    }

    #detach(): void {
        this.#listeners.detach();
    }

    #readViewport(): void {
        const buf = this.#host.term()?.buffer?.active;
        if (buf) this.setViewport(typeof buf.viewportY === 'number' ? buf.viewportY : 0);
    }
}
