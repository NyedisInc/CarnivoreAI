
export interface CharacterPack {
  id: string;
  pixel: boolean;
}

export const DEFAULT_PACK: CharacterPack = { id: 'default', pixel: false };

export const PIXEL_PACK: CharacterPack = { id: 'pixel', pixel: true };

export const BUILTIN_PACKS: Readonly<Record<string, CharacterPack>> = { default: DEFAULT_PACK, pixel: PIXEL_PACK };

function named(name: unknown): CharacterPack | null {
  return typeof name === 'string' && Object.prototype.hasOwnProperty.call(BUILTIN_PACKS, name) ? BUILTIN_PACKS[name]! : null;
}

export function readCharacterPack(block: unknown, override?: string | null): CharacterPack {
  const forced = named(override);
  if (forced) return forced;
  const fromTheme = block && typeof block === 'object' ? named((block as { pack?: unknown }).pack) : null;
  return fromTheme ?? DEFAULT_PACK;
}
