/* the widgets page */

export const GLYPHS: Readonly<Record<string, string>> = {
    overview: 'M2 2h4v4H2zM8 2h4v4H8zM2 8h4v4H2zM8 8h4v4H8z',
    sessions: 'M2 3h10M2 7h10M2 11h6',
    catalog: 'M2 4l5-2 5 2v6l-5 2-5-2zM2 4l5 2 5-2M7 6v6',
    monitoring: 'M1 8h3l2-5 2 8 2-5 1 2h2',
    tools: 'M2 4h6M10 4h2M2 10h2M6 10h6M8 2v4M4 8v4',
    live: 'M2 3h10v8H2zM6 5.5v3l3-1.5z',
    grid: 'M2 2h4v4H2zM8 2h4v4H8zM2 8h4v4H2zM8 8h4v4H8z',
};

export function glyphPath(name: string): string {
    return GLYPHS[name] ?? GLYPHS['grid']!;
}
