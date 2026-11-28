import { ASCII_PUNCT, parseLinkDestination, parseLinkTitle, unescapeCommonMarkAndEntities } from './markdown-safe-tags';

export type MdInline =
    | { type: 'text'; text: string }
    | { type: 'strong'; children: MdInline[] }
    | { type: 'em'; children: MdInline[] }
    | { type: 'code'; text: string }
    | { type: 'break' }
    | { type: 'safe_link_text'; text: string };

export type MdBlock =
    | { type: 'heading'; level: 1 | 2 | 3 | 4 | 5 | 6; inlines: MdInline[] }
    | { type: 'paragraph'; inlines: MdInline[] }
    | { type: 'code_block'; language?: string; text: string }
    | { type: 'blockquote'; blocks: MdBlock[] }
    | { type: 'list'; ordered: boolean; start: number; items: MdBlock[][] }
    | { type: 'hr' };

const FENCE_RE = /^ {0,3}(`{3,}|~{3,})(.*)$/;
const HR_RE = /^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$/;
const ATX_RE = /^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$/;
const SETEXT_RE = /^ {0,3}(=+|-+)[ \t]*$/;
const LIST_RE = /^( {0,3})([-+*]|([0-9]{1,9})([.)]))(?:[ \t]+(.*)|$)$/;
const REF_DEF_RE = /^ {0,3}\[([^\]\n]+)\]:[ \t]*(.+)$/;
const WORD_CHAR_RE = /[A-Za-z0-9]/;
const MAX_PARSE_DEPTH = 16;

function isWordChar(ch: string | undefined): boolean {
    return ch !== undefined && WORD_CHAR_RE.test(ch);
}

function findMatchingBackticks(text: string, openPos: number, len: number): number {
    let i = openPos + len;
    while (i < text.length) {
        if (text[i] === '`') {
            let j = i;
            while (j < text.length && text[j] === '`') j += 1;
            if (j - i === len) return i;
            i = j;
        } else {
            i += 1;
        }
    }
    return -1;
}

function findClosingBracket(text: string, openPos: number): number {
    let depth = 1;
    let i = openPos + 1;
    while (i < text.length) {
        const ch = text[i]!;
        if (ch === '\\' && i + 1 < text.length) {
            i += 2;
            continue;
        }
        if (ch === '`') {
            let j = i;
            while (j < text.length && text[j] === '`') j += 1;
            const close = findMatchingBackticks(text, i, j - i);
            i = close !== -1 ? close + (j - i) : j;
            continue;
        }
        if (ch === '[') depth += 1;
        else if (ch === ']') {
            depth -= 1;
            if (depth === 0) return i;
        }
        i += 1;
    }
    return -1;
}

function tryConsumeInlineLinkTail(text: string, openParen: number): number {
    const n = text.length;
    let p = openParen + 1;
    while (p < n && (text[p] === ' ' || text[p] === '\t' || text[p] === '\n')) p += 1;
    if (p < n && text[p] === ')') return p + 1;
    const [okDest, destEnd] = parseLinkDestination(text, p, n, false);
    if (!okDest) return -1;
    p = destEnd;
    const wsStart = p;
    while (p < n && (text[p] === ' ' || text[p] === '\t' || text[p] === '\n')) p += 1;
    if (p > wsStart && p < n) {
        const [okTitle, titleEnd] = parseLinkTitle(text, p, n);
        if (okTitle) {
            p = titleEnd;
            while (p < n && (text[p] === ' ' || text[p] === '\t' || text[p] === '\n')) p += 1;
        }
    }
    return p < n && text[p] === ')' ? p + 1 : -1;
}

function findClosingEmphasis(text: string, start: number, marker: string): number {
    const mLen = marker.length;
    const singleChar = marker[0]!;
    let i = start;
    while (i < text.length) {
        const ch = text[i]!;
        if (ch === '\\' && i + 1 < text.length) {
            i += 2;
            continue;
        }
        if (ch === '`') {
            let j = i;
            while (j < text.length && text[j] === '`') j += 1;
            const close = findMatchingBackticks(text, i, j - i);
            i = close !== -1 ? close + (j - i) : j;
            continue;
        }
        if (ch === singleChar && text.startsWith(marker, i)) {
            const prev = i > 0 ? text[i - 1] : undefined;
            const next = i + mLen < text.length ? text[i + mLen] : undefined;
            if (prev !== ' ' && prev !== '\t' && prev !== '\n') {
                if (singleChar === '_' && isWordChar(prev) && isWordChar(next)) {
                    i += mLen;
                    continue;
                }
                return i;
            }
        }
        i += 1;
    }
    return -1;
}

