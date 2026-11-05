
export interface LocalFace {
    family: string;
    style: string;
}

export interface InstalledFamily {
    family: string;
    mono: boolean;
    weights: number[];
}

const WEIGHT_NUMBERS: Record<string, number> = { light: 300, normal: 400, medium: 500, bold: 700 };

export function weightNumber(name: string): number {
    return WEIGHT_NUMBERS[name] ?? 400;
}

export function faceWeights(faces: readonly LocalFace[]): number[] {
    const found = new Set<number>();
    for (const face of faces) {
        const style = face.style.toLowerCase();
        if (/italic|oblique/.test(style)) continue;
        if (/^(extra|ultra|semi|demi)/.test(style)) continue;
        if (/^light$/.test(style)) found.add(300);
        else if (/^(regular|book|normal|roman)$/.test(style)) found.add(400);
        else if (/^medium$/.test(style)) found.add(500);
        else if (/^bold$/.test(style)) found.add(700);
    }
    return [...found].sort((a, b) => a - b);
}

let probe: CanvasRenderingContext2D | null | undefined;

export function isMonospace(family: string): boolean {
    if (probe === undefined) probe = typeof document === 'undefined' ? null : document.createElement('canvas').getContext('2d');
    if (!probe) return false;
    probe.font = `16px "${family}", serif`;
    const narrow = probe.measureText('iiii').width;
    return narrow > 0 && narrow === probe.measureText('WWWW').width && narrow === probe.measureText('i.W-').width;
}
