import {
    ASCII_PUNCT,
    type CommentIndex,
    HTML_OPEN_CLOSE_LINE_RE,
    HTML_TAG_RE,
    buildCommentIndex,
    isAsciiAlpha,
    isMdValidAutolinkUrl,
    matchCloseTag,
    matchCommentWithIndex,
    matchHtmlOpenCloseLine,
    matchOpenTag,
    normalizeReferenceLabel,
    parseLinkDestination,
    parseLinkTitle,
    tryAutolink,
    unescapeCommonMarkAndEntities,
} from './markdown-safe-tags';

export {
    HTML_OPEN_CLOSE_LINE_RE,
    HTML_TAG_RE,
    matchHtmlOpenCloseLine,
    normalizeReferenceLabel,
    parseLinkDestination,
    parseLinkTitle,
    unescapeCommonMarkAndEntities,
};

type BracketOpener = {
    pos: number;
    isImage: boolean;
    active: boolean;
    hasNestedBracket: boolean;
    hasNestedLink: boolean;
};

type RefStackItem = {
    openP: number;
    isImage: boolean;
    hasNestedLink: boolean;
    hasNestedBracket: boolean;
};

type RefPending = {
    openP: number;
    isImage: boolean;
    hasNestedLink: boolean;
    hasNestedBracket: boolean;
    labelEnd: number;
    pRef: number;
    triedImage: boolean;
};

type RefFrame = {
    startBracket: number;
    fallbackStart: number;
    stack: RefStackItem[];
    q: number;
    pending: RefPending | null;
};

function skipAsciiWs(segment: string, pos: number, maximum: number): number {
    while (pos < maximum) {
        const ch = segment[pos]!;
        if (ch !== ' ' && ch !== '\t' && ch !== '\n') break;
        pos += 1;
    }
    return pos;
}

