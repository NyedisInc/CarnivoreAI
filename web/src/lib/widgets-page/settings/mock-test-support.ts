
export function stubResizeObserver(): void {
    const target = globalThis as { ResizeObserver?: unknown };
    if (target.ResizeObserver) return;
    target.ResizeObserver = class { observe(): void {} unobserve(): void {} disconnect(): void {} };
}
