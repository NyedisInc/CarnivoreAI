/* the Task Manager */
import type { Component } from 'svelte';

/* the Task Manager */
export interface MarkdownKit {
  Block: Component<{ text: string; inline?: boolean }>;
  plain: (text: string) => string;
}

let kit: MarkdownKit | null = null;

export function registerMarkdown(next: MarkdownKit): void {
  kit = next;
}

/* the Task Manager */
export function markdownKit(): MarkdownKit | null {
  return kit;
}

export function markdownPlain(text: string): string {
  return kit ? kit.plain(text) : text;
}
