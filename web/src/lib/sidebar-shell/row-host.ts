import type { LayoutRowParts } from '../drawer/layouts-row-html';
import { contextFromRow, triggerSpec } from '../item-menu/row-context';
import type { SidebarRow } from './legacy';
import type { RowChipSpec } from './row-plan';

export type RowMenuContext = Record<string, unknown>;

export interface RowHost {
    label?: { resolve(row: SidebarRow): string | null };
    transport?: { stateFor(name: string): string };
    actions?: {
        offersMenu(status: unknown): boolean;
        specs(status: unknown, name: string, surfaceClass: string): RowChipSpec[];
    };
    menu?: {
        contextFromRow(row: SidebarRow, opts: Record<string, unknown>): RowMenuContext;
        triggerSpec(ctx: RowMenuContext): RowChipSpec;
    };
    autoSleep?: { isKeptAwake(name: string): boolean | null };
    layouts?: {
        rowParts(row: SidebarRow, band?: string): LayoutRowParts;
        memberBody?(row: SidebarRow, band?: string): {
            bodyId: string; uuid: string; band: string; members: SidebarRow[];
        } | null;
    };
}

interface HostGlobals {
    SessionLabel?: RowHost['label'];
    SessionTransport?: RowHost['transport'];
    SessionRowActions?: RowHost['actions'];
    SessionSidebarLayouts?: RowHost['layouts'];
    CloudeWeb?: { autoSleep?: RowHost['autoSleep'] };
}

const ROW_TRIGGER: NonNullable<RowHost['menu']> = {
    contextFromRow: (row, opts) => contextFromRow(row as unknown as Record<string, unknown>, opts) as unknown as RowMenuContext,
    triggerSpec: (ctx) => triggerSpec(ctx as Partial<import('../item-menu/row-context').RowMenuCtx>) as unknown as RowChipSpec,
};

export function rowHost(host: unknown = globalThis): RowHost {
    const g = host as HostGlobals;
    return {
        label: g.SessionLabel,
        transport: g.SessionTransport,
        actions: g.SessionRowActions,
        menu: ROW_TRIGGER,
        autoSleep: g.CloudeWeb?.autoSleep,
        layouts: g.SessionSidebarLayouts,
    };
}
