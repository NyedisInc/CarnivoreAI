import rawEntities from './html5-entities.json';

const HTML5_ENTITIES: Readonly<Record<string, string>> = rawEntities;
export const ASCII_PUNCT = new Set('!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~');
const CM_UNESCAPE_RE =
    /\\([!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~])|&#[xX]([0-9a-fA-F]{1,6});|&#([0-9]{1,7});|&([A-Za-z][A-Za-z0-9]{1,31});/g;
const REF_WS_RE =
    /[\x00-\x20\x7f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+/g;
const REF_WS_SINGLE_RE =
    /[\x00-\x20\x7f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]/;

const ATTR_WS = '[ \\t\\r\\n\\f\\v\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]';
const ATTR_NAME = '[a-zA-Z_:][a-zA-Z0-9:._-]*';
const UNQUOTED = '[^"\'=<>`\\x00-\\x20\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]+';
const SINGLE_QUOTED = "'[^']*'";
const DOUBLE_QUOTED = '"[^"]*"';
const ATTR_VALUE = `(?:${UNQUOTED}|${SINGLE_QUOTED}|${DOUBLE_QUOTED})`;
const ATTRIBUTE = `(?:${ATTR_WS}+${ATTR_NAME}(?:${ATTR_WS}*=${ATTR_WS}*${ATTR_VALUE})?)`;
const OPEN_TAG = `<[A-Za-z][A-Za-z0-9\\-]*${ATTRIBUTE}*${ATTR_WS}*/?>`;
const CLOSE_TAG = `</[A-Za-z][A-Za-z0-9\\-]*${ATTR_WS}*>`;
const COMMENT = '<!---?>|<!--(?:[^-]|-[^-]|--[^>])*-->';
const PROCESSING = '<\\?[\\s\\S]*?\\?>';
const DECLARATION = '<![A-Za-z][^>]*>';
const CDATA = '<!\\[CDATA\\[[\\s\\S]*?\\]\\]>';

export const HTML_TAG_RE = new RegExp(
    `(?:${OPEN_TAG}|${CLOSE_TAG}|${COMMENT}|${PROCESSING}|${DECLARATION}|${CDATA})`,
    'y',
);
export const HTML_OPEN_CLOSE_LINE_RE = new RegExp(`^ {0,3}(?:${OPEN_TAG}|${CLOSE_TAG})${ATTR_WS}*$`);

const ATTR_WS_CHARS = new Set(
    ' \t\r\n\f\v\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000',
);
const UNQUOTED_FORBIDDEN = new Set('"\'=<>`');

const B_END_NO_WS = 1 << 0;
const B_READY_WS = 1 << 1;
const B_SLASH = 1 << 2;
const B_IN_NAME = 1 << 3;
const B_AFTER_NAME_WS = 1 << 4;
const B_AFTER_EQ_WS = 1 << 5;
const B_IN_UNQUOTED = 1 << 6;
const B_IN_SQUOTE = 1 << 7;
const B_IN_DQUOTE = 1 << 8;

const AUTOLINK_URI_RE = /^[A-Za-z][A-Za-z0-9+.\-]{1,31}:[^\x00-\x20<>]*$/;
const AUTOLINK_EMAIL_RE =
    /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/;
const BAD_AUTOLINK_PROTO_RE = /^(?:vbscript|javascript|file|data):/i;
const GOOD_AUTOLINK_DATA_RE = /^data:image\/(?:gif|png|jpeg|webp);/i;

export type CommentIndex = {
    genDStarts: number[];
    genEnds: number[];
    localEnds: Map<number, number>;
};

export function isMdValidAutolinkUrl(url: string): boolean {
    const u = url.trim();
    if (BAD_AUTOLINK_PROTO_RE.test(u)) return GOOD_AUTOLINK_DATA_RE.test(u);
    return true;
}

export function unescapeCommonMarkAndEntities(text: string): string {
    CM_UNESCAPE_RE.lastIndex = 0;
    return text.replace(
        CM_UNESCAPE_RE,
        (
            full: string,
            punct: string | undefined,
            hexDigits: string | undefined,
            decDigits: string | undefined,
            named: string | undefined,
        ) => {
            if (punct !== undefined) return punct;
            if (hexDigits !== undefined) {
                const cp = Number.parseInt(hexDigits, 16);
                return cp === 0 || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)
                    ? '\ufffd'
                    : String.fromCodePoint(cp);
            }
            if (decDigits !== undefined) {
                const cp = Number.parseInt(decDigits, 10);
                return cp === 0 || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)
                    ? '\ufffd'
                    : String.fromCodePoint(cp);
            }
            if (named !== undefined && Object.hasOwn(HTML5_ENTITIES, named)) {
                return HTML5_ENTITIES[named]!;
            }
            return full;
        },
    );
}

