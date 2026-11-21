
export function ancestorZoom(el: Element, style: (node: Element) => { zoom?: string } = (node) => getComputedStyle(node)): number {
  let factor = 1;
  for (let node = el.parentElement; node; node = node.parentElement) {
    const zoom = Number.parseFloat(style(node).zoom ?? '');
    if (Number.isFinite(zoom) && zoom > 0) factor *= zoom;
  }
  return factor;
}

export function counterZoom(factor: number): number | null {
  return factor === 1 || !Number.isFinite(factor) || factor <= 0 ? null : 1 / factor;
}
