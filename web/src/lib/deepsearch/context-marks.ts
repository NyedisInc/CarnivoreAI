import { snippetParts } from '../conversation-snippet/snippet-parts';

export interface MarkPiece {
  text: string;
  match: boolean;
}

const MAX_TERMS = 8;

export function hitTerms(snippet: string): string[] {
  const words = snippetParts(snippet).filter((p) => p.match).map((p) => p.text.trim().toLowerCase()).filter(Boolean);
  return [...new Set(words)].slice(0, MAX_TERMS);
}

export function markPieces(text: string, terms: string[]): MarkPiece[] {
  if (terms.length === 0 || text === '') return [{ text, match: false }];
  const pattern = terms.slice().sort((a, b) => b.length - a.length).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  const pieces: MarkPiece[] = [];
  let last = 0;
  for (const m of text.matchAll(new RegExp(pattern, 'gi'))) {
    if (m[0] === '') continue;
    if (m.index > last) pieces.push({ text: text.slice(last, m.index), match: false });
    pieces.push({ text: m[0], match: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) pieces.push({ text: text.slice(last), match: false });
  return pieces.length > 0 ? pieces : [{ text, match: false }];
}

export function landingTop(boxHeight: number, hitTop: number, hitHeight: number, markTop: number | null, markHeight: number): number {
  const centered = (top: number, height: number): number => Math.max(0, top - (boxHeight - height) / 2);
  if (hitHeight <= boxHeight) return centered(hitTop, hitHeight);
  return markTop === null ? Math.max(0, hitTop) : centered(markTop, markHeight);
}
