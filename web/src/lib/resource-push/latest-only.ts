
export interface LatestOnly {
  begin(): () => boolean;
  invalidate(): void;
}

export function latestOnly(): LatestOnly {
  let generation = 0;
  return {
    begin() {
      const mine = ++generation;
      return () => mine === generation;
    },
    invalidate() {
      generation += 1;
    },
  };
}
