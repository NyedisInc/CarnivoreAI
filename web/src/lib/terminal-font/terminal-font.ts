
export interface TerminalFontState {
    size: number;
    family: string;
}

export interface TerminalFontApi {
    MIN_SIZE: number;
    MAX_SIZE: number;
    DEFAULT_SIZE: number;
    size(): number;
    family(): string;
    familyStack(picked: string, base?: string): string;
    sanitizeFamily(value: unknown): string;
    setSize(value: number): number;
    step(delta: number): number;
    reset(): number;
    setFamily(value: string): Promise<boolean>;
    onChange(fn: (state: TerminalFontState) => void): () => void;
}

export function terminalFont(): TerminalFontApi | null {
    return (globalThis as { TerminalFont?: TerminalFontApi }).TerminalFont ?? null;
}

export function stepTerminalFont(delta: number): boolean {
    const font = terminalFont();
    if (!font) return false;
    if (delta === 0) font.reset();
    else font.step(delta);
    return true;
}
