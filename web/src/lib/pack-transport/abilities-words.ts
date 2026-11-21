export const BASIC_TOOLS: readonly string[] = ['python3.12', 'python3', 'node', 'npm', 'git', 'gh', 'tmux', 'claude', 'brew'];

export interface Facts {
  os?: string | null;
  os_version?: string | null;
  chip?: string | null;
  arch?: string | null;
  cores?: number | null;
  mem_gb?: number | null;
  gpus?: ReadonlyArray<{ vendor?: string | null; model?: string | null; vram_gb?: number | null }>;
  xcode?: string | null;
  ios_sim?: boolean;
  tools?: Record<string, boolean>;
}

export function chipRows(f: Facts, t: (key: string, vars?: Record<string, string>) => string): { main: string[]; basic: string[] } {
  const main: string[] = [];
  if (f.os) main.push(f.os_version ? `${f.os} ${f.os_version}` : f.os);
  const chip = f.chip ?? f.arch;
  if (chip) main.push(chip);
  if (f.cores != null) main.push(t('pack.deck.cap.cores', { n: String(f.cores) }));
  if (f.mem_gb != null) main.push(t('pack.deck.cap.memory', { n: String(Math.round(f.mem_gb)) }));
  for (const g of f.gpus ?? []) if (g.model) main.push(t('pack.deck.cap.gpu', { model: g.model, vram: g.vram_gb != null ? ` ${Math.round(g.vram_gb)} gb` : '' }));
  if (f.xcode) main.push(t('pack.deck.cap.xcode', { v: f.xcode }));
  if (f.ios_sim) main.push(t('roster.can.ios_sim'));
  const have = Object.entries(f.tools ?? {}).filter(([, on]) => on).map(([tool]) => tool).sort();
  const word = (tool: string): string => { const k = `pack.machines.tool.${tool}`; const w = t(k); return w && w !== k ? w : tool; };
  for (const tool of have) if (!BASIC_TOOLS.includes(tool)) main.push(word(tool));
  return { main, basic: have.filter((tool) => BASIC_TOOLS.includes(tool)).map(word) };
}

const KEY_WORDS: readonly string[] = ['xcode', 'gpu:nvidia', 'blender', 'playwright', 'docker', 'ffmpeg'];

export function keyWords(f: Facts): string[] {
  const have = new Set<string>(Object.entries(f.tools ?? {}).filter(([, on]) => on).map(([tool]) => tool));
  if (f.xcode) have.add('xcode');
  if ((f.gpus ?? []).some((g) => g.vendor === 'nvidia')) have.add('gpu:nvidia');
  return KEY_WORDS.filter((k) => have.has(k)).slice(0, 3);
}
