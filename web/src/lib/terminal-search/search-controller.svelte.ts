import { flushSync } from 'svelte';

import { t } from '../i18n/index.svelte';
import { uiPrefs, type SearchDirection } from '../ui/prefs.svelte';
import { countLabel, promptCountLabel } from './count-label';
import { RailModel } from './rail-model.svelte';
import { onAlternateScreen, type SearchHost } from './search-host';
import type { KeyRoutingTarget } from './search-keys';
import type { EngineResults, HistoryState, TermLike } from './types';
import { whenWritesQuiet } from './write-quiet';

export const TYPE_DEBOUNCE_MS = 120;

export const SESSION_WATCH_MS = 750;

export class SearchController implements KeyRoutingTarget {
    opened = $state(false);
    query = $state('');
    history = $state<HistoryState>(null);
    results = $state.raw<EngineResults | null>(null);
    rail: RailModel;
    headerHosted = $state(false);
    driven = $state(false);

    #host: SearchHost;
    #openedFor: string | null = null;
    #panelEl: HTMLElement | null = null;
    #inputEl: HTMLInputElement | null = null;
    #typeTimer: ReturnType<typeof setTimeout> | null = null;
    #watch: ReturnType<typeof setInterval> | null = null;
    #unsubscribeResults: (() => void) | null = null;
    #pendingJump: number | null = null;
    #quietCancel: (() => void) | null = null;

    constructor(host: SearchHost) {
        this.#host = host;
        this.rail = new RailModel({
            term: () => host.term(),
            promptScan: () => host.promptScan(),
            isRule: () => host.isRule(),
            onTerminal: (listener) => host.onTerminal(listener),
            promptTexts: async () => (await host.promptTexts?.()) ?? null,
        });
    }

    get direction(): SearchDirection {
        return uiPrefs.searchDirection;
    }

    toggleDirection(): void {
        uiPrefs.setSearchDirection(
            this.direction === 'bottom_up' ? 'top_down' : 'bottom_up',
        );
    }

    get promptsOnly(): boolean {
        return uiPrefs.searchPromptsOnly;
    }

