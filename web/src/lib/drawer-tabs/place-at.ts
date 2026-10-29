/* position: fixed */
export function placeAt(node: HTMLElement, at: { x: number; y: number }): void {
  node.style.left = `${at.x}px`;
  node.style.top = `${at.y}px`;
  const box = node.getBoundingClientRect();
  node.style.left = `${at.x - (box.left - at.x)}px`;
  node.style.top = `${at.y - (box.top - at.y)}px`;
}
