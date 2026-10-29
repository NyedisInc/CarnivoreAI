import type { MenuNode } from '../drawer-tabs/add-component-menu';
import type { GhostAgent } from '../sidebar-shell/leader-ghost';
import type { WidgetMenuCtx } from '../widget-menu/model';
import type { RowMenuCtx } from './row-context';

export interface HeadingMenuCtx {
    key: string;
    anchor: Element;
}

export interface ColorMenuCtx {
    kind: 'group' | 'layout';
    id: string;
    anchor: Element;
}

export interface LeaderMenuCtx {
    ghost: GhostAgent;
    anchor: Element;
}

export interface PageRowCtx {
    label: string;
    nodes: MenuNode[];
}

export interface ItemMenuContexts {
    project: HeadingMenuCtx;
    company: HeadingMenuCtx;
    group: HeadingMenuCtx;
    color: ColorMenuCtx;
    leader: LeaderMenuCtx;
    widget: WidgetMenuCtx;
    pagerow: PageRowCtx;
    session: RowMenuCtx;
    browser: RowMenuCtx;
    page: RowMenuCtx;
    file: RowMenuCtx;
    layout: RowMenuCtx;
}

export type ItemMenuType = keyof ItemMenuContexts;

export interface BuiltItemMenu {
    nodes: MenuNode[];
    ariaLabel: string;
}

export interface ItemMenuEnv {
    close: () => void;
    glyph: (icon: string | undefined) => string;
    refresh?: () => void;
}

export interface ItemMenuTypeEntry<C> {
    build(ctx: C, env: ItemMenuEnv): BuiltItemMenu | null;
}

export interface ItemMenuContribution<C> {
    id: string;
    nodes(ctx: C, env: ItemMenuEnv): MenuNode[];
}
