import type { LayoutSkill } from './api';

export type Sigil = '/' | '$';

export const MAX_ROWS = 50;

export function typing(text: string): { sigil: Sigil; query: string } | null {
  const hit = /^([/$])(\S*)$/.exec(text);
  return hit ? { sigil: hit[1] as Sigil, query: hit[2] ?? '' } : null;
}

export function filterSkills(all: LayoutSkill[], query: string): LayoutSkill[] {
  const q = query.toLowerCase();
  if (!q) return all.slice(0, MAX_ROWS);
  const rank = (s: LayoutSkill): number => {
    const name = s.name.toLowerCase();
    if (name.startsWith(q)) return 0;
    if (name.includes(q)) return 1;
    return s.description.toLowerCase().includes(q) ? 2 : 3;
  };
  return all.filter((s) => rank(s) < 3)
    .map((s, i) => ({ s, i, r: rank(s) }))
    .sort((a, b) => a.r - b.r || a.i - b.i)
    .map((one) => one.s)
    .slice(0, MAX_ROWS);
}

export function accepted(sigil: Sigil, skill: LayoutSkill): string {
  return `${sigil}${skill.name} `;
}
