
export const MIN_FONT_PX = 7;

export const MAX_FONT_PX = 14;

export const DEFAULT_CHAR_WIDTH_RATIO = 0.6;

export interface FontFit {
    fontSize: number;
    scroll: boolean;
}

export function fitFontSize(stageWidth: number, cols: number, charWidthRatio: number): FontFit {
    if (!(stageWidth > 0) || !(cols > 0) || !(charWidthRatio > 0)) {
        return { fontSize: MAX_FONT_PX, scroll: true };
    }
    const ideal = Math.floor((stageWidth / (cols * charWidthRatio)) * 4) / 4;
    if (ideal < MIN_FONT_PX) return { fontSize: MIN_FONT_PX, scroll: true };
    return { fontSize: Math.min(MAX_FONT_PX, ideal), scroll: false };
}