export function normalizeReferenceLabel(label: string): string {
    let start = 0;
    let end = label.length;
    while (start < end && REF_WS_SINGLE_RE.test(label[start]!)) start += 1;
    while (end > start && REF_WS_SINGLE_RE.test(label[end - 1]!)) end -= 1;
    return label.slice(start, end).replace(REF_WS_RE, ' ').toLowerCase().toUpperCase();
}

export function parseLinkDestination(
    text: string,
    pos: number,
    maximum: number,
    stopBeforeCtrl = true,
): [boolean, number, string] {
    const start = pos;
    if (pos >= maximum) return [false, pos, ''];

    if (text[pos] === '<') {
        pos += 1;
        while (pos < maximum) {
            const ch = text[pos]!;
            if (ch === '\n' || ch === '<') return [false, start, ''];
            if (ch === '>') {
                return [true, pos + 1, unescapeCommonMarkAndEntities(text.slice(start + 1, pos))];
            }
            if (ch === '\\' && pos + 1 < maximum) {
                if (stopBeforeCtrl && text.charCodeAt(pos + 1) === 0x0a) return [false, start, ''];
                pos += 2;
                continue;
            }
            pos += 1;
        }
        return [false, start, ''];
    }

    let level = 0;
    while (pos < maximum) {
        const code = text.charCodeAt(pos);
        if (code <= 0x20 || code === 0x7f) break;
        if (code === 0x5c && pos + 1 < maximum) {
            const nxt = text.charCodeAt(pos + 1);
            if (nxt === 0x20) break;
            if (stopBeforeCtrl && (nxt < 0x20 || nxt === 0x7f)) {
                pos += 1;
                break;
            }
            pos += 2;
            continue;
        }
        if (code === 0x28) {
            level += 1;
            if (level > 32) return [false, start, ''];
        } else if (code === 0x29) {
            if (level === 0) break;
            level -= 1;
        }
        pos += 1;
    }

    if (start === pos || level !== 0) return [false, start, ''];
    return [true, pos, unescapeCommonMarkAndEntities(text.slice(start, pos))];
}

export function parseLinkTitle(
    text: string,
    pos: number,
    maximum: number,
): [boolean, number, string] {
    if (pos >= maximum) return [false, pos, ''];
    const opener = text[pos]!;
    if (opener !== '"' && opener !== "'" && opener !== '(') return [false, pos, ''];
    const closer = opener === '(' ? ')' : opener;
    const start = pos + 1;
    pos = start;
    while (pos < maximum) {
        const ch = text[pos]!;
        if (ch === closer) {
            return [true, pos + 1, unescapeCommonMarkAndEntities(text.slice(start, pos))];
        }
        if (ch === '(' && closer === ')') return [false, start - 1, ''];
        if (ch === '\\' && pos + 1 < maximum) {
            pos += 2;
            continue;
        }
        pos += 1;
    }
    return [false, start - 1, ''];
}

