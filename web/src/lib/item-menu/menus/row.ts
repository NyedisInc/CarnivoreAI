import { addToNodes } from '../../add-to-menu/host';
import type { MenuNode } from '../../drawer-tabs/add-component-menu';
import { t } from '../../i18n/index.svelte';
import { packMachines } from '../../pack-machines/pack-machines-store.svelte';
import { computerNodes } from '../../send-to/host';
import type { RowMenuCtx, RowMenuType } from '../row-context';
import { pluginItemsFor, runPluginItem } from '../row-plugins';
import { defineItemMenu } from '../registry';
import type { ItemMenuEnv } from '../types';
import { groupFor, ROW_ITEMS } from './row-items';

export interface ResolvedRowItem {
    id: string;
    order: number;
    label: string;
    enabled: boolean;
    reason: string;
    separatorBefore: boolean;
    tone?: 'update';
    locked?: string;
    plugin?: boolean;
}

export const BRANCH_ITEM_IDS: readonly string[] = ['add-to', 'add-members', 'send-to'];

const COPIED_FLASH_MS = 700;

interface RowRunGlobals {
    SessionRowMenuActions?: {
        run(id: string, ctx: RowMenuCtx, opts?: Record<string, unknown>): unknown;
        runCopySessionId?(ctx: RowMenuCtx): Promise<boolean>;
    };
    API?: { getProjects?(): Promise<{ id: unknown; name?: string }[]> };
}

const g = (): RowRunGlobals => globalThis as unknown as RowRunGlobals;

export function rowMenuItems(ctx: RowMenuCtx): ResolvedRowItem[] {
    const out: ResolvedRowItem[] = ROW_ITEMS.filter((item) => item.available(ctx)).map((item) => {
        const ok = !!item.enabled(ctx);
        return {
            id: item.id, order: item.order, separatorBefore: false, label: item.label(ctx), enabled: ok,
            reason: ok ? '' : item.reason(ctx) || '', ...(item.tone ? { tone: item.tone } : {}),
        };
    });
    const captured = String(ctx.pluginItems || '').split(',');
    for (const item of pluginItemsFor(ctx as unknown as Record<string, unknown>)) {
        if (!captured.includes(item.id)) continue;
        if (item.id === 'mark-unread' && ctx.unread === true && out.some((o) => o.id === 'mark-read')) continue;
        if (item.id === 'mark-unread' && (ctx.status === 'working' || ctx.status === 'working_subagent') && ctx.unread !== true) continue;
        out.push({
            id: item.id, order: item.order, separatorBefore: false, label: item.label, enabled: true, reason: '', plugin: true,
            ...(item.locked ? { locked: item.feature ?? item.id } : {}),
        });
    }
    out.sort((a, b) => (a.order !== b.order ? a.order - b.order : a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    out.forEach((item, i) => {
        item.separatorBefore = i > 0 && groupFor(item.order) !== groupFor(out[i - 1]!.order);
    });
    return out;
}

function pushedProject(uuid: string | null | undefined, tmuxName: string): { id: number | null; name: string | null } {
    const rows = ((globalThis as { ListingPush?: { rows?(n: string): unknown[] | null } }).ListingPush?.rows?.('list') ?? []) as Array<{
        session_uuid?: string | null; tmux_session?: string | null; project_id?: number | null; project_name?: string | null;
        session?: { session_uuid?: string | null; project_id?: number | null };
    }>;
    const row = rows.find((r) => (uuid && (r.session_uuid === uuid || r.session?.session_uuid === uuid)) || (r.tmux_session && r.tmux_session === tmuxName));
    return { id: row?.project_id ?? row?.session?.project_id ?? null, name: row?.project_name ?? null };
}

function sendToNodes(ctx: RowMenuCtx, env: ItemMenuEnv): MenuNode[] {
    const first = !packMachines.data;
    void packMachines.refresh(true).then(() => { if (first && packMachines.data) env.refresh?.(); });
    const subject = {
        sessionUuid: ctx.sessionUuid,
        name: ctx.label || ctx.name,
        projectName: async (): Promise<string | null> => {
            // own project
            const listed = pushedProject(ctx.sessionUuid, ctx.name);
            const projectId = ctx.projectId ?? listed.id;
            if (projectId == null && listed.name) return listed.name;
            const getProjects = g().API?.getProjects;
            if (projectId == null || typeof getProjects !== 'function') return listed.name;
            try {
                const projects = await getProjects();
                return (Array.isArray(projects) ? projects.find((p) => p && p.id === projectId)?.name : null) || listed.name;
            } catch (err) {
                console.error('[item-menu] could not read projects for send to:', err);
                return null;
            }
        },
    };
    return computerNodes(packMachines.data?.machines ?? [], subject, () => undefined);
}

function branchChildren(id: string, ctx: RowMenuCtx, env: ItemMenuEnv): MenuNode[] {
    if (id === 'send-to') return ctx.sessionUuid ? sendToNodes(ctx, env) : [];
    if (ctx.kind === 'layout') return addToNodes.forLayout(ctx.layoutUuid || '');
    return addToNodes.forSession(ctx.name, ctx.sessionUuid || null);
}

function runNative(id: string, ctx: RowMenuCtx): void {
    const actions = g().SessionRowMenuActions;
    if (!actions) {
        console.error(`[item-menu] SessionRowMenuActions is missing - "${id}" cannot run`);
        return;
    }
    Promise.resolve(actions.run(id, ctx)).catch((err: unknown) => console.error(`[item-menu] "${id}" failed:`, err));
}

export function rowNodes(ctx: RowMenuCtx, env: ItemMenuEnv): MenuNode[] {
    return rowMenuItems(ctx).map((item): MenuNode => {
        const html = env.glyph(item.id);
        const node: MenuNode = { id: item.id, label: item.label, ...(html ? { glyphHtml: html } : {}) };
        if (item.separatorBefore) node.sep = true;
        if (!item.enabled) node.blocked = item.reason;
        if (item.tone) node.tone = item.tone;
        if (item.locked) node.locked = item.locked;
        if (BRANCH_ITEM_IDS.includes(item.id)) {
            node.children = item.enabled ? branchChildren(item.id, ctx, env).map((child) => withClose(child, env.close)) : [];
            return node;
        }
        if (item.id === 'copy-session-id') {
            node.flash = {
                done: t('session.menu.copy_session_id.done'),
                run: () => g().SessionRowMenuActions?.runCopySessionId?.(ctx) ?? Promise.resolve(false),
            };
            return node;
        }
        node.run = item.plugin
            ? () => { env.close(); void runPluginItem(item.id, ctx as unknown as Record<string, unknown>); }
            : () => { env.close(); runNative(item.id, ctx); };
        return node;
    });
}

function withClose(node: MenuNode, close: () => void): MenuNode {
    if (node.children) return { ...node, children: node.children.map((c) => withClose(c, close)) };
    const run = node.run;
    if (!run) return node;
    return { ...node, run: () => { try { run(); } finally { close(); } } };
}

const ariaLabel = (ctx: RowMenuCtx): string => `actions for ${ctx.label || ctx.name}`;

for (const type of ['session', 'browser', 'page', 'file', 'layout'] as const satisfies readonly RowMenuType[]) {
    defineItemMenu(type, {
        build(ctx, env) {
            if (!ctx || !ctx.name) return null;
            return { nodes: rowNodes(ctx, env), ariaLabel: ariaLabel(ctx) };
        },
    });
}
