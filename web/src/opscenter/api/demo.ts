
let cached: boolean | null = null;

export function isDemo(): boolean {
  if (cached !== null) return cached;
  try {
    cached = new URLSearchParams(globalThis.location?.search ?? '').get('demo') === '1';
  } catch {
    cached = false;
  }
  return cached;
}
