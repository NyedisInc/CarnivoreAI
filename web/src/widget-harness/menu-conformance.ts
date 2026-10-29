import { excusedForWidget } from '../opscenter/widgets/menu/menu-rules';

export interface MenuDrawFinding {
  rule: 'menu-button-in-body';
  selector: string;
  px: number;
  detail: string;
}

const HOST_CHROME = '[data-widget-head], .oc-frame-cornerwrap, .oc-frame-corner, .oc-frame-strip';

function describe(el: Element): string {
  const cls = [...el.classList].slice(0, 2).map((one) => `.${one}`).join('');
  const role = el.getAttribute('role');
  return `${el.tagName.toLowerCase()}${cls}${role ? `[role=${role}]` : ''}`;
}

export function menuConformance(cell: Element, widget: string): MenuDrawFinding[] {
  if (excusedForWidget(widget).has('body-menu-button')) return [];
  return [...cell.querySelectorAll('[aria-haspopup="menu"]')]
    .filter((button) => button.closest(HOST_CHROME) === null)
    .map((button) => ({ rule: 'menu-button-in-body' as const, selector: describe(button), px: 0,
      detail: 'a menu button in the widget body; its items belong in the one widget menu (docs/widget-spec.md section 11)' }));
}
