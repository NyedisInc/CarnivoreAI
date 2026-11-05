
export function scannable(src: string): string {
    let out = src
        .replace(/<!--[\s\S]*?-->/g, ' ')
        .replace(/\/\*[\s\S]*?\*\//g, ' ')
        .replace(/^[ \t]*\/\/.*$/gm, ' ')
        .replace(/\bclass=("[^"]*"|'[^']*')/g, 'class=""')
        .replace(/\b(\w*Class|btn\w*)=("[^"]*"|'[^']*')/g, '$1=""')
        .replace(/\brel=("[^"]*"|'[^']*')/g, 'rel=""')
        .replace(/setAttribute\(\s*(['"])rel\1\s*,\s*(['"])[^'"]*\2/g, "setAttribute('rel', ''")
        .replace(/\bgenerics=("[^"]*"|'[^']*')/g, 'generics=""');
    let index = out.indexOf('console.');
    while (index !== -1) {
        const open = out.indexOf('(', index);
        if (open === -1) break;
        let depth = 0;
        let i = open;
        for (; i < out.length; i++) {
            if (out[i] === '(') depth++;
            else if (out[i] === ')') {
                depth--;
                if (depth === 0) break;
            }
        }
        out = out.slice(0, index) + ' ' + out.slice(Math.min(i + 1, out.length));
        index = out.indexOf('console.', index);
    }
    return out;
}

export function stringLiterals(src: string): string[] {
    const found: string[] = [];
    const re = /'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(src)) !== null) {
        found.push(m[1] ?? m[2] ?? '');
    }
    return found;
}

export function looksLikeCopy(literal: string): boolean {
    if (literal.includes('.') && !literal.includes(' ')) return false;
    if (WIRE_LITERALS.has(literal)) return false;
    if (COMMAND_LITERALS.has(literal)) return false;
    if (LOG_LABELS.has(literal)) return false;
    return /[A-Za-z]{2,}\s+[A-Za-z]{2,}/.test(literal);
}

export const WIRE_LITERALS = new Set([
    'already exists',
    'already running',
    'not authenticated',
    'not found',
    'repo not found',
    'repository not found',
    'gh auth login',
    'gh cli not',
    'install with `brew install gh`',
    'timed out',
]);

export const COMMAND_LITERALS = new Set([
    'tmux -L cloude new -s mywork; claude',
    'tmux -L cloude new -s mywork "claude --dangerously-skip-permissions; exec $SHELL"',
    'tmux -L cloude new -s mywork \\"$SHELL -ic \'cld; exec $SHELL\'\\"',
]);

export const LOG_LABELS = new Set([
    'launcher rejoin',
    'deep-link resolve',
]);
