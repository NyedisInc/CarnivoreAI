
export const FUZZY_SPAN = 2;

export const FUZZY_MIN_LETTERS = 3;

export function wordMatches(word: string, text: string): boolean {
  if (text.includes(word)) return true;
  if (word.length < FUZZY_MIN_LETTERS) return false;
  const limit = word.length * FUZZY_SPAN;
  for (let start = text.indexOf(word[0] as string); start !== -1; start = text.indexOf(word[0] as string, start + 1)) {
    let at = start;
    let matched = 1;
    while (matched < word.length) {
      at = text.indexOf(word[matched] as string, at + 1);
      if (at === -1 || at - start + 1 > limit) break;
      matched += 1;
    }
    if (matched === word.length) return true;
  }
  return false;
}

export function fuzzyMatch(query: string, text: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = text.toLowerCase();
  return words.every((word) => wordMatches(word, haystack));
}
