export function revealTabHorizontally(scroller: HTMLElement, button: HTMLElement): void {
  const strip = scroller.getBoundingClientRect();
  const tab = button.getBoundingClientRect();
  if (tab.left < strip.left) scroller.scrollLeft += tab.left - strip.left;
  else if (tab.right > strip.right) scroller.scrollLeft += tab.right - strip.right;
}
