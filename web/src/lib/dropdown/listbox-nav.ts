
export function nextOption(entries: readonly unknown[], from: number, step: 1 | -1, isOption: (index: number) => boolean): number {
    for (let i = from; i >= 0 && i < entries.length; i += step) if (isOption(i)) return i;
    return -1;
}

export function typeahead(labels: readonly string[], from: number, typed: string): number {
    const text = typed.toLowerCase();
    if (!text || labels.length === 0) return -1;
    const cycle = text.length > 1 && [...text].every((c) => c === text[0]);
    const needle = cycle ? text[0]! : text;
    const start = cycle || text.length === 1 ? from + 1 : Math.max(0, from);
    for (let n = 0; n < labels.length; n += 1) {
        const i = (start + n) % labels.length;
        if (labels[i]!.toLowerCase().startsWith(needle)) return i;
    }
    return -1;
}