function pushText(out: MdInline[], value: string): void {
    if (!value) return;
    const prev = out[out.length - 1];
    if (prev && prev.type === 'text') prev.text += value;
    else out.push({ type: 'text', text: value });
}

export function parseInlines(text: string, depth = 0): MdInline[] {
    if (!text) return [];
    if (depth >= MAX_PARSE_DEPTH) return [{ type: 'text', text: unescapeCommonMarkAndEntities(text) }];
    const out: MdInline[] = [];
    let buf = '';
    const flush = (): void => {
        if (buf) {
            pushText(out, unescapeCommonMarkAndEntities(buf));
            buf = '';
        }
    };

    let i = 0;
    const n = text.length;
    while (i < n) {
        const ch = text[i]!;
        if (ch === '\\' && i + 1 < n) {
            const nxt = text[i + 1]!;
            if (nxt === '\n') {
                flush();
                out.push({ type: 'break' });
                i += 2;
                continue;
            }
            if (ASCII_PUNCT.has(nxt)) {
                flush();
                pushText(out, nxt);
                i += 2;
                continue;
            }
        }
        if (ch === ' ' && i + 1 < n) {
            let j = i;
            while (j < n && text[j] === ' ') j += 1;
            if (j - i >= 2 && text[j] === '\n') {
                flush();
                out.push({ type: 'break' });
                i = j + 1;
                continue;
            }
        }
        if (ch === '\n') {
            buf += ' ';
            i += 1;
            continue;
        }
        if (ch === '`') {
            let j = i;
            while (j < n && text[j] === '`') j += 1;
            const len = j - i;
            const close = findMatchingBackticks(text, i, len);
            if (close !== -1) {
                flush();
                let code = text.slice(j, close).replace(/\n/g, ' ');
                if (code.length >= 2 && code.startsWith(' ') && code.endsWith(' ') && /[^ ]/.test(code)) {
                    code = code.slice(1, -1);
                }
                out.push({ type: 'code', text: code });
                i = close + len;
                continue;
            }
            buf += text.slice(i, j);
            i = j;
            continue;
        }
        if (ch === '!' && i + 1 < n && text[i + 1] === '[') {
            const closeBr = findClosingBracket(text, i + 1);
            if (closeBr !== -1) {
                const after = closeBr + 1;
                let linkEnd = -1;
                if (after < n && text[after] === '(') linkEnd = tryConsumeInlineLinkTail(text, after);
                else if (after < n && text[after] === '[') linkEnd = findClosingBracket(text, after) + 1 || -1;
                if (linkEnd > after) {
                    flush();
                    const alt = unescapeCommonMarkAndEntities(text.slice(i + 2, closeBr));
                    if (alt) out.push({ type: 'safe_link_text', text: alt });
                    i = linkEnd;
                    continue;
                }
            }
        }
        if (ch === '[') {
            const closeBr = findClosingBracket(text, i);
            if (closeBr !== -1) {
                const after = closeBr + 1;
                let linkEnd = -1;
                if (after < n && text[after] === '(') linkEnd = tryConsumeInlineLinkTail(text, after);
                else if (after < n && text[after] === '[') {
                    const refClose = findClosingBracket(text, after);
                    if (refClose !== -1) linkEnd = refClose + 1;
                }
                if (linkEnd > after) {
                    flush();
                    out.push({ type: 'safe_link_text', text: unescapeCommonMarkAndEntities(text.slice(i + 1, closeBr)) });
                    i = linkEnd;
                    continue;
                }
            }
        }
        if ((ch === '*' || ch === '_') && i + 1 < n) {
            const dbl = text[i + 1] === ch;
            const marker = dbl ? ch + ch : ch;
            const prev = i > 0 ? text[i - 1] : undefined;
            const afterOpen = text[i + marker.length];
            const canOpen =
                afterOpen !== undefined &&
                afterOpen !== ' ' &&
                afterOpen !== '\t' &&
                afterOpen !== '\n' &&
                !(ch === '_' && isWordChar(prev) && isWordChar(afterOpen));
            if (canOpen) {
                const closePos = findClosingEmphasis(text, i + marker.length, marker);
                if (closePos > i + marker.length) {
                    flush();
                    const children = parseInlines(text.slice(i + marker.length, closePos), depth + 1);
                    out.push(dbl ? { type: 'strong', children } : { type: 'em', children });
                    i = closePos + marker.length;
                    continue;
                }
            }
        }
        buf += ch;
        i += 1;
    }
    flush();
    return out;
}

