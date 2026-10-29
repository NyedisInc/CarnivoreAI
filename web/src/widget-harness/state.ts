
export const harnessState = {
  ready: false,
  error: '',
  requests: 0,
  counts: {} as Record<string, number>,
  misses: [] as string[],
  asked: [] as string[],
};

(globalThis as { __widgetHarness?: unknown }).__widgetHarness = harnessState;
