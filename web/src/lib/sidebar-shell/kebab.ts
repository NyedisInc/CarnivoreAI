
const KEBAB_SIZE = 14;
const KEBAB_RADIUS = 1.4;

export function kebabSvg(): string {
    const k = (globalThis as { KebabIcon?: { svg(size: number, weight: number): string } }).KebabIcon;
    return k ? k.svg(KEBAB_SIZE, KEBAB_RADIUS) : '';
}
