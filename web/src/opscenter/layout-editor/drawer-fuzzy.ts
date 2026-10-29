
export interface FuzzyMatch {
  score: number;
  indices: number[];
}

export interface TextPart {
  text: string;
  hit: boolean;
}

const BONUS_ADJACENT = 8;
const BONUS_WORD_START = 6;
const BONUS_FIRST_LETTER = 4;
const PENALTY_GAP = 1;
const PENALTY_LENGTH = 0.1;

function startsWord(text: string, at: number): boolean {
  if (at === 0) return true;
  return /[\s\-_./]/.test(text.charAt(at - 1));
}

export function fuzzyMatch(query: string, text: string): FuzzyMatch | null {
  const q = query.replace(/\s+/g, '').toLowerCase();
  const hay = text.toLowerCase();
  if (q.length === 0 || q.length > hay.length) return null;
  const n = q.length;
  const m = hay.length;
  const best: number[][] = Array.from({ length: n }, () => new Array<number>(m).fill(-Infinity));
  const from: number[][] = Array.from({ length: n }, () => new Array<number>(m).fill(-1));
  for (let i = 0; i < n; i++) {
    for (let j = i; j < m; j++) {
      if (hay.charAt(j) !== q.charAt(i)) continue;
      const own = (startsWord(hay, j) ? BONUS_WORD_START : 0) + (j === 0 ? BONUS_FIRST_LETTER : 0);
      if (i === 0) {
        best[0]![j] = own - j * PENALTY_GAP;
        continue;
      }
      for (let k = i - 1; k < j; k++) {
        const prior = best[i - 1]![k]!;
        if (prior === -Infinity) continue;
        const score = prior + own + (k === j - 1 ? BONUS_ADJACENT : -(j - k - 1) * PENALTY_GAP);
        if (score > best[i]![j]!) {
          best[i]![j] = score;
          from[i]![j] = k;
        }
      }
    }
  }
  let end = -1;
  let top = -Infinity;
  for (let j = 0; j < m; j++) {
    if (best[n - 1]![j]! > top) {
      top = best[n - 1]![j]!;
      end = j;
    }
  }
  if (end < 0) return null;
  const indices: number[] = new Array<number>(n);
  let at = end;
  for (let i = n - 1; i >= 0; i--) {
    indices[i] = at;
    at = from[i]![at]!;
  }
  return { score: top - (m - n) * PENALTY_LENGTH, indices };
}

export function highlightParts(text: string, indices: readonly number[]): TextPart[] {
  if (indices.length === 0) return text ? [{ text, hit: false }] : [];
  const hits = new Set(indices);
  const parts: TextPart[] = [];
  for (let at = 0; at < text.length; at++) {
    const hit = hits.has(at);
    const last = parts[parts.length - 1];
    if (last && last.hit === hit) last.text += text.charAt(at);
    else parts.push({ text: text.charAt(at), hit });
  }
  return parts;
}
