import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test } from 'vitest';

import { walkSources } from '../../test-support/source-scan';

const WEB_SRC = new URL('../../', import.meta.url).pathname;
const REPO = new URL('../../../../', import.meta.url).pathname;
const SHELL = 'web/src/lib/dialog-frame/ModalShell.svelte';

const KNOWN_HAND_HEADS: Record<string, number> = {
    'web/src/lib/pack-machines/RelayApprovalPopup.svelte': 2,
    'web/src/lib/pack-machines/RelayConsentPopup.svelte': 2,
};

const KNOWN_OWN_HEADS: Record<string, number> = {
    'web/src/plugins/taskmanager/ask/TaskManagerAskPanel.svelte': 1,
    'web/src/lib/send-to/SendToModal.svelte': 1,
    'web/src/lib/session-move/MoveFolderModal.svelte': 1,
    'web/src/lib/worktree-cleanup/CleanupModal.svelte': 1,
    'web/src/lib/sidebar-shell/ProjectMenuWindows.svelte': 1,
    'web/src/lib/warroom/WarroomModal.svelte': 1,
    'web/src/lib/pack-machines/RelayApprovalPopup.svelte': 1,
    'web/src/lib/pack-machines/RelayConsentPopup.svelte': 1,
};

const HAND_HEAD = /class="[^"]*\btext-prompt-modal__head\b|overlayClass=(?:"[^"]*|\{[^}]*)\btext-prompt-modal(?![\w-])/g;
const OWN_HEAD = /\{head\}|\bhead=\{|\{#snippet head\(\)\}/;
const USES_SHELL = /<ModalShell\b/;
const SKIP_DIRS = /^(?:node_modules|__goldens__)$/;

function markupOf(text: string): string {
    return text
        .replace(/<script[^>]*>[\s\S]*?<\/script>/g, '')
        .replace(/<style[^>]*>[\s\S]*?<\/style>/g, '')
        .replace(/<!--[\s\S]*?-->/g, '');
}

function counts(hits: (markup: string) => number): Record<string, number> {
    const files = walkSources(WEB_SRC, /\.svelte$/, { skipDirs: SKIP_DIRS, base: REPO }).filter((f) => f !== SHELL);
    expect(files.length).toBeGreaterThan(200);
    const found: Record<string, number> = {};
    for (const f of files) {
        const n = hits(markupOf(readFileSync(join(REPO, f), 'utf8')));
        if (n) found[f] = n;
    }
    return found;
}

function handHeads(markup: string): number {
    return (markup.match(HAND_HEAD) ?? []).length;
}

function ownHead(markup: string): number {
    return USES_SHELL.test(markup) && OWN_HEAD.test(markup) ? 1 : 0;
}

test('no dialog hand-writes the title strip or picks the titlerow panel by class, outside the known list', () => {
    expect(counts(handHeads)).toEqual(KNOWN_HAND_HEADS);
});

test('no ModalShell caller replaces the head outside the known list, and the list is exact', () => {
    expect(counts(ownHead)).toEqual(KNOWN_OWN_HEADS);
});

test('ModalShell draws both heads itself, the X tied to dismissal', () => {
    const shell = readFileSync(join(REPO, SHELL), 'utf8');
    expect(shell).toContain("'modal-titlerow': titlerow, 'text-prompt-modal__head': titlerow");
    expect(shell).toContain("titlerow && 'text-prompt-modal'");
    expect(shell).toMatch(/data-modal-close\s+disabled=\{!dismissable\} onclick=\{onCancel\}/);
});

test('negative control: a planted strip, a class-picked panel and an own head are each named; a comment is not', () => {
    const planted = markupOf([
        '<!-- the old text-prompt-modal__head -->',
        '<ModalShell title="x" overlayClass="text-prompt-modal foo" onCancel={() => close(null)}>',
        '  {#snippet head()}<div class="text-prompt-modal__head"><span>x</span></div>{/snippet}',
        '</ModalShell>',
        "<ModalShell title=\"y\" overlayClass={busy ? 'text-prompt-modal a' : 'b'} {head} onCancel={() => go()} />",
        '<ModalShell look="titlerow" title="z" overlayClass="text-prompt-modal-ish" onCancel={() => close(null)} />',
    ].join('\n'));
    expect(handHeads(planted)).toBe(3);
    expect(ownHead(planted)).toBe(1);
    expect(ownHead('<Card>{#snippet head()}<b>x</b>{/snippet}</Card>')).toBe(0);
    expect(ownHead('<ModalShell look="titlerow" title="z" onCancel={() => close(null)} />')).toBe(0);
});
