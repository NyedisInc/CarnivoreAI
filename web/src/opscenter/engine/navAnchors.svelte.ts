
export const navAnchors: { components: HTMLElement | null; surface: HTMLElement | null } = $state({
  components: null,
  surface: null,
});

export function anchorRect(name: keyof typeof navAnchors): DOMRect | null {
  const element = navAnchors[name];
  if (!element || element.getClientRects().length === 0) return null;
  return element.getBoundingClientRect();
}
