export type VisibilityObserverCtor = new (callback: IntersectionObserverCallback, options?: IntersectionObserverInit) => IntersectionObserver;

export function visibilityObserver(): VisibilityObserverCtor | undefined {
  return (globalThis as { VisibilityObserver?: VisibilityObserverCtor }).VisibilityObserver;
}
