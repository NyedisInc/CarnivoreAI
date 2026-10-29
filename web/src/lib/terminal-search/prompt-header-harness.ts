import { flushSync, mount, unmount } from 'svelte';

import PromptHeader from './PromptHeader.svelte';
import { RailModel } from './rail-model.svelte';
import type { PromptScanApi, ScannedPrompt } from './types';

export function scannedPrompt(
    ordinal: number,
    line: number,
    lines: string[],
): ScannedPrompt {
    const text = lines.join(' ');
    return { ordinal, line, text, full: lines.join('\n'), preview: text.slice(0, 80) };
}

export const metrics = { scrollWidth: 0, clientWidth: 0 };

export interface FakeObserver {
    targets: Element[];
    disconnected: boolean;
    fire: () => void;
}

export let observers: FakeObserver[] = [];

export function installMeasurement(): void {
    for (const name of ['scrollWidth', 'clientWidth'] as const) {
        Object.defineProperty(window.HTMLElement.prototype, name, {
            configurable: true,
            get(): number {
                return metrics[name];
            },
        });
    }
    class FakeResizeObserver {
        targets: Element[] = [];
        disconnected = false;
        #cb: () => void;
        constructor(cb: () => void) {
            this.#cb = cb;
            observers.push(this as unknown as FakeObserver);
        }
        observe(el: Element): void {
            this.targets.push(el);
        }
        disconnect(): void {
            this.disconnected = true;
        }
        fire(): void {
            this.#cb();
        }
    }
    (window as unknown as Record<string, unknown>).ResizeObserver = FakeResizeObserver;
}

export interface Harness {
    rail: RailModel;
    scrolled: number[];
    focused: () => number;
    scrollTo: (y: number) => void;
    setBaseY: (y: number) => void;
    strip: () => HTMLElement;
    button: (name: string) => HTMLButtonElement;
    maybe: (name: string) => HTMLButtonElement | null;
    destroy: () => void;
}

export function fakeRail(prompts: ScannedPrompt[]): {
    rail: RailModel; buffer: Record<string, unknown>; scrolled: number[];
} {
    const buffer: Record<string, unknown> = {
        type: 'normal',
        baseY: 976,
        cursorY: 0,
        viewportY: 0,
        length: 1000,
    };
    const scrolled: number[] = [];
    const term = {
        cols: 80,
        rows: 24,
        get buffer() {
            return { active: buffer };
        },
        registerMarker: (offset: number) => ({
            line: (buffer.baseY as number) + (buffer.cursorY as number) + offset,
            isDisposed: false,
            dispose: () => {},
        }),
        scrollToLine: (line: number) => scrolled.push(line),
    };
    const scan: PromptScanApi = {
        scan: () => prompts.map((p) => ({ ...p })),
        layoutTicks: () => [],
        currentOrdinalFor: () => 0,
    };
    const rail = new RailModel({
        term: () => term,
        promptScan: () => scan,
        isRule: () => undefined,
    });

    return { rail, buffer, scrolled };
}

function mountHeader(prompts: ScannedPrompt[]): Harness {
    const { rail, buffer, scrolled } = fakeRail(prompts);
    let focused = 0;
    const target = document.createElement('div');
    document.body.appendChild(target);
    const instance = mount(PromptHeader, {
        target,
        props: {
            rail,
            onfocusterm: () => {
                focused += 1;
            },
        },
    });
    flushSync();

    const strip = (): HTMLElement =>
        target.querySelector('.prompt-header-root') as HTMLElement;

    return {
        rail,
        scrolled,
        focused: () => focused,
        scrollTo: (y) => {
            buffer.viewportY = y;
            rail.setViewport(y);
            flushSync();
        },
        setBaseY: (y) => {
            buffer.baseY = y;
            rail.refresh();
            flushSync();
        },
        strip,
        button: (name) => {
            const el = target.querySelector(`.prompt-header__${name}, [data-prompt-key="${name}"]`);
            if (!el) throw new Error(`no .prompt-header__${name} or [data-prompt-key="${name}"] in the strip`);
            return el as HTMLButtonElement;
        },
        maybe: (name) =>
            target.querySelector(`.prompt-header__${name}, [data-prompt-key="${name}"]`) as HTMLButtonElement | null,
        destroy: () => {
            unmount(instance, { outro: false });
            rail.dispose();
            target.remove();
            live = null;
        },
    };
}

export const THREE = [
    scannedPrompt(1, 10, ['run the tests']),
    scannedPrompt(2, 60, ['first line', 'second line']),
    scannedPrompt(3, 120, ['ship it']),
];

let live: Harness | null = null;

export function mounted(prompts: ScannedPrompt[] = THREE): Harness {
    const h = mountHeader(prompts);
    live = h;
    return h;
}

export function beforeEachHeader(): void {
    metrics.scrollWidth = 0;
    metrics.clientWidth = 0;
    observers = [];
    installMeasurement();
}

export function afterEachHeader(): void {
    live?.destroy();
    live = null;
    document.body.innerHTML = '';
    for (const name of ['scrollWidth', 'clientWidth'] as const) {
        delete (window.HTMLElement.prototype as unknown as Record<string, unknown>)[name];
    }
    delete (window as unknown as Record<string, unknown>).ResizeObserver;
}
