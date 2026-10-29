import { validateDocument, type Declared, type UiNode } from './validate';

export interface GlanceBadge {
    readonly status?: string;
    readonly text?: string;
    readonly tone: string;
}

const ATTENTION = new Set(['working', 'working_subagent', 'question', 'notice', 'finished_unread', 'dead']);

function firstBadge(node: UiNode): Extract<UiNode, { type: 'badge' }> | null {
    if (node.type === 'badge') return node;
    const kids = node.type === 'section' || node.type === 'row' || node.type === 'column' ? node.children : node.type === 'list' ? node.items : [];
    for (const kid of kids) {
        const found = firstBadge(kid);
        if (found) return found;
    }
    return null;
}

export function glanceBadge(document: unknown, declared: Declared): GlanceBadge | null {
    const verdict = validateDocument(document, declared);
    if (!verdict.ok) return null;
    const badge = firstBadge(verdict.doc.root);
    return badge ? { status: badge.status, text: badge.text, tone: badge.tone ?? 'normal' } : null;
}

export function wantsBar(badge: GlanceBadge): boolean {
    return badge.status ? ATTENTION.has(badge.status) : badge.tone === 'warn' || badge.tone === 'danger' || badge.tone === 'accent';
}