function stripAtxTrailing(raw: string): string {
    const trimmed = raw.trimEnd();
    if (/^#+$/.test(trimmed)) return '';
    const m = /^(.+?)[ \t]+#+$/.exec(trimmed);
    return m ? m[1]! : trimmed;
}

function isBlockStart(line: string): boolean {
    return (
        ATX_RE.test(line) ||
        FENCE_RE.test(line) ||
        HR_RE.test(line) ||
        /^ {0,3}>/.test(line) ||
        LIST_RE.test(line)
    );
}

function parseBlocks(lines: string[], depth = 0): MdBlock[] {
    if (depth >= MAX_PARSE_DEPTH) {
        const joined = lines.join('\n').trim();
        return joined ? [{ type: 'paragraph', inlines: parseInlines(joined, depth) }] : [];
    }
    const blocks: MdBlock[] = [];
    let i = 0;
    const n = lines.length;

    while (i < n) {
        const line = lines[i]!;
        if (/^[ \t]*$/.test(line)) {
            i += 1;
            continue;
        }

        const fence = FENCE_RE.exec(line);
        if (fence && (fence[1]![0] === '~' || !(fence[2] ?? '').includes('`'))) {
            const fChar = fence[1]![0]!;
            const fLen = fence[1]!.length;
            const info = unescapeCommonMarkAndEntities((fence[2] ?? '').trim().split(/\s+/)[0] ?? '');
            const indent = line.length - line.replace(/^ {0,3}/, '').length;
            const body: string[] = [];
            i += 1;
            while (i < n) {
                const cur = lines[i]!;
                const close = /^ {0,3}(`{3,}|~{3,})[ \t]*$/.exec(cur);
                if (close && close[1]![0] === fChar && close[1]!.length >= fLen) {
                    i += 1;
                    break;
                }
                body.push(indent > 0 ? cur.replace(new RegExp(`^ {1,${indent}}`), '') : cur);
                i += 1;
            }
            blocks.push({ type: 'code_block', ...(info ? { language: info } : {}), text: body.join('\n') });
            continue;
        }

        if (HR_RE.test(line)) {
            blocks.push({ type: 'hr' });
            i += 1;
            continue;
        }

        const atx = ATX_RE.exec(line);
        if (atx) {
            const level = atx[1]!.length as 1 | 2 | 3 | 4 | 5 | 6;
            const content = stripAtxTrailing(atx[2] ?? '');
            blocks.push({ type: 'heading', level, inlines: parseInlines(content) });
            i += 1;
            continue;
        }

        if (/^ {0,3}>/.test(line)) {
            const qLines: string[] = [];
            while (i < n) {
                const cur = lines[i]!;
                if (/^ {0,3}>/.test(cur)) {
                    qLines.push(cur.replace(/^ {0,3}> ?/, ''));
                    i += 1;
                } else if (!/^[ \t]*$/.test(cur) && !isBlockStart(cur) && qLines.length > 0 && !/^[ \t]*$/.test(qLines[qLines.length - 1]!)) {
                    qLines.push(cur.replace(/^ {0,3}/, ''));
                    i += 1;
                } else {
                    break;
                }
            }
            blocks.push({ type: 'blockquote', blocks: parseBlocks(qLines, depth + 1) });
            continue;
        }

        if (/^(?: {4}|\t)/.test(line)) {
            const codeLines: string[] = [];
            while (i < n) {
                const cur = lines[i]!;
                if (/^(?: {4}|\t)/.test(cur)) {
                    codeLines.push(cur.replace(/^(?: {4}|\t)/, ''));
                    i += 1;
                } else if (/^[ \t]*$/.test(cur)) {
                    let k = i + 1;
                    while (k < n && /^[ \t]*$/.test(lines[k]!)) k += 1;
                    if (k < n && /^(?: {4}|\t)/.test(lines[k]!)) {
                        while (i < k) {
                            codeLines.push('');
                            i += 1;
                        }
                    } else {
                        break;
                    }
                } else {
                    break;
                }
            }
            blocks.push({ type: 'code_block', text: codeLines.join('\n') });
            continue;
        }

        const firstLi = LIST_RE.exec(line);
        if (firstLi) {
            const ordered = firstLi[3] !== undefined;
            const start = ordered ? Number.parseInt(firstLi[3]!, 10) : 1;
            const delim = ordered ? firstLi[4]! : firstLi[2]!;
            const items: MdBlock[][] = [];
            while (i < n) {
                const li = LIST_RE.exec(lines[i]!);
                if (!li) break;
                const liOrdered = li[3] !== undefined;
                const liDelim = liOrdered ? li[4]! : li[2]!;
                if (liOrdered !== ordered || (ordered ? liDelim !== delim : !'-+*'.includes(liDelim))) break;
                const markerIndent = li[1]!.length + li[2]!.length + 1;
                const itemLines: string[] = [li[5] ?? ''];
                i += 1;
                while (i < n) {
                    const nxt = lines[i]!;
                    if (/^[ \t]*$/.test(nxt)) {
                        let k = i + 1;
                        while (k < n && /^[ \t]*$/.test(lines[k]!)) k += 1;
                        if (k < n && (new RegExp(`^ {${markerIndent},}`).test(lines[k]!) || LIST_RE.test(lines[k]!))) {
                            if (LIST_RE.test(lines[k]!) && !new RegExp(`^ {${markerIndent},}`).test(lines[k]!)) {
                                i = k;
                                break;
                            }
                            while (i < k) {
                                itemLines.push('');
                                i += 1;
                            }
                            continue;
                        }
                        break;
                    }
                    if (LIST_RE.test(nxt) && !new RegExp(`^ {${markerIndent},}`).test(nxt)) break;
                    if (HR_RE.test(nxt) || ATX_RE.test(nxt) || FENCE_RE.test(nxt)) break;
                    if (new RegExp(`^ {${markerIndent},}`).test(nxt)) {
                        itemLines.push(nxt.slice(markerIndent));
                        i += 1;
                    } else if (!isBlockStart(nxt)) {
                        itemLines.push(nxt.replace(/^ {0,3}/, ''));
                        i += 1;
                    } else {
                        break;
                    }
                }
                items.push(parseBlocks(itemLines, depth + 1));
            }
            blocks.push({ type: 'list', ordered, start, items });
            continue;
        }

        if (REF_DEF_RE.test(line)) {
            i += 1;
            continue;
        }

        const paraLines: string[] = [line.replace(/^ {0,3}/, '')];
        i += 1;
        let setextLevel: 1 | 2 | null = null;
        while (i < n) {
            const nxt = lines[i]!;
            if (/^[ \t]*$/.test(nxt)) break;
            const setext = SETEXT_RE.exec(nxt);
            if (setext) {
                setextLevel = setext[1]![0] === '=' ? 1 : 2;
                i += 1;
                break;
            }
            if (isBlockStart(nxt)) break;
            paraLines.push(nxt.replace(/^ {0,3}/, ''));
            i += 1;
        }
        const joined = paraLines.join('\n');
        if (setextLevel !== null) {
            blocks.push({ type: 'heading', level: setextLevel, inlines: parseInlines(joined) });
        } else {
            blocks.push({ type: 'paragraph', inlines: parseInlines(joined) });
        }
    }

    return blocks;
}

export function parseMarkdownSafeAst(text: string): MdBlock[] {
    if (!text) return [];
    const normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    return parseBlocks(normalized.split('\n'));
}
