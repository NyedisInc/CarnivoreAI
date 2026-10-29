
export const REFUSAL_SHOW_MS = 6000;

export const placementRefusal = $state({ line: '' });

let timer: ReturnType<typeof setTimeout> | undefined;

export function refusePlacement(line: string): void {
  if (timer !== undefined) clearTimeout(timer);
  placementRefusal.line = line;
  timer = line ? setTimeout(dismissRefusal, REFUSAL_SHOW_MS) : undefined;
}

export function dismissRefusal(): void {
  if (timer !== undefined) clearTimeout(timer);
  timer = undefined;
  placementRefusal.line = '';
}
