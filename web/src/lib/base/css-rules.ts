
export interface CssRule {
    selector: string;
    decls: Record<string, string>;
    within: string[];
}

export function cssRules(css: string): CssRule[] {
    const src = css.replace(/\/\*[\s\S]*?\*\//g, '');
    const rules: CssRule[] = [];
    const within: string[] = [];
    let start = 0;
    for (let i = 0; i < src.length; i++) {
        const ch = src[i];
        if (ch === '{') {
            const prelude = src.slice(start, i).trim();
            if (prelude.startsWith('@')) {
                within.push(prelude);
                start = i + 1;
                continue;
            }
            const close = src.indexOf('}', i);
            const decls: Record<string, string> = {};
            for (const part of src.slice(i + 1, close).split(';')) {
                const at = part.indexOf(':');
                if (at > 0) decls[part.slice(0, at).trim()] = part.slice(at + 1).trim();
            }
            rules.push({ selector: prelude.replace(/\s+/g, ' '), decls, within: [...within] });
            i = close;
            start = close + 1;
        } else if (ch === '}') {
            within.pop();
            start = i + 1;
        } else if (ch === ';' && src.slice(start, i).trim().startsWith('@')) {
            start = i + 1;
        }
    }
    return rules;
}