export function scanInlineViolations(
    segment: string,
    checkUrl: (url: string) => 'link_not_allowed' | null,
    refLabels: ReadonlySet<string> = new Set(),
): 'html_not_allowed' | 'link_not_allowed' | null {
    const end = segment.length;
    const lastGt = segment.lastIndexOf('>');
    let lastPiClose: number | null = null;
    let lastCdataClose: number | null = null;
    let commentIndex: CommentIndex | null = null;
    let btScannedAll = false;
    const btLastPos = new Map<number, number>();
    const refLabelCache = new Map<number, number>();
    const refHasNestedLinkCache = new Set<number>();
    const refHasNestedBracketCache = new Set<number>();
    const skipLinkCache = new Map<number, number>();
    const parenCache = new Map<number, [number, string | null, number]>();

    const matchHtmlInlineFast = (pos: number): number => {
        if (pos > lastGt || pos + 2 >= end) return -1;
        const ch = segment[pos + 1]!;
        if (ch === '!') {
            if (segment.startsWith('<!--', pos)) {
                if (pos + 5 <= end && segment[pos + 4] === '>') return pos + 5;
                if (pos + 6 <= end && segment[pos + 4] === '-' && segment[pos + 5] === '>') return pos + 6;
                if (commentIndex === null) commentIndex = buildCommentIndex(segment);
                return matchCommentWithIndex(pos, commentIndex);
            }
            if (segment.startsWith('<![CDATA[', pos)) {
                if (lastCdataClose === null) lastCdataClose = segment.lastIndexOf(']]>');
                if (pos + 9 > lastCdataClose) return -1;
                const idx = segment.indexOf(']]>', pos + 9);
                return idx !== -1 && idx + 3 <= end ? idx + 3 : -1;
            }
            if (isAsciiAlpha(segment[pos + 2]!)) {
                if (pos + 3 > lastGt) return -1;
                const idx = segment.indexOf('>', pos + 3);
                return idx !== -1 && idx + 1 <= end ? idx + 1 : -1;
            }
            return -1;
        }
        if (ch === '?') {
            if (lastPiClose === null) lastPiClose = segment.lastIndexOf('?>');
            if (pos + 2 > lastPiClose) return -1;
            const idx = segment.indexOf('?>', pos + 2);
            return idx !== -1 && idx + 2 <= end ? idx + 2 : -1;
        }
        if (ch === '/') return matchCloseTag(segment, pos, end);
        if (isAsciiAlpha(ch)) return matchOpenTag(segment, pos, end);
        return -1;
    };

    const findBackticks = (pos: number): [number, number] => {
        let j = pos;
        while (j < end && segment[j] === '`') j += 1;
        const openLen = j - pos;
        if (btScannedAll && (btLastPos.get(openLen) ?? -1) <= pos) return [j, -1];
        let k = j;
        while (k < end) {
            if (segment[k] === '`') {
                let m = k;
                while (m < end && segment[m] === '`') m += 1;
                const runLen = m - k;
                if (runLen === openLen) return [j, m];
                if ((btLastPos.get(runLen) ?? -1) < k) btLastPos.set(runLen, k);
                k = m;
            } else {
                k += 1;
            }
        }
        btScannedAll = true;
        return [j, -1];
    };

    const tryInlineParenTail = (openParenPos: number): [number, string | null, number] => {
        const cached = parenCache.get(openParenPos);
        if (cached !== undefined) return cached;
        let p = skipAsciiWs(segment, openParenPos + 1, end);
        if (p >= end) {
            const res: [number, string | null, number] = [-1, null, -1];
            parenCache.set(openParenPos, res);
            return res;
        }
        let destVal: string | null = null;
        const [okDest, destEnd, destStr] = parseLinkDestination(segment, p, end, false);
        if (okDest && isMdValidAutolinkUrl(destStr)) {
            destVal = destStr;
            p = destEnd;
            const wsStart = p;
            p = skipAsciiWs(segment, p, end);
            if (p < end && p !== wsStart) {
                const [okTitle, titleEnd] = parseLinkTitle(segment, p, end);
                if (okTitle) p = skipAsciiWs(segment, titleEnd, end);
            }
        }
        const res: [number, string | null, number] =
            p < end && segment[p] === ')' ? [p + 1, destVal, -1] : [-1, null, p + 1];
        parenCache.set(openParenPos, res);
        return res;
    };

    const runPass = (
        startPos: number,
        allowDesyncCheck: boolean,
    ): ['html_not_allowed' | 'link_not_allowed' | null, number] => {
        let desyncFrom = -1;
        let sawClosedSpanInOpeners = false;
        const openers: BracketOpener[] = [];
        let activeOrImgOpeners = 0;
        let pos = startPos;
        let sawLinkErr = false;

        const noteDesync = (fallbackStart = -1): void => {
            if (allowDesyncCheck && desyncFrom === -1 && sawClosedSpanInOpeners) {
                for (const op of openers) {
                    if (op.active || op.isImage) {
                        desyncFrom = op.pos + (op.isImage ? 2 : 1);
                        break;
                    }
                }
                if (desyncFrom === -1 && fallbackStart !== -1) {
                    desyncFrom = fallbackStart;
                }
            }
        };

        const findRefLabelEnd = (initBracket: number, initFallback = -1): number => {
            const cached = refLabelCache.get(initBracket);
            if (cached !== undefined) return cached;
            const frames: RefFrame[] = [
                {
                    startBracket: initBracket,
                    fallbackStart: initFallback,
                    stack: [{ openP: initBracket, isImage: false, hasNestedLink: false, hasNestedBracket: false }],
                    q: initBracket + 1,
                    pending: null,
                },
            ];
            let lastResult = -1;

            const markStackFailed = (stack: RefStackItem[]): void => {
                for (const item of stack) {
                    const bKey = item.isImage ? item.openP + 1 : item.openP;
                    refLabelCache.set(bKey, -1);
                }
            };

            const propagateNestedLink = (stack: RefStackItem[]): void => {
                for (let idx = stack.length - 1; idx >= 0; idx -= 1) {
                    const op = stack[idx]!;
                    if (op.hasNestedLink) break;
                    op.hasNestedLink = true;
                    if (op.isImage) break;
                }
            };

            const finishInnerTail = (
                frame: RefFrame,
                openP: number,
                isImg: boolean,
                hLink: boolean,
                hBr: boolean,
                labelEnd: number,
                pRef: number,
                refEnd: number,
                triedImg: boolean,
            ): void => {
                const stack = frame.stack;
                const labelStart = openP + (isImg ? 2 : 1);
                const nextPos = refEnd >= 0 ? refEnd + 1 : labelEnd + 1;
                const hasNonemptyRef = refEnd >= 0 && refEnd > pRef + 1;
                let matched = false;
                if (hasNonemptyRef) {
                    if (!refHasNestedBracketCache.has(pRef)) {
                        matched = refLabels.has(normalizeReferenceLabel(segment.slice(pRef + 1, refEnd)));
                    }
                } else if (!hBr) {
                    matched = refLabels.has(normalizeReferenceLabel(segment.slice(labelStart, labelEnd)));
                }
                if (triedImg) {
                    if (matched) {
                        skipLinkCache.set(openP, nextPos);
                        stack[stack.length - 1]!.hasNestedBracket = true;
                        frame.q = nextPos;
                    } else {
                        skipLinkCache.set(openP, -1);
                        skipLinkCache.set(openP + 1, -1);
                        if (hLink) propagateNestedLink(stack);
                        frame.q = labelEnd + 1;
                    }
                    return;
                }
                const linkKey = isImg ? openP + 1 : openP;
                if (matched) {
                    skipLinkCache.set(linkKey, nextPos);
                    stack[stack.length - 1]!.hasNestedBracket = true;
                    propagateNestedLink(stack);
                    frame.q = nextPos;
                } else {
                    skipLinkCache.set(linkKey, -1);
                    if (isImg && hLink) propagateNestedLink(stack);
                    frame.q = labelEnd + 1;
                }
            };

            const resolveRef = (
                frame: RefFrame,
                openP: number,
                isImg: boolean,
                hLink: boolean,
                hBr: boolean,
                labelEnd: number,
                pRef: number,
                triedImg: boolean,
            ): void => {
                if (pRef < end && segment[pRef] === '[') {
                    const cRef = refLabelCache.get(pRef);
                    if (cRef === undefined) {
                        frame.pending = { openP, isImage: isImg, hasNestedLink: hLink, hasNestedBracket: hBr, labelEnd, pRef, triedImage: triedImg };
                        frames.push({
                            startBracket: pRef,
                            fallbackStart: openP + (isImg ? 2 : 1),
                            stack: [{ openP: pRef, isImage: false, hasNestedLink: false, hasNestedBracket: false }],
                            q: pRef + 1,
                            pending: null,
                        });
                        return;
                    }
                    finishInnerTail(frame, openP, isImg, hLink, hBr, labelEnd, pRef, cRef, triedImg);
                    return;
                }
                finishInnerTail(frame, openP, isImg, hLink, hBr, labelEnd, pRef, -1, triedImg);
            };

            const startInnerTail = (
                frame: RefFrame,
                openP: number,
                isImg: boolean,
                hLink: boolean,
                hBr: boolean,
                labelEnd: number,
            ): void => {
                const stack = frame.stack;
                const p = labelEnd + 1;
                if (isImg) {
                    if (p < end && segment[p] === '(') {
                        const [mEnd, , fbPos] = tryInlineParenTail(p);
                        if (mEnd >= 0) {
                            skipLinkCache.set(openP, mEnd);
                            stack[stack.length - 1]!.hasNestedBracket = true;
                            frame.q = mEnd;
                            return;
                        }
                        skipLinkCache.set(openP, -1);
                        if (hLink || fbPos === -1 || refLabels.size === 0) {
                            skipLinkCache.set(openP + 1, -1);
                            if (hLink) propagateNestedLink(stack);
                            frame.q = labelEnd + 1;
                            return;
                        }
                        resolveRef(frame, openP, true, hLink, hBr, labelEnd, fbPos, false);
                        return;
                    }
                    if (refLabels.size === 0) {
                        skipLinkCache.set(openP, -1);
                        skipLinkCache.set(openP + 1, -1);
                        if (hLink) propagateNestedLink(stack);
                        frame.q = labelEnd + 1;
                        return;
                    }
                    resolveRef(frame, openP, true, hLink, hBr, labelEnd, p, true);
                    return;
                }
                if (hLink) {
                    skipLinkCache.set(openP, -1);
                    propagateNestedLink(stack);
                    frame.q = labelEnd + 1;
                    return;
                }
                let pRef = p;
                if (p < end && segment[p] === '(') {
                    const [mEnd, , fbPos] = tryInlineParenTail(p);
                    if (mEnd >= 0) {
                        skipLinkCache.set(openP, mEnd);
                        stack[stack.length - 1]!.hasNestedBracket = true;
                        propagateNestedLink(stack);
                        frame.q = mEnd;
                        return;
                    }
                    if (fbPos === -1) {
                        skipLinkCache.set(openP, -1);
                        frame.q = labelEnd + 1;
                        return;
                    }
                    pRef = fbPos;
                }
                if (refLabels.size === 0) {
                    skipLinkCache.set(openP, -1);
                    frame.q = labelEnd + 1;
                    return;
                }
                resolveRef(frame, openP, false, hLink, hBr, labelEnd, pRef, false);
            };

            while (frames.length > 0) {
                const frame = frames[frames.length - 1]!;
                if (frame.pending !== null) {
                    const pend = frame.pending;
                    frame.pending = null;
                    finishInnerTail(frame, pend.openP, pend.isImage, pend.hasNestedLink, pend.hasNestedBracket, pend.labelEnd, pend.pRef, lastResult, pend.triedImage);
                    if (frames[frames.length - 1] !== frame) continue;
                }
                const stack = frame.stack;
                let q = frame.q;
                const fbCur = frames[0]!.fallbackStart !== -1 ? frames[0]!.fallbackStart : frame.fallbackStart;
                let popped = false;
                while (q < end) {
                    const ch = segment[q]!;
                    if (ch === ']') {
                        const item = stack.pop()!;
                        const bKey = item.isImage ? item.openP + 1 : item.openP;
                        refLabelCache.set(bKey, q);
                        if (item.hasNestedLink) refHasNestedLinkCache.add(bKey);
                        if (item.hasNestedBracket) refHasNestedBracketCache.add(bKey);
                        if (stack.length === 0) { lastResult = q; frames.pop(); popped = true; break; }
                        startInnerTail(frame, item.openP, item.isImage, item.hasNestedLink, item.hasNestedBracket, q);
                        if (frames[frames.length - 1] !== frame) { popped = true; break; }
                        q = frame.q;
                        continue;
                    }
                    if (ch === '\\') { q += q + 1 < end ? 2 : 1; continue; }
                    if (ch === '`') {
                        const wasScanned = btScannedAll;
                        const [openE, closeE] = findBackticks(q);
                        if (!wasScanned && btScannedAll) noteDesync(fbCur);
                        q = closeE !== -1 ? closeE : openE;
                        continue;
                    }
                    if (ch === '<') {
                        if (q <= lastGt) {
                            const auto = tryAutolink(segment, q, end);
                            if (auto !== null && isMdValidAutolinkUrl(auto[0])) { q = auto[1]; continue; }
                            const htmlEnd = matchHtmlInlineFast(q);
                            if (htmlEnd !== -1) { q = htmlEnd; continue; }
                        }
                        q += 1;
                        continue;
                    }
                    if (ch === '[') {
                        const skipEnd = skipLinkCache.get(q);
                        if (skipEnd !== undefined && skipEnd >= 0) {
                            stack[stack.length - 1]!.hasNestedBracket = true;
                            propagateNestedLink(stack);
                            q = skipEnd;
                            frame.q = q;
                            continue;
                        }
                        const subCached = refLabelCache.get(q);
                        if (subCached !== undefined) {
                            if (subCached < 0) { markStackFailed(stack); lastResult = -1; frames.pop(); popped = true; break; }
                            if (skipLinkCache.has(q)) {
                                stack[stack.length - 1]!.hasNestedBracket = true;
                                if (refHasNestedLinkCache.has(q)) propagateNestedLink(stack);
                                q = subCached + 1;
                                frame.q = q;
                                continue;
                            }
                            stack[stack.length - 1]!.hasNestedBracket = true;
                            startInnerTail(frame, q, false, refHasNestedLinkCache.has(q), refHasNestedBracketCache.has(q), subCached);
                            if (frames[frames.length - 1] !== frame) { popped = true; break; }
                            q = frame.q;
                            continue;
                        }
                        stack[stack.length - 1]!.hasNestedBracket = true;
                        stack.push({ openP: q, isImage: false, hasNestedLink: false, hasNestedBracket: false });
                        q += 1;
                        frame.q = q;
                        continue;
                    }
                    if (ch === '!' && q + 1 < end && segment[q + 1] === '[') {
                        const skipEnd = skipLinkCache.get(q);
                        if (skipEnd !== undefined) {
                            stack[stack.length - 1]!.hasNestedBracket = true;
                            q = skipEnd >= 0 ? skipEnd : q + 1;
                            frame.q = q;
                            continue;
                        }
                        const subCached = refLabelCache.get(q + 1);
                        if (subCached !== undefined) {
                            if (subCached < 0) { markStackFailed(stack); lastResult = -1; frames.pop(); popped = true; break; }
                            stack[stack.length - 1]!.hasNestedBracket = true;
                            startInnerTail(frame, q, true, refHasNestedLinkCache.has(q + 1), refHasNestedBracketCache.has(q + 1), subCached);
                            if (frames[frames.length - 1] !== frame) { popped = true; break; }
                            q = frame.q;
                            continue;
                        }
                        stack[stack.length - 1]!.hasNestedBracket = true;
                        stack.push({ openP: q, isImage: true, hasNestedLink: false, hasNestedBracket: false });
                        q += 2;
                        frame.q = q;
                        continue;
                    }
                    q += 1;
                }
                if (!popped) { markStackFailed(stack); lastResult = -1; frames.pop(); }
            }
            return lastResult;
        };

        while (pos < end) {
            const ch = segment[pos]!;
            if (ch === '\\') {
                if (pos + 1 < end && (segment[pos + 1] === '\n' || ASCII_PUNCT.has(segment[pos + 1]!))) {
                    pos += 2;
                } else {
                    pos += 1;
                }
                continue;
            }
            if (ch === '`') {
                const wasScanned = btScannedAll;
                const [openEnd, closeEnd] = findBackticks(pos);
                if (closeEnd !== -1) {
                    if (allowDesyncCheck && activeOrImgOpeners > 0) sawClosedSpanInOpeners = true;
                } else if (!wasScanned && btScannedAll) {
                    noteDesync();
                }
                pos = closeEnd !== -1 ? closeEnd : openEnd;
                continue;
            }
            if (ch === '<') {
                if (pos <= lastGt) {
                    const auto = tryAutolink(segment, pos, end);
                    if (auto !== null) {
                        if (checkUrl(auto[0]) === 'link_not_allowed') sawLinkErr = true;
                        pos = auto[1];
                        continue;
                    }
                    if (matchHtmlInlineFast(pos) !== -1) return ['html_not_allowed', -1];
                }
                pos += 1;
                continue;
            }
            if (ch === '[') {
                if (openers.length > 0) openers[openers.length - 1]!.hasNestedBracket = true;
                openers.push({ pos, isImage: false, active: true, hasNestedBracket: false, hasNestedLink: false });
                activeOrImgOpeners += 1;
                pos += 1;
                continue;
            }
            if (ch === '!' && pos + 1 < end && segment[pos + 1] === '[') {
                if (openers.length > 0) openers[openers.length - 1]!.hasNestedBracket = true;
                openers.push({ pos, isImage: true, active: true, hasNestedBracket: false, hasNestedLink: false });
                activeOrImgOpeners += 1;
                pos += 2;
                continue;
            }
            if (ch === ']') {
                if (openers.length === 0) {
                    pos += 1;
                    continue;
                }
                const opener = openers.pop()!;
                if (opener.active || opener.isImage) activeOrImgOpeners -= 1;
                if (!opener.active) {
                    pos += 1;
                    continue;
                }

                const labelStart = opener.pos + (opener.isImage ? 2 : 1);
                const labelEnd = pos;
                const p = labelEnd + 1;
                let matchedEnd = -1;
                let matchedDest: string | null = null;
                let matchedAsImage = false;

                const tryRefMatch = (pRef: number, refFallback: number): number => {
                    if (refLabels.size === 0) return -1;
                    let hasNonemptyRef = false;
                    let nextPos = labelEnd + 1;
                    if (pRef < end && segment[pRef] === '[') {
                        const refEnd = findRefLabelEnd(pRef, refFallback);
                        if (refEnd >= 0) {
                            nextPos = refEnd + 1;
                            if (refEnd > pRef + 1) {
                                hasNonemptyRef = true;
                                if (!refHasNestedBracketCache.has(pRef)) {
                                    if (refLabels.has(normalizeReferenceLabel(segment.slice(pRef + 1, refEnd)))) {
                                        return nextPos;
                                    }
                                }
                                return -1;
                            }
                        }
                    }
                    if (!hasNonemptyRef && !opener.hasNestedBracket) {
                        if (refLabels.has(normalizeReferenceLabel(segment.slice(labelStart, labelEnd)))) {
                            return nextPos;
                        }
                    }
                    return -1;
                };

                if (p < end && segment[p] === '(') {
                    const [candEnd, candDest, fbPos] = tryInlineParenTail(p);
                    if (candEnd >= 0) {
                        matchedEnd = candEnd;
                        matchedDest = candDest;
                        matchedAsImage = opener.isImage;
                    } else if (!opener.hasNestedLink && fbPos !== -1) {
                        matchedEnd = tryRefMatch(fbPos, labelStart);
                    }
                } else if (opener.isImage) {
                    matchedEnd = tryRefMatch(p, labelStart);
                    if (matchedEnd >= 0) matchedAsImage = true;
                } else if (!opener.hasNestedLink) {
                    matchedEnd = tryRefMatch(p, labelStart);
                }

                if (matchedEnd >= 0) {
                    if (matchedDest !== null && checkUrl(matchedDest) === 'link_not_allowed') {
                        sawLinkErr = true;
                    }
                    if (!matchedAsImage) {
                        for (let idxOp = openers.length - 1; idxOp >= 0; idxOp -= 1) {
                            const prev = openers[idxOp]!;
                            if (prev.isImage) {
                                prev.hasNestedLink = true;
                                break;
                            }
                            if (!prev.active) break;
                            prev.active = false;
                            activeOrImgOpeners -= 1;
                        }
                    }
                    pos = matchedEnd;
                    continue;
                }

                if (opener.isImage && opener.hasNestedLink) {
                    for (let idxOp = openers.length - 1; idxOp >= 0; idxOp -= 1) {
                        const prev = openers[idxOp]!;
                        if (prev.isImage) {
                            prev.hasNestedLink = true;
                            break;
                        }
                        if (!prev.active) break;
                        prev.active = false;
                        activeOrImgOpeners -= 1;
                    }
                }

                pos += 1;
                continue;
            }
            pos += 1;
        }

        return [sawLinkErr ? 'link_not_allowed' : null, desyncFrom];
    };

    const [res1, desyncFrom] = runPass(0, true);
    if (res1 === 'html_not_allowed') return res1;
    if (desyncFrom !== -1) {
        refLabelCache.clear();
        refHasNestedLinkCache.clear();
        refHasNestedBracketCache.clear();
        skipLinkCache.clear();
        const [res2] = runPass(desyncFrom, false);
        if (res2 === 'html_not_allowed' || res2 === 'link_not_allowed') return res2;
    }
    return res1;
}
