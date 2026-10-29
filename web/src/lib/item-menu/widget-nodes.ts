import type { MenuNode } from '../drawer-tabs/add-component-menu';
import type { WidgetMenuCtx } from '../widget-menu/model';
import './menus/widget';
import { itemMenu } from './registry';

export function widgetMenuNodes(ctx: WidgetMenuCtx): MenuNode[] {
    return itemMenu('widget', ctx, { close: ctx.onClose, glyph: () => '' })?.nodes ?? [];
}
