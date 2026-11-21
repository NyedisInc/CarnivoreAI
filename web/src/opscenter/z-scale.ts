/* the stacking scale */

export class ZScaleError extends Error {}

const RUNG = /^\s*(--oc-z-[a-z-]+)\s*:\s*([^;]+);/gm;
const VAR = /^var\((--oc-z-[a-z-]+)\)$/;
const TERM = /^([+-])\s*(var\(--oc-z-[a-z-]+\)|-?\d+)\s*/;

export function zRungs(tokensCss: string): Map<string, string> {
  const rungs = new Map<string, string>();
  for (const m of tokensCss.matchAll(RUNG)) rungs.set(m[1], m[2].trim());
  return rungs;
}

export function resolveZ(value: string, rungs: Map<string, string>, depth = 0): number {
  if (depth > 8) throw new ZScaleError(`z scale loops at ${value}`);
  const v = value.trim();
  if (/^-?\d+$/.test(v)) return Number(v);
  const one = VAR.exec(v);
  if (one) {
    const def = rungs.get(one[1]);
    if (def === undefined) throw new ZScaleError(`no rung ${one[1]}`);
    return resolveZ(def, rungs, depth + 1);
  }
  const calc = /^calc\((.*)\)$/.exec(v);
  if (!calc) throw new ZScaleError(`not a scale value: ${v}`);
  let rest = `+ ${calc[1].trim()}`;
  let total = 0;
  while (rest.length) {
    const term = TERM.exec(rest);
    if (!term) throw new ZScaleError(`cannot read ${rest} in ${v}`);
    const n = resolveZ(term[2], rungs, depth + 1);
    total += term[1] === '+' ? n : -n;
    rest = rest.slice(term[0].length);
  }
  return total;
}
