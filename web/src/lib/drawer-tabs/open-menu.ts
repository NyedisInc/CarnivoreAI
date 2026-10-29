
interface OpenMenu {
  close: () => void;
}

let current: OpenMenu | null = null;

export function claimOpenMenu(close: () => void): () => void {
  const mine: OpenMenu = { close };
  const previous = current;
  current = mine;
  previous?.close();
  return () => {
    if (current === mine) current = null;
  };
}

export function closeOpenMenu(): void {
  const held = current;
  current = null;
  held?.close();
}
