export function tabName(tab: string, root: ParentNode | undefined = typeof document === 'undefined' ? undefined : document): string {
  const el = root ? [...root.querySelectorAll<HTMLElement>('[data-tab]')].find((e) => e.dataset['tab'] === tab) : undefined;
  return el?.querySelector('.oc-tab-name')?.textContent?.trim() || tab;
}
