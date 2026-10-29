/* the detail pane */

export const FOCUS_TTL_MS = 10000;

export interface FocusRequest {
  id: number;
  archived: boolean;
  at: number;
}

export const boardFocus = $state<{ request: FocusRequest | null }>({ request: null });

export function isFresh(request: FocusRequest | null, now: number = Date.now()): request is FocusRequest {
  return request !== null && now - request.at < FOCUS_TTL_MS;
}