export function tryAutolink(segment: string, pos: number, maximum: number): [string, number] | null {
    let k = pos + 1;
    while (k < maximum) {
        const ch = segment[k]!;
        if (ch === '<' || ch === '\n') return null;
        if (ch === '>') {
            const inner = segment.slice(pos + 1, k);
            if (AUTOLINK_URI_RE.test(inner)) return [inner, k + 1];
            if (AUTOLINK_EMAIL_RE.test(inner)) return [`mailto:${inner}`, k + 1];
            return null;
        }
        k += 1;
    }
    return null;
}

export function isAsciiAlpha(ch: string): boolean {
    const o = ch.charCodeAt(0);
    return (o >= 65 && o <= 90) || (o >= 97 && o <= 122);
}

function isTagNameCont(ch: string): boolean {
    const o = ch.charCodeAt(0);
    return (o >= 65 && o <= 90) || (o >= 97 && o <= 122) || (o >= 48 && o <= 57) || o === 45;
}

function isAttrNameStart(ch: string): boolean {
    const o = ch.charCodeAt(0);
    return (o >= 65 && o <= 90) || (o >= 97 && o <= 122) || o === 95 || o === 58;
}

function isAttrNameCont(ch: string): boolean {
    const o = ch.charCodeAt(0);
    return (
        (o >= 65 && o <= 90) ||
        (o >= 97 && o <= 122) ||
        (o >= 48 && o <= 57) ||
        o === 58 ||
        o === 46 ||
        o === 95 ||
        o === 45
    );
}

function isUnquotedChar(ch: string): boolean {
    return ch.charCodeAt(0) > 0x20 && !UNQUOTED_FORBIDDEN.has(ch);
}

export function matchOpenTag(text: string, pos: number, maximum: number): number {
    if (pos + 2 >= maximum || text[pos] !== '<' || !isAsciiAlpha(text[pos + 1]!)) return -1;
    let p = pos + 2;
    while (p < maximum && isTagNameCont(text[p]!)) p += 1;
    let mask = B_END_NO_WS;
    while (p < maximum && mask !== 0) {
        if ((mask & B_IN_SQUOTE) !== 0) {
            const q = text.indexOf("'", p);
            if (q === -1 || q >= maximum) return -1;
            p = q + 1;
            mask = B_END_NO_WS;
            continue;
        }
        if ((mask & B_IN_DQUOTE) !== 0) {
            const q = text.indexOf('"', p);
            if (q === -1 || q >= maximum) return -1;
            p = q + 1;
            mask = B_END_NO_WS;
            continue;
        }
        const ch = text[p]!;
        if (ch === '>') {
            if ((mask & (B_END_NO_WS | B_READY_WS | B_SLASH | B_IN_NAME | B_IN_UNQUOTED)) !== 0) {
                return p + 1;
            }
            return -1;
        }
        let nxt = 0;
        const isWs = ATTR_WS_CHARS.has(ch);
        const isUnq = isUnquotedChar(ch);
        if ((mask & B_END_NO_WS) !== 0) {
            if (isWs) nxt |= B_READY_WS;
            else if (ch === '/') nxt |= B_SLASH;
        }
        if ((mask & B_READY_WS) !== 0) {
            if (isWs) nxt |= B_READY_WS;
            else if (ch === '/') nxt |= B_SLASH;
            else if (isAttrNameStart(ch)) nxt |= B_IN_NAME;
        }
        if ((mask & B_IN_NAME) !== 0) {
            if (isAttrNameCont(ch)) nxt |= B_IN_NAME;
            if (isWs) nxt |= B_READY_WS | B_AFTER_NAME_WS;
            else if (ch === '=') nxt |= B_AFTER_EQ_WS;
            else if (ch === '/') nxt |= B_SLASH;
        }
        if ((mask & B_AFTER_NAME_WS) !== 0) {
            if (isWs) nxt |= B_AFTER_NAME_WS;
            else if (ch === '=') nxt |= B_AFTER_EQ_WS;
        }
        if ((mask & B_AFTER_EQ_WS) !== 0) {
            if (isWs) nxt |= B_AFTER_EQ_WS;
            if (isUnq) nxt |= B_IN_UNQUOTED;
            else if (ch === "'") nxt |= B_IN_SQUOTE;
            else if (ch === '"') nxt |= B_IN_DQUOTE;
        }
        if ((mask & B_IN_UNQUOTED) !== 0) {
            if (isUnq) nxt |= B_IN_UNQUOTED;
            if (isWs) nxt |= B_READY_WS;
            else if (ch === '/') nxt |= B_SLASH;
        }
        mask = nxt;
        p += 1;
    }
    return -1;
}