    #promptsOnlyActive(): boolean {
        return this.promptsOnly && this.promptsOnlyAvailable;
    }

    #promptsOnlyDisabledReason = $state<string | null>(null);

    get promptsOnlyDisabledReason(): string | null {
        return this.#promptsOnlyDisabledReason;
    }

    #refreshPromptsOnlyAvailability(): void {
        this.#promptsOnlyDisabledReason = null;
    }

    get promptsOnlyAvailable(): boolean {
        return this.promptsOnlyDisabledReason === null;
    }

    get promptsOnlyTitle(): string {
        return this.promptsOnlyDisabledReason ?? t('search.prompts_only.toggle');
    }

    togglePromptsOnly(): void {
        if (!this.promptsOnlyAvailable) return;
        uiPrefs.setSearchPromptsOnly(!this.promptsOnly);
        if (this.opened && this.query) this.runQuery();
    }

    get countText(): string {
        if (this.#promptsOnlyActive()) {
            return promptCountLabel({
                prompts: this.rail.prompts,
                currentOrdinal: this.rail.currentOrdinal,
            }, t);
        }
        return countLabel({
            history: this.history,
            query: this.query,
            results: this.results,
        }, t);
    }

    get matchCount(): number | null {
        if (this.#promptsOnlyActive()) return this.rail.prompts.filter((p) => p.matches).length;
        return this.results?.resultCount ?? null;
    }

    drive(): void {
        this.driven = true;
        if (!this.opened) this.open(false);
    }

    release(): void {
        if (this.driven) this.close();
    }

    setPanelElement(el: HTMLElement | null): void {
        this.#panelEl = el;
    }

    setInputElement(el: HTMLInputElement | null): void {
        this.#inputEl = el;
    }


    isOpen(): boolean {
        return this.opened;
    }

    containsTarget(node: unknown): boolean {
        if (!this.opened || !this.#panelEl) return false;
        return this.#panelEl.contains(node as Node | null);
    }

    alternate(): boolean {
        return onAlternateScreen(this.#host.term());
    }

    screenActive(): boolean {
        return this.#host.terminalScreenActive();
    }

    modalOpen(): boolean {
        return this.#host.modalOpen();
    }


    open(focus = true): void {
        if (this.opened) {
            if (!focus) return;
            this.driven = false;
            flushSync();
            this.focusInput();
            return;
        }
        const term = this.#host.term();
        if (!term) return;

        this.opened = true;
        this.#openedFor = this.#host.sessionId();
        this.results = null;
        this.history = null;

        const engine = this.#host.engine();
        if (engine) {
            engine.attach(term);
            this.#unsubscribeResults = engine.onResults((r) => {
                this.results = r;
            });
        }

        this.rail.show();

        if (focus) {
            flushSync();
            this.focusInput();
        }

        this.#loadHistory(term);
        this.#refreshPromptsOnlyAvailability();
        this.#watch = setInterval(() => this.#checkSessionStillOurs(), SESSION_WATCH_MS);
    }

    close(): void {
        if (!this.opened) return;
        const driven = this.driven;
        this.driven = false;
        this.opened = false;
        this.#openedFor = null;
        this.#pendingJump = null;
        this.#quietCancel?.();
        this.history = null;
        this.results = null;
        if (this.#typeTimer !== null) {
            clearTimeout(this.#typeTimer);
            this.#typeTimer = null;
        }
        if (this.#watch !== null) {
            clearInterval(this.#watch);
            this.#watch = null;
        }
        if (this.#unsubscribeResults) {
            this.#unsubscribeResults();
            this.#unsubscribeResults = null;
        }
        this.#host.engine()?.clear();
        this.rail.hide();
        if (!driven) this.#host.focusTerm();
    }

    focusTerminal(): void {
        this.#host.focusTerm();
    }

    openAt(query: string, fromEnd: number): void {
        if (this.opened && this.#openedFor !== this.#host.sessionId()) this.close();
        this.query = query;
        this.#pendingJump = Math.max(0, Math.floor(fromEnd) || 0);
        if (this.opened) this.focusInput(); else this.open();
        if (!this.opened) this.#pendingJump = null;
        else if (this.history !== 'pending') this.#applyJump();
    }

    #applyJump(): void {
        this.#quietCancel?.();
        this.#quietCancel = whenWritesQuiet(this.#host.term(), () => {
            this.#quietCancel = null;
            const steps = this.#pendingJump;
            if (steps === null) return;
            this.#pendingJump = null;
            const engine = this.#host.engine();
            this.rail.setFilter(engine ? engine.predicate(this.query) : null);
            if (!engine || !this.query) return;
            this.#clearSelection();
            engine.find(this.query, { incremental: false }, 'prev');
            for (let i = 0; i < steps; i++) engine.prev();
        });
    }

    toggle(): void {
        if (this.opened) this.close();
        else this.open();
    }

    onType(): void {
        if (this.#typeTimer !== null) clearTimeout(this.#typeTimer);
        this.#typeTimer = setTimeout(() => {
            this.#typeTimer = null;
            if (this.opened) this.runQuery();
        }, TYPE_DEBOUNCE_MS);
    }

    runQuery(): void {
        const engine = this.#host.engine();
        const bottomUp = this.direction === 'bottom_up';
        if (bottomUp) this.#clearSelection();
        if (this.#promptsOnlyActive()) engine?.clear();
        else engine?.find(this.query, { incremental: true }, bottomUp ? 'prev' : 'next');
        this.rail.setFilter(engine ? engine.predicate(this.query) : null);
        if (this.#promptsOnlyActive()) this.#landOnMatchingPrompt(bottomUp);
    }

    #landOnMatchingPrompt(bottomUp: boolean): void {
        const list = this.rail.prompts.filter((p) => p.matches);
        const target = bottomUp ? list[list.length - 1] : list[0];
        if (target) this.rail.jumpTo(target.ordinal);
    }

    step(dir: 'next' | 'prev'): void {
        if (!this.query) return;
        const upward = (dir === 'next') === (this.direction === 'bottom_up');
        if (this.#promptsOnlyActive()) {
            this.rail.jump(upward ? -1 : 1);
            return;
        }
        const engine = this.#host.engine();
        if (!engine) return;
        if (upward) engine.prev();
        else engine.next();
    }

    #clearSelection(): void {
        const term = this.#host.term();
        if (!term || typeof term.clearSelection !== 'function') return;
        try {
            term.clearSelection();
        } catch (err) {
            console.warn('TerminalSearch: could not clear the pane selection', err);
        }
    }

    jump(delta: number): void {
        this.rail.jump(delta);
    }

    focusInput(): void {
        if (!this.#inputEl) return;
        try {
            this.#inputEl.focus({ preventScroll: true });
            this.#inputEl.select?.();
        } catch (err) {
            console.warn('TerminalSearch: could not focus the search field', err);
        }
    }

    #loadHistory(term: TermLike): void {
        const hist = this.#host.history();
        if (!hist || typeof hist.ensureLoaded !== 'function') {
            this.history = 'unavailable';
            return;
        }
        this.history = 'pending';
        const forSession = this.#openedFor;
        Promise.resolve(hist.ensureLoaded(term, forSession))
            .then((r) => {
                if (!this.opened || this.#openedFor !== forSession) return;
                this.history = r?.loaded ? r.loaded : 'unavailable';
                this.rail.refresh();
                if (this.#pendingJump !== null) this.#applyJump();
                else if (this.query) this.runQuery();
            })
            .catch((err: unknown) => {
                if (!this.opened || this.#openedFor !== forSession) return;
                console.warn('TerminalSearch: history load failed', err);
                this.history = 'unavailable';
                this.#applyJump();
            });
    }

    #checkSessionStillOurs(): void {
        if (!this.opened) return;
        const now = this.#host.sessionId();
        if (now === null || this.#openedFor === null) return;
        if (now !== this.#openedFor) this.close();
    }
}
