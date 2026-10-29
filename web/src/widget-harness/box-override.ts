
export const MAX_OVERRIDE_PX = 4000;

export function boxOverride(params: URLSearchParams): { w?: number; h?: number } | null {
  const read = (name: string): number | undefined => {
    const raw = params.get(name);
    const value = raw !== null && /^\d{1,4}$/.test(raw) ? Number(raw) : NaN;
    return value >= 1 && value <= MAX_OVERRIDE_PX ? value : undefined;
  };
  const w = read('w');
  const h = read('h');
  return w === undefined && h === undefined ? null : { ...(w === undefined ? {} : { w }), ...(h === undefined ? {} : { h }) };
}
