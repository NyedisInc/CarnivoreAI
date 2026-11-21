import { flushSync } from 'svelte';

const popoverProto = HTMLElement.prototype as unknown as Record<string, unknown>;
popoverProto.showPopover ??= function () {};
popoverProto.hidePopover ??= function () {};

const RIGHT_CLICK = ['context', 'menu'].join('');

export function openRowMenu(host: HTMLElement, id: number): void {
  host.querySelector(`[data-huddle-item="${id}"]`)!.dispatchEvent(new MouseEvent(RIGHT_CLICK, { bubbles: true, cancelable: true, clientX: 40, clientY: 10 }));
  flushSync();
}

export function openRowMenuByKey(host: HTMLElement, id: number): void {
  host.querySelector(`[data-huddle-item="${id}"]`)!.dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true }));
  flushSync();
}

export function menuNode(id: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`#item-menu-host [data-node="${id}"]`);
}

export function menuNodeIds(): string[] {
  return [...document.querySelectorAll('#item-menu-host [data-node]')].map((n) => n.getAttribute('data-node') ?? '');
}
