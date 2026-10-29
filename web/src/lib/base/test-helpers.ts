import { readFileSync } from 'node:fs';
import { flushSync, mount, unmount, type Component } from 'svelte';

import { cssRules, type CssRule } from './css-rules';

const mounted: Record<string, unknown>[] = [];

export function cleanup(): void {
    for (const m of mounted.splice(0)) unmount(m);
    document.body.innerHTML = '';
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function show(component: Component<any>, props: Record<string, unknown> = {}): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(component, { target, props }) as Record<string, unknown>);
    flushSync();
    return target;
}

export function press(el: Element, key: string, init: KeyboardEventInit = {}): KeyboardEvent {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
    el.dispatchEvent(event);
    flushSync();
    return event;
}

export function sheet(name: string): CssRule[] {
    return cssRules(readFileSync(`${process.cwd()}/src/lib/base/${name}`, 'utf8'));
}
