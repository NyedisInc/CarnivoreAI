
import type { RouteAnswer, RouteTable } from './types';

export function lookup(table: RouteTable, method: string, path: string): RouteAnswer | undefined {
  const exact = `${method} ${path}`;
  if (exact in table) return table[exact];
  let best: string | null = null;
  for (const key of Object.keys(table)) {
    if (!key.endsWith('*')) continue;
    const prefix = key.slice(0, -1);
    if (exact.startsWith(prefix) && (best === null || prefix.length > best.length - 1)) best = key;
  }
  return best === null ? undefined : table[best];
}

export function jsonResponse(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

export function answerResponse(answer: RouteAnswer, url: URL, init: RequestInit | undefined, method: string): Response {
  const body = typeof answer === 'function' ? (answer as (u: URL, i?: RequestInit) => unknown)(url, init) : answer;
  return jsonResponse(method === 'DELETE' ? 204 : 200, structuredClone(body));
}