export function matchCloseTag(text: string, pos: number, maximum: number): number {
    if (pos + 3 >= maximum || text[pos] !== '<' || text[pos + 1] !== '/' || !isAsciiAlpha(text[pos + 2]!)) {
        return -1;
    }
    let p = pos + 3;
    while (p < maximum && isTagNameCont(text[p]!)) p += 1;
    while (p < maximum && ATTR_WS_CHARS.has(text[p]!)) p += 1;
    return p < maximum && text[p] === '>' ? p + 1 : -1;
}

export function matchHtmlOpenCloseLine(line: string): boolean {
    const n = line.length;
    let pos = 0;
    while (pos < n && pos < 3 && line[pos] === ' ') pos += 1;
    if (pos + 2 >= n || line[pos] !== '<') return false;
    let endPos = line[pos + 1] === '/' ? matchCloseTag(line, pos, n) : matchOpenTag(line, pos, n);
    if (endPos === -1) return false;
    while (endPos < n) {
        if (!ATTR_WS_CHARS.has(line[endPos]!)) return false;
        endPos += 1;
    }
    return true;
}

export function buildCommentIndex(segment: string): CommentIndex {
    const n = segment.length;
    const genDStarts: number[] = [];
    const genEnds: number[] = [];
    const localEnds = new Map<number, number>();
    let search = 0;
    while (search < n) {
        const idx = segment.indexOf('-->', search);
        if (idx === -1) break;
        let dStart = idx;
        while (dStart > 0 && segment[dStart - 1] === '-') dStart -= 1;
        const dAll = idx + 2 - dStart;
        if ((dAll - 2) % 3 === 0) {
            genDStarts.push(dStart);
            genEnds.push(idx + 3);
        } else if (dAll >= 4 && (dAll - 4) % 3 === 0) {
            if (dStart >= 2 && segment[dStart - 2] === '<' && segment[dStart - 1] === '!') {
                const localPos = dStart - 2;
                if (!localEnds.has(localPos)) localEnds.set(localPos, idx + 3);
            }
        }
        search = idx + 3;
    }
    return { genDStarts, genEnds, localEnds };
}

export function matchCommentWithIndex(pos: number, index: CommentIndex): number {
    let best = index.localEnds.get(pos) ?? -1;
    const target = pos + 4;
    let lo = 0;
    let hi = index.genDStarts.length;
    while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (index.genDStarts[mid]! < target) lo = mid + 1;
        else hi = mid;
    }
    if (lo < index.genEnds.length) {
        const cand = index.genEnds[lo]!;
        if (best === -1 || cand < best) best = cand;
    }
    return best;
}

export function matchHtmlInline(segment: string, pos: number, maximum: number): number {
    if (pos + 2 >= maximum) return -1;
    const ch = segment[pos + 1]!;
    if (ch === '/') return matchCloseTag(segment, pos, maximum);
    if (isAsciiAlpha(ch)) return matchOpenTag(segment, pos, maximum);
    if (ch !== '!' && ch !== '?') return -1;
    HTML_TAG_RE.lastIndex = pos;
    const m = HTML_TAG_RE.exec(segment);
    return m ? HTML_TAG_RE.lastIndex : -1;
}
