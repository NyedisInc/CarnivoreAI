import { isAdvancedTabHash, isSessionsTabHash, parseEditId, parseFeedRun, parsePrefill, parseRunLink, parseSessionFocus, type SchedulePrefill } from './schedule-prefill';

export const PAGE_HASH = '#automations';

export type Route =
  | { kind: 'sessions' }
  | { kind: 'advanced' }
  | { kind: 'feed_run'; runId: string }
  | { kind: 'run'; runId: string }
  | { kind: 'session'; uuid: string }
  | { kind: 'edit'; id: string }
  | { kind: 'new'; prefill: SchedulePrefill };

export type RouteKind = Route['kind'];
type Handler<K extends RouteKind> = (route: Extract<Route, { kind: K }>) => void;

const ONE_SHOT: ReadonlySet<RouteKind> = new Set<RouteKind>(['sessions', 'advanced', 'session', 'edit', 'new']);

const handlers: { [K in RouteKind]?: Handler<K> } = {};

export function parseRoute(hash: string | null | undefined): Route | null {
  const feedRun = parseFeedRun(hash);
  if (feedRun) return { kind: 'feed_run', runId: feedRun };
  const run = parseRunLink(hash);
  if (run) return { kind: 'run', runId: run };
  const session = parseSessionFocus(hash);
  if (session) return { kind: 'session', uuid: session };
  const edit = parseEditId(hash);
  if (edit) return { kind: 'edit', id: edit };
  const prefill = parsePrefill(hash);
  if (prefill) return { kind: 'new', prefill };
  if (isAdvancedTabHash(hash)) return { kind: 'advanced' };
  return isSessionsTabHash(hash) ? { kind: 'sessions' } : null;
}

export function onRoute<K extends RouteKind>(kind: K, handler: Handler<K>): () => void {
  (handlers as Record<string, unknown>)[kind] = handler;
  return () => {
    if ((handlers as Record<string, unknown>)[kind] === handler) delete handlers[kind];
  };
}

export function setAddress(fragment: string): void {
  if (typeof location === 'undefined' || location.hash === fragment) return;
  history.replaceState(history.state, '', `${location.pathname}${location.search}${fragment}`);
}

export function takeRoute(): Route | null {
  const route = typeof location === 'undefined' ? null : parseRoute(location.hash);
  if (!route) return null;
  if (ONE_SHOT.has(route.kind)) setAddress(PAGE_HASH);
  (handlers[route.kind] as ((r: Route) => void) | undefined)?.(route);
  return route;
}

export function clearRunAddress(): void {
  if (typeof location !== 'undefined' && parseRunLink(location.hash)) setAddress(PAGE_HASH);
}

export function writeFeedRun(runId: string | null): void {
  if (typeof location === 'undefined') return;
  if (runId) setAddress(`${PAGE_HASH}/sessions/run/${runId}`);
  else if (parseFeedRun(location.hash)) setAddress(PAGE_HASH);
}
