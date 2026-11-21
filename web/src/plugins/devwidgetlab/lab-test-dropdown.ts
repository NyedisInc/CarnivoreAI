import { flushSync } from 'svelte';


export function pickOption(root: ParentNode, key: string, id: string): void {
  const host = root.querySelector<HTMLElement>(`[data-choice="${key}"]`);
  if (!host) throw new Error(`no dropdown ${key}`);
  if (!host.querySelector('[data-choice-list]')) {
    host.querySelector<HTMLElement>('[data-choice-trigger]')!.click();
    flushSync();
  }
  const option = host.querySelector<HTMLElement>(`[data-choice-option="${id}"]`);
  if (!option) throw new Error(`no row ${id} in ${key}`);
  option.click();
}
