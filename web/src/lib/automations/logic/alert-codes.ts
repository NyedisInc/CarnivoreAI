
export const MAX_ALERT_CODES = 8;

export function codesText(codes: unknown): string {
  return Array.isArray(codes) ? codes.join(', ') : '';
}

export function parseCodes(text: string): Array<number | string> {
  const tokens = text.split(/[\s,]+/).filter(Boolean);
  const read = tokens.map((token) => (/^\d+$/.test(token) ? Number(token) : token));
  return [...new Set(read)];
}

export function codesProblem(codes: unknown): '' | 'range' | 'count' {
  if (codes == null) return '';
  if (!Array.isArray(codes)) return 'range';
  if (codes.some((c) => typeof c !== 'number' || !Number.isInteger(c) || c < 1 || c > 255)) return 'range';
  return codes.length > MAX_ALERT_CODES ? 'count' : '';
}
