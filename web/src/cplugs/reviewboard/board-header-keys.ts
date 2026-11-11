import type { Component } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';

export interface BoardHeaderKeyProps {
  slug: string;
}

export interface BoardHeaderKey {
  id: string;
  component: Component<BoardHeaderKeyProps>;
  enabled: () => boolean;
}

const keys = new SvelteMap<string, BoardHeaderKey>();

export function registerBoardHeaderKey(key: BoardHeaderKey): void {
  keys.set(key.id, key);
}

export function boardHeaderKeys(): BoardHeaderKey[] {
  return [...keys.values()].filter((key) => key.enabled());
}

export function resetBoardHeaderKeys(): void {
  keys.clear();
}
