import { openItemMenu } from '../item-menu/open.svelte';
import { findPathCandidates, type PathCandidate } from './detect';
import { cachedAnswer, resolvePaths, type ResolvedPath } from './api';

interface CellLike { getChars(): string; getWidth(): number }
interface LineLike { length: number; getCell(x: number): CellLike | undefined }
export interface TermLike {
    buffer: { active: { getLine(y: number): LineLike | undefined } };
    element?: HTMLElement;
}
export interface TermLink {
    range: { start: { x: number; y: number }; end: { x: number; y: number } };
    text: string;
    activate(event: MouseEvent, text: string): void;
}

interface LinkGate { shouldOpen?(event: MouseEvent): boolean }

function touchOnly(): boolean {
    return !!globalThis.matchMedia?.('(hover: none)').matches;
}

export function rowText(line: LineLike): { text: string; cols: number[] } {
    let text = '';
    const cols: number[] = [];
    for (let x = 0; x < line.length; x++) {
        const cell = line.getCell(x);
        if (!cell || cell.getWidth() === 0) continue;
        const chars = cell.getChars() || ' ';
        text += chars;
        for (let i = 0; i < chars.length; i++) cols.push(x);
    }
    return { text, cols };
}

export async function activatePath(sessionId: string, text: string, event: MouseEvent, anchor: Element): Promise<void> {
    const gate = (globalThis as { TerminalLinks?: LinkGate }).TerminalLinks;
    if (!gate?.shouldOpen?.(event)) return;
    const at = { x: event.clientX, y: event.clientY };
    let answer: ResolvedPath | null | undefined = cachedAnswer(sessionId, text);
    if (!answer) answer = (await resolvePaths(sessionId, [text])).get(text);
    if (!answer?.path || !answer.kind) return;
    openItemMenu('termpath', { sessionId, text, path: answer.path, kind: answer.kind, touch: touchOnly() }, anchor, at);
}

export function provideLinks(term: TermLike, sessionId: string, y: number, callback: (links: TermLink[] | undefined) => void): void {
    const line = sessionId && !sessionId.startsWith('remote:') ? term.buffer.active.getLine(y - 1) : undefined;
    if (!line) { callback(undefined); return; }
    const { text, cols } = rowText(line);
    const candidates = findPathCandidates(text);
    if (candidates.length === 0) { callback(undefined); return; }
    const anchor = term.element ?? document.body;
    const link = (c: PathCandidate): TermLink => ({
        range: { start: { x: (cols[c.start] ?? 0) + 1, y }, end: { x: (cols[c.end - 1] ?? 0) + 1, y } },
        text: c.text,
        activate: (event, linkText) => {
            activatePath(sessionId, linkText, event, anchor).catch((err: unknown) => {
                console.warn('terminal paths: the open failed', err);
            });
        },
    });
    if (touchOnly()) { callback(candidates.map(link)); return; }
    resolvePaths(sessionId, candidates.map((c) => c.text)).then((answers) => {
        const found = candidates.filter((c) => answers.get(c.text)?.path);
        callback(found.length ? found.map(link) : undefined);
    }, (err: unknown) => {
        console.debug('terminal paths: the check failed', err);
        callback(undefined);
    });
}
