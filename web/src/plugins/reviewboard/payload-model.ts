import type { BoardRevision, BoardSave, PayloadDraft } from './board-model';

export const MAX_PAYLOAD_BYTES = 64 * 1024;
export const MAX_PAYLOAD_DEPTH = 32;
export type Payload = Record<string, unknown>;

function depthOf(value: unknown): number {
  let deepest = 0;
  const stack: Array<[unknown, number]> = [[value, 0]];
  while (stack.length > 0) {
    const [node, depth] = stack.pop()!;
    if (node !== null && typeof node === 'object') {
      deepest = Math.max(deepest, depth + 1);
      for (const child of Array.isArray(node) ? node : Object.values(node as Record<string, unknown>)) stack.push([child, depth + 1]);
    }
  }
  return deepest;
}

export function validatePayload(value: unknown): Payload | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null;
  let text: string | undefined;
  try {
    text = JSON.stringify(value);
  } catch {
    return null;
  }
  if (text === undefined || new TextEncoder().encode(text).length > MAX_PAYLOAD_BYTES) return null;
  const plain: unknown = JSON.parse(text);
  if (plain === null || typeof plain !== 'object' || Array.isArray(plain)) return null;
  return depthOf(plain) > MAX_PAYLOAD_DEPTH ? null : (plain as Payload);
}

export function stableJson(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? 'null';
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record).sort().map((k) => `${JSON.stringify(k)}:${stableJson(record[k])}`).join(',')}}`;
}

export function samePayload(a: Payload | null, b: Payload | null): boolean {
  return a !== null && b !== null && stableJson(a) === stableJson(b);
}

export function savesOf(revision: BoardRevision | null): BoardSave[] {
  return revision?.saves ?? [];
}

export function stepSave(saves: readonly BoardSave[], current: number | null, delta: number): number | null {
  if (saves.length === 0) return null;
  const at = current === null ? saves.length + 1 : saves.findIndex((s) => s.n === current) + 1;
  if (at <= 0) return saves.at(-1)!.n;
  const next = at + delta;
  return next > saves.length ? null : saves[Math.max(1, next) - 1]!.n;
}

export function draftOf(revision: BoardRevision | null): PayloadDraft | null {
  return revision?.draft ?? null;
}
