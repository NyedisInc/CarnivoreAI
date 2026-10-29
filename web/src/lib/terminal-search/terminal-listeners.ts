/* nothing at all */
import type { DisposableLike, TermLike } from './types';

export const REFRESH_THROTTLE_MS = 300;

export interface ListenerHost {
    term(): TermLike | null;
    onTerminal?(listener: () => void): () => void;
}

export interface ListenerSink {
    rescan(): void;
    viewportMoved(): void;
    held(): boolean;
}

export class TerminalListeners {
    #host: ListenerHost;
    #sink: ListenerSink;
    #term: TermLike | null = null;
    #writeSub: DisposableLike | null = null;
    #scrollSub: DisposableLike | null = null;
    #lifeSub: (() => void) | null = null;
    #throttle: ReturnType<typeof setTimeout> | null = null;
    #rafPending = false;

    constructor(host: ListenerHost, sink: ListenerSink) {
        this.#host = host;
        this.#sink = sink;
    }

    get attachedTo(): TermLike | null {
        return this.#term;
    }

    attach(): void {
        this.#watch();
        this.#listen();
    }

    detach(): void {
        this.#unwatch();
        this.#unlisten();
    }

    #watch(): void {
        if (this.#lifeSub || typeof this.#host.onTerminal !== 'function') return;
        try {
            this.#lifeSub = this.#host.onTerminal(() => this.#terminalChanged());
        } catch (err) {
            console.warn('TerminalSearch: could not follow the terminal', err);
        }
    }

    #unwatch(): void {
        const stop = this.#lifeSub;
        this.#lifeSub = null;
        if (!stop) return;
        try {
            stop();
        } catch (err) {
            console.warn('TerminalSearch: could not stop following the terminal', err);
        }
    }

    #terminalChanged(): void {
        if (!this.#sink.held()) return;
        this.#listen();
        this.#sink.rescan();
    }

    #listen(): void {
        const term = this.#host.term();
        if (term && term === this.#term) return;
        this.#unlisten();
        if (!term) return;
        try {
            if (typeof term.onWriteParsed === 'function') {
                this.#writeSub = term.onWriteParsed(() => this.#scheduleRescan());
            }
            if (typeof term.onScroll === 'function') {
                this.#scrollSub = term.onScroll(() => this.#scheduleViewport());
            }
            this.#term = term;
        } catch (err) {
            console.warn('TerminalSearch: could not observe the terminal', err);
        }
    }

    #unlisten(): void {
        this.#writeSub?.dispose?.();
        this.#scrollSub?.dispose?.();
        this.#writeSub = null;
        this.#scrollSub = null;
        this.#term = null;
        if (this.#throttle !== null) {
            clearTimeout(this.#throttle);
            this.#throttle = null;
        }
    }

    #scheduleRescan(): void {
        if (this.#throttle !== null) return;
        this.#throttle = setTimeout(() => {
            this.#throttle = null;
            this.#sink.rescan();
        }, REFRESH_THROTTLE_MS);
    }

    #scheduleViewport(): void {
        if (this.#rafPending) return;
        this.#rafPending = true;
        const run = (): void => {
            this.#rafPending = false;
            this.#sink.viewportMoved();
        };
        if (typeof requestAnimationFrame === 'function') requestAnimationFrame(run);
        else setTimeout(run, 16);
    }
}
