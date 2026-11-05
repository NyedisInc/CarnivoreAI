import { t } from '../../i18n/index.svelte';
import type { MenuNode } from '../../drawer-tabs/add-component-menu';
import { failureReason } from '../../errors/failure-reason';
import { showFilesCell } from '../../file-drawer/file-drawer';
import { openFromPath } from '../../open-files/open-bridge';
import { openOutside } from '../../terminal-paths/api';
import { closing } from '../../widget-menu/model';
import { defineItemMenu } from '../registry';
import type { TermPathCtx } from '../types';

function baseName(path: string): string {
    return path.replace(/\/+$/, '').split('/').pop() || path;
}

function reported(name: string, act: () => Promise<unknown> | unknown): () => void {
    return () => {
        Promise.resolve().then(act).catch((err: unknown) => {
            globalThis.alert?.(t('terminal.path.open_failed', { name, detail: failureReason(err) }));
        });
    };
}

export function termPathNodes(ctx: TermPathCtx): MenuNode[] {
    const name = baseName(ctx.path);
    const nodes: MenuNode[] = [{
        id: 'open-carnivore', label: t('terminal.path.open_carnivore'),
        run: reported(name, () => (ctx.kind === 'dir' ? showFilesCell() : openFromPath(ctx.path))),
    }];
    if (ctx.touch) return nodes;
    if (ctx.kind === 'file') {
        nodes.push({ id: 'open-browser', label: t('terminal.path.open_browser'),
            run: reported(name, () => openOutside(ctx.sessionId, ctx.text, 'browser')) });
    }
    nodes.push({ id: 'show-finder', label: t('terminal.path.show_finder'),
        run: reported(name, () => openOutside(ctx.sessionId, ctx.text, 'finder')) });
    return nodes;
}

defineItemMenu('termpath', {
    build(ctx, env) {
        if (!ctx.path) return null;
        return { nodes: closing(termPathNodes(ctx), env.close), ariaLabel: t('terminal.path.menu', { name: baseName(ctx.path) }) };
    },
});
