import {
    matchHtmlOpenCloseLine,
    normalizeReferenceLabel,
    parseLinkDestination,
    scanInlineViolations,
    unescapeCommonMarkAndEntities,
} from './markdown-safe-inline';

const WS_STRIP =
    /[\x00-\x20\x7f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+/g;
const SCHEME =
    /(^|[\x00-\x20\x7f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff(<[\"'])[A-Za-z][A-Za-z0-9+.\-]{1,20}:(\/\/|[^\x00-\x20\x7f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff0-9])/;
const LINK_SCHEME = /^(?:[A-Za-z][A-Za-z0-9+.\-]*:|\/\/)/;

const MD_FENCE_OPEN = /^ {0,3}(`{3,}|~{3,})(.*)$/;
const MD_FENCE_CLOSE = /^ {0,3}(`{3,}|~{3,})[ \t]*$/;
const MD_BLANK_LINE = /^[ \t]*$/;
const MD_ATX_HEADING = /^ {0,3}#{1,6}(?:[ \t]|$)/;
const MD_ATX_STRIP = /^ {0,3}#{1,6}[ \t]*/;
const MD_ATX_ONLY_HASH = /^#+[ \t]*$/;
const MD_SETEXT_UNDERLINE = /^ {0,3}(?:=+|-+)[ \t]*$/;
const MD_THEMATIC_BREAK = /^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$/;
const MD_LIST_MARKER_ANY = /^ {0,3}([-+*]|[0-9]{1,9}[.)])(?:[ \t]|$)/;
const MD_LIST_MARKER_AT = /([-+*]|[0-9]{1,9}[.)])(?:[ \t]|$)/y;
const MD_LIST_MARKER_INT = /^ {0,3}(?:[-+*]|0{0,8}1[.)])[ \t]+[^ \t]/;

const BLOCK_WS = '[ \\t\\f\\v\\u00a0\\u1680\\u2000-\\u200a\\u202f\\u205f\\u3000]';
const MD_HTML_TYPE_1 = new RegExp(`^ {0,3}<(?:pre|script|style|textarea)(?=${BLOCK_WS}|>|$)`, 'i');
const MD_HTML_TYPE_2_3_5 = /^ {0,3}(?:<!--|<\?|<!\[CDATA\[)/;
const MD_HTML_TYPE_4 = /^ {0,3}<![A-Z]/;
const MD_HTML_TYPE_6 = new RegExp(
    '^ {0,3}</?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|' +
        'dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h1|h2|h3|h4|h5|h6|head|header|hr|html|' +
        'iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|summary|' +
        `table|tbody|td|tfoot|th|thead|title|tr|track|ul)(?=${BLOCK_WS}|\\/>|>|$)`,
    'i',
);

type Container = ['bq' | 'li', number];

function checkUrl(unescapedTarget: string): 'link_not_allowed' | null {
    WS_STRIP.lastIndex = 0;
    const cleaned = unescapedTarget.replace(WS_STRIP, '').replace(/^<+/, '');
    if (SCHEME.test(unescapedTarget) || SCHEME.test(cleaned) || LINK_SCHEME.test(cleaned)) {
        return 'link_not_allowed';
    }
    return null;
}

function initLineState(line: string): [number, number, number] {
    const n = line.length;
    let lastNonWs = n - 1;
    while (lastNonWs >= 0 && (line[lastNonWs] === ' ' || line[lastNonWs] === '\t')) {
        lastNonWs -= 1;
    }
    let pos = 0;
    let sCount = 0;
    while (pos < n) {
        const ch = line[pos]!;
        if (ch === ' ') {
            sCount += 1;
            pos += 1;
        } else if (ch === '\t') {
            sCount += 4 - (sCount % 4);
            pos += 1;
        } else {
            break;
        }
    }
    return [pos, sCount, lastNonWs];
}

function consumeBqState(line: string, startPos: number, sCount: number, bsCount: number, n: number): [number, number, number] {
    const oldSCount = sCount;
    let pos = startPos + 1;
    let initial = oldSCount + 1;
    let offset = initial;
    let adjustTab = false;
    let spaceAfterMarker = false;
    if (pos < n) {
        const ch = line[pos]!;
        if (ch === ' ') {
            pos += 1;
            initial += 1;
            offset += 1;
            spaceAfterMarker = true;
        } else if (ch === '\t') {
            spaceAfterMarker = true;
            if ((bsCount + offset) % 4 === 3) {
                pos += 1;
                initial += 1;
                offset += 1;
            } else {
                adjustTab = true;
            }
        }
    }
    while (pos < n) {
        const ch = line[pos]!;
        if (ch === ' ') {
            offset += 1;
            pos += 1;
        } else if (ch === '\t') {
            offset += 4 - ((offset + bsCount + (adjustTab ? 1 : 0)) % 4);
            pos += 1;
        } else {
            break;
        }
    }
    const nextBsCount = oldSCount + 1 + (spaceAfterMarker ? 1 : 0);
    const nextSCount = offset - initial;
    return [pos, nextSCount, nextBsCount];
}

function parseListMarkerState(
    line: string,
    pos: number,
    sCount: number,
    bsCount: number,
    n: number,
): [number, number, number] | null {
    MD_LIST_MARKER_AT.lastIndex = pos;
    const m = MD_LIST_MARKER_AT.exec(line);
    if (!m) return null;
    const markerLen = m[1]!.length;
    const initial = sCount + markerLen;
    let offset = initial;
    let j = pos + markerLen;
    while (j < n) {
        const ch = line[j]!;
        if (ch === ' ') {
            offset += 1;
            j += 1;
        } else if (ch === '\t') {
            offset += 4 - ((offset + bsCount) % 4);
            j += 1;
        } else {
            break;
        }
    }
    let indentAfterMarker = j >= n ? 1 : offset - initial;
    if (indentAfterMarker > 4) indentAfterMarker = 1;
    const indent = initial + indentAfterMarker;
    return [indent, j, offset];
}

function hrBounds(line: string, lastNonWs: number): [string, number, number] {
    if (lastNonWs < 0) return ['', 0, -1];
    const marker = line[lastNonWs]!;
    if (marker !== '*' && marker !== '-' && marker !== '_') return ['', 0, -1];
    let count = 0;
    let thirdPos = -1;
    let k = lastNonWs;
    while (k >= 0) {
        const ch = line[k]!;
        if (ch === marker) {
            count += 1;
            if (count === 3) thirdPos = k;
        } else if (ch !== ' ' && ch !== '\t') {
            break;
        }
        k -= 1;
    }
    if (thirdPos < 0) return ['', 0, -1];
    return [marker, k + 1, thirdPos];
}

function htmlBlockKind(stripped: string, allowType7: boolean): number | null {
    if (MD_HTML_TYPE_1.test(stripped)) return 1;
    if (MD_HTML_TYPE_2_3_5.test(stripped)) {
        const s = stripped.replace(/^ +/, '');
        if (s.startsWith('<!--')) return 2;
        if (s.startsWith('<?')) return 3;
        return 5;
    }
    if (MD_HTML_TYPE_4.test(stripped)) return 4;
    if (MD_HTML_TYPE_6.test(stripped)) return 6;
    if (allowType7 && matchHtmlOpenCloseLine(stripped)) return 7;
    return null;
}

function atxContent(stripped: string): string {
    const s = stripped.replace(MD_ATX_STRIP, '');
    if (MD_ATX_ONLY_HASH.test(s)) return '';
    let k = s.length;
    while (k > 0 && (s[k - 1] === ' ' || s[k - 1] === '\t')) k -= 1;
    let h = k;
    while (h > 0 && s[h - 1] === '#') h -= 1;
    if (h < k && h > 0 && (s[h - 1] === ' ' || s[h - 1] === '\t')) {
        while (h > 0 && (s[h - 1] === ' ' || s[h - 1] === '\t')) h -= 1;
        return s.slice(0, h);
    }
    return s;
}

function matchContainers(
    containers: Container[],
    bqIndices: number[],
    blkIndents: number[],
    line: string,
    limit: number,
): [number, number, number, number, number, number, boolean] {
    const n = line.length;
    let [pos, sCount, lastNonWs] = initLineState(line);
    let bsCount = 0;
    let blkIndent = 0;
    let matched = 0;
    let bqCursor = 0;
    const nBq = bqIndices.length;
    while (matched < limit) {
        const [kind, arg] = containers[matched]!;
        if (kind === 'bq') {
            if (sCount < blkIndent || pos > lastNonWs || line[pos] !== '>') break;
            [pos, sCount, bsCount] = consumeBqState(line, pos, sCount, bsCount, n);
            blkIndent = 0;
            matched += 1;
            bqCursor += 1;
        } else if (pos > lastNonWs) {
            const nextBq = bqCursor < nBq ? bqIndices[bqCursor]! : limit;
            matched = nextBq < limit ? nextBq : limit;
            return [matched, n, sCount, bsCount, blkIndents[matched]!, lastNonWs, true];
        } else {
            if (sCount < arg) break;
            blkIndent = arg;
            matched += 1;
        }
    }
    return [matched, pos, sCount, bsCount, blkIndent, lastNonWs, pos > lastNonWs];
}

function bisectLeft(arr: number[], target: number): number {
    let lo = 0;
    let hi = arr.length;
    while (lo < hi) {
        const mid = (lo + hi) >>> 1;
        if (arr[mid]! < target) lo = mid + 1;
        else hi = mid;
    }
    return lo;
}

function isTerminator(
    stripped: string,
    curS: number,
    curBlk: number,
    curList: number,
    parentType: string,
): boolean {
    if (curS - curBlk >= 4) return false;
    const mf = MD_FENCE_OPEN.exec(stripped);
    if (mf && (mf[1]![0] === '~' || !(mf[2] ?? '').includes('`'))) return true;
    if (stripped.startsWith('>')) return true;
    if (MD_THEMATIC_BREAK.test(stripped)) return true;
    if (htmlBlockKind(stripped, false) !== null) return true;
    if (MD_ATX_HEADING.test(stripped)) return true;
    if (curList >= 0 && curS - curList >= 4 && curS < curBlk) return false;
    if (parentType === 'paragraph' && curS >= curBlk) return MD_LIST_MARKER_INT.test(stripped);
    return MD_LIST_MARKER_ANY.test(stripped);
}

function checkUnmatchedTerminates(
    stripped: string,
    matched: number,
    sCount: number,
    bqIndices: number[],
    blkIndents: number[],
    listIndents: number[],
    parentType: string,
): boolean {
    const hasUnmatchedBq = bqIndices.length > 0 && bqIndices[bqIndices.length - 1]! >= matched;
    if (!hasUnmatchedBq) {
        return isTerminator(
            stripped,
            sCount,
            blkIndents[blkIndents.length - 1]!,
            listIndents[listIndents.length - 1]!,
            parentType,
        );
    }
    const firstBq = bqIndices[bisectLeft(bqIndices, matched)]!;
    const lastBq = bqIndices[bqIndices.length - 1]!;
    if (isTerminator(stripped, sCount, blkIndents[firstBq]!, listIndents[firstBq]!, 'blockquote')) {
        return true;
    }
    if (firstBq < lastBq) {
        return isTerminator(stripped, -1, 0, -1, 'blockquote');
    }
    return false;
}

function canContinueRefLine(
    lines: string[],
    idx: number,
    containers: Container[],
    blkIndents: number[],
    listIndents: number[],
    bqIndices: number[],
): [string, number] | null {
    if (idx >= lines.length || MD_BLANK_LINE.test(lines[idx]!)) return null;
    const raw = lines[idx]!;
    const [matched, pos, sCount, _bs, blkIndent, _lnws, isEmptyAfter] = matchContainers(
        containers,
        bqIndices,
        blkIndents,
        raw,
        containers.length,
    );
    if (isEmptyAfter) return null;
    const stripped = raw.slice(pos);
    if (matched === containers.length) {
        if (isTerminator(stripped, sCount, blkIndent, listIndents[listIndents.length - 1]!, 'reference')) {
            return null;
        }
        return [stripped, matched];
    }
    if (checkUnmatchedTerminates(stripped, matched, sCount, bqIndices, blkIndents, listIndents, 'reference')) {
        return null;
    }
    return [stripped, matched];
}

function tryParseRefDef(
    lines: string[],
    startIdx: number,
    firstTrimmed: string,
    containers: Container[],
    blkIndents: number[],
    listIndents: number[],
    bqIndices: number[],
): [string, string, number, number] | null {
    let buf = `${firstTrimmed}\n`;
    const lineMatched: number[] = [containers.length];
    let nextIdx = startIdx + 1;

    const pullNext = (): boolean => {
        const nxt = canContinueRefLine(lines, nextIdx, containers, blkIndents, listIndents, bqIndices);
        if (nxt === null) return false;
        buf += `${nxt[0]}\n`;
        lineMatched.push(nxt[1]);
        nextIdx += 1;
        return true;
    };

    const lineCountAt = (pos: number): number => {
        let count = 1;
        for (let i = 0; i < pos; i += 1) {
            if (buf[i] === '\n') count += 1;
        }
        return count;
    };

    const skipWsMultiline = (startPos: number): number => {
        let p = startPos;
        while (true) {
            if (p >= buf.length && !pullNext()) return p;
            const ch = buf[p]!;
            if (ch === ' ' || ch === '\t') {
                p += 1;
            } else if (ch === '\n') {
                p += 1;
                if (p === buf.length && !pullNext()) return p;
            } else {
                return p;
            }
        }
    };

    const trailingOk = (startPos: number): boolean => {
        let p = startPos;
        while (p < buf.length && (buf[p] === ' ' || buf[p] === '\t')) p += 1;
        return p >= buf.length || buf[p] === '\n';
    };

    let pos = 1;
    let labelEnd = -1;
    while (true) {
        if (pos >= buf.length && !pullNext()) return null;
        const ch = buf[pos]!;
        if (ch === '[') return null;
        if (ch === ']') {
            labelEnd = pos;
            break;
        }
        if (ch === '\n') {
            pos += 1;
            if (pos === buf.length && !pullNext()) return null;
            continue;
        }
        if (ch === '\\') {
            pos += 1;
            if (pos >= buf.length && !pullNext()) return null;
            if (pos < buf.length && buf[pos] === '\n') {
                pos += 1;
                if (pos === buf.length && !pullNext()) return null;
                continue;
            }
        }
        pos += 1;
    }

    if (labelEnd < 0 || labelEnd + 1 >= buf.length || buf[labelEnd + 1] !== ':') return null;

    pos = skipWsMultiline(labelEnd + 2);
    const destStart = pos;
    const [okDest, destEnd, destStr] = parseLinkDestination(buf, pos, buf.length);
    if (!okDest) return null;

    const destEndPos = destEnd;
    let finalPos = destEndPos;
    let oddTrailingBs = false;
    if (destEndPos < buf.length && buf[destEndPos] === '\n' && buf[destStart] !== '<') {
        let bsK = destEndPos;
        while (bsK > destStart && buf[bsK - 1] === '\\') bsK -= 1;
        oddTrailingBs = (destEndPos - bsK) % 2 === 1;
    }

    if (!oddTrailingBs) {
        const afterDestWs = skipWsMultiline(destEndPos);
        if (afterDestWs > destEndPos && afterDestWs < buf.length) {
            const opener = buf[afterDestWs]!;
            if (opener === '"' || opener === "'" || opener === '(') {
                const closer = opener === '(' ? ')' : opener;
                let tPos = afterDestWs + 1;
                let tOk = false;
                while (true) {
                    if (tPos >= buf.length && !pullNext()) break;
                    const tCh = buf[tPos]!;
                    if (tCh === closer) {
                        tPos += 1;
                        tOk = true;
                        break;
                    }
                    if (tCh === '(' && closer === ')') break;
                    if (tCh === '\\') {
                        tPos += 1;
                        if (tPos >= buf.length && !pullNext()) break;
                    }
                    tPos += 1;
                }
                if (tOk && trailingOk(tPos)) finalPos = tPos;
            }
        }
    }

    if (!trailingOk(finalPos)) return null;

    const normLabel = normalizeReferenceLabel(buf.slice(1, labelEnd));
    if (!normLabel) return null;

    const usedLines = Math.min(lineCountAt(finalPos), lineMatched.length);
    return [destStr, normLabel, startIdx + usedLines, lineMatched[usedLines - 1]!];
}

export function checkMarkdownSafeViolation(text: string): 'html_not_allowed' | 'link_not_allowed' | null {
    const normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const lines = normalized.split('\n');
    let segLines: string[] = [];
    const inlineSegments: string[] = [];
    const refUrls: string[] = [];
    const refLabels = new Set<string>();
    const containers: Container[] = [];
    const blkIndents: number[] = [0];
    const listIndents: number[] = [-1];
    const bqIndices: number[] = [];
    let inFence: [number, string, number] | null = null;
    let emptyLiParent: number | null = null;

    const flushSeg = (): void => {
        if (segLines.length > 0) {
            inlineSegments.push(segLines.join('\n'));
            segLines = [];
        }
    };

    const pushContainer = (kind: 'bq' | 'li', arg: number): void => {
        if (kind === 'bq') {
            bqIndices.push(containers.length);
            listIndents.push(listIndents[listIndents.length - 1]!);
            blkIndents.push(0);
        } else {
            listIndents.push(blkIndents[blkIndents.length - 1]!);
            blkIndents.push(arg);
        }
        containers.push([kind, arg]);
    };

    const truncateContainers = (newLen: number): void => {
        if (newLen < containers.length) {
            containers.length = newLen;
            blkIndents.length = newLen + 1;
            listIndents.length = newLen + 1;
            while (bqIndices.length > 0 && bqIndices[bqIndices.length - 1]! >= newLen) {
                bqIndices.pop();
            }
        }
    };

    let idx = 0;
    const nLines = lines.length;
    while (idx < nLines) {
        const rawLine = lines[idx]!;

        if (inFence !== null) {
            const [fDepth, fChar, fLen] = inFence;
            if (MD_BLANK_LINE.test(rawLine)) {
                const firstBq = bqIndices.length > 0 ? bqIndices[0]! : containers.length;
                if (firstBq < fDepth) {
                    truncateContainers(firstBq);
                    inFence = null;
                }
                emptyLiParent = null;
                idx += 1;
                continue;
            }
            const [matched, pos, sCount, _bs, blkIndent, _lnws, isEmptyAfter] = matchContainers(
                containers,
                bqIndices,
                blkIndents,
                rawLine,
                fDepth,
            );
            if (matched < fDepth) {
                truncateContainers(matched);
                inFence = null;
            } else {
                if (!isEmptyAfter && sCount - blkIndent < 4) {
                    const mc = MD_FENCE_CLOSE.exec(rawLine.slice(pos));
                    if (mc && mc[1]![0] === fChar && mc[1]!.length >= fLen) inFence = null;
                }
                emptyLiParent = null;
                idx += 1;
                continue;
            }
        }

        if (MD_BLANK_LINE.test(rawLine)) {
            flushSeg();
            let limitLen = bqIndices.length > 0 ? bqIndices[0]! : containers.length;
            if (emptyLiParent !== null && emptyLiParent < limitLen) limitLen = emptyLiParent;
            truncateContainers(limitLen);
            emptyLiParent = null;
            idx += 1;
            continue;
        }

        let [matched, pos, sCount, bsCount, blkIndent, lastNonWs, isEmptyAfter] = matchContainers(
            containers,
            bqIndices,
            blkIndents,
            rawLine,
            containers.length,
        );

        if (isEmptyAfter) {
            flushSeg();
            let limitLen = matched;
            if (emptyLiParent !== null && emptyLiParent < limitLen) limitLen = emptyLiParent;
            truncateContainers(limitLen);
            emptyLiParent = null;
            idx += 1;
            continue;
        }

        emptyLiParent = null;
        let stripped = rawLine.slice(pos);

        if (segLines.length > 0) {
            if (matched === containers.length) {
                if (sCount - blkIndent < 4) {
                    if (MD_SETEXT_UNDERLINE.test(stripped) || MD_THEMATIC_BREAK.test(stripped)) {
                        flushSeg();
                        idx += 1;
                        continue;
                    }
                    if (MD_ATX_HEADING.test(stripped)) {
                        flushSeg();
                        inlineSegments.push(atxContent(stripped));
                        idx += 1;
                        continue;
                    }
                    const mf = MD_FENCE_OPEN.exec(stripped);
                    if (mf && (mf[1]![0] === '~' || !(mf[2] ?? '').includes('`'))) {
                        flushSeg();
                        inFence = [containers.length, mf[1]![0]!, mf[1]!.length];
                        idx += 1;
                        continue;
                    }
                    if (htmlBlockKind(stripped, false) !== null) return 'html_not_allowed';
                    if (stripped.startsWith('>') || MD_LIST_MARKER_INT.test(stripped)) {
                        flushSeg();
                    } else {
                        segLines.push(stripped);
                        idx += 1;
                        continue;
                    }
                } else {
                    segLines.push(stripped);
                    idx += 1;
                    continue;
                }
            } else {
                if (
                    checkUnmatchedTerminates(
                        stripped,
                        matched,
                        sCount,
                        bqIndices,
                        blkIndents,
                        listIndents,
                        'paragraph',
                    )
                ) {
                    flushSeg();
                    truncateContainers(matched);
                    blkIndent = blkIndents[matched]!;
                    if (sCount - blkIndent >= 4) {
                        idx += 1;
                        continue;
                    }
                } else {
                    segLines.push(stripped);
                    idx += 1;
                    continue;
                }
            }
        } else {
            truncateContainers(matched);
        }

        const nLine = rawLine.length;
        let hrInfo: [string, number, number] | null = null;
        let lastPushedKind: 'bq' | 'li' | null = null;
        while (pos <= lastNonWs && sCount - blkIndent < 4) {
            if (rawLine[pos] === '>') {
                [pos, sCount, bsCount] = consumeBqState(rawLine, pos, sCount, bsCount, nLine);
                blkIndent = 0;
                pushContainer('bq', 0);
                lastPushedKind = 'bq';
                continue;
            }
            const tailCh = rawLine[lastNonWs]!;
            if (tailCh === '*' || tailCh === '-' || tailCh === '_') {
                if (hrInfo === null) hrInfo = hrBounds(rawLine, lastNonWs);
                const [hrCh, hrMin, hrThird] = hrInfo;
                if (hrThird >= 0 && pos >= hrMin && pos <= hrThird && rawLine[pos] === hrCh) break;
            }
            const li = parseListMarkerState(rawLine, pos, sCount, bsCount, nLine);
            if (li !== null) {
                let indent: number;
                [indent, pos, sCount] = li;
                blkIndent = indent;
                pushContainer('li', indent);
                lastPushedKind = 'li';
                continue;
            }
            break;
        }

        if (pos > lastNonWs) {
            if (lastPushedKind === 'li') emptyLiParent = containers.length - 1;
            idx += 1;
            continue;
        }

        if (sCount - blkIndent >= 4) {
            idx += 1;
            continue;
        }

        stripped = rawLine.slice(pos);
        const mf = MD_FENCE_OPEN.exec(stripped);
        if (mf && (mf[1]![0] === '~' || !(mf[2] ?? '').includes('`'))) {
            inFence = [containers.length, mf[1]![0]!, mf[1]!.length];
            idx += 1;
            continue;
        }

        if (MD_THEMATIC_BREAK.test(stripped)) {
            idx += 1;
            continue;
        }

        if (MD_ATX_HEADING.test(stripped)) {
            inlineSegments.push(atxContent(stripped));
            idx += 1;
            continue;
        }

        if (htmlBlockKind(stripped, true) !== null) return 'html_not_allowed';

        if (stripped.startsWith('[')) {
            const ref = tryParseRefDef(lines, idx, stripped, containers, blkIndents, listIndents, bqIndices);
            if (ref !== null) {
                const [destUrl, normLabel, nextIdx, lastMatched] = ref;
                refUrls.push(destUrl);
                refLabels.add(normLabel);
                truncateContainers(lastMatched);
                idx = nextIdx;
                continue;
            }
        }

        segLines.push(stripped);
        idx += 1;
    }
    flushSeg();

    let sawLinkErr = false;
    for (const segment of inlineSegments) {
        const verdict = scanInlineViolations(segment, checkUrl, refLabels);
        if (verdict === 'html_not_allowed') return 'html_not_allowed';
        if (verdict === 'link_not_allowed') sawLinkErr = true;
    }

    const decoded = unescapeCommonMarkAndEntities(normalized);
    if (SCHEME.test(decoded)) return 'link_not_allowed';
    for (const refUrl of refUrls) {
        if (checkUrl(refUrl) === 'link_not_allowed') return 'link_not_allowed';
    }
    if (sawLinkErr) return 'link_not_allowed';
    return null;
}
