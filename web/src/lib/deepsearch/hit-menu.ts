import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { t } from '../i18n/index.svelte';
import type { DeepSearchController } from './deepsearch.svelte';
import type { DeepGroup, DeepHit } from './deepsearch-api';
import { hitActions, splitActions, type ActionId, type ConvState } from './result-model';

const MENU_ORDER: readonly ActionId[] = ['read', 'go', 'resume', 'branch', 'link', 'bookmark', 'scope', 'closest'];
const PRIMARY: readonly ActionId[] = ['read', 'go', 'resume'];
const MENU_HINT: Partial<Record<ActionId, string>> = { read: 'enter', go: 'cmd enter', resume: 'cmd enter' };

export function runHitAction(controller: DeepSearchController, group: DeepGroup, hit: DeepHit, name: string, id: ActionId): void {
  if (id === 'read') void controller.pickHit(group, hit, name);
  else if (id === 'go' || id === 'resume') void controller.go(group);
  else if (id === 'branch') void controller.branch(group, hit);
  else if (id === 'link') void controller.copyLink(group, hit);
  else if (id === 'bookmark') void controller.bookmark(group, hit);
  else if (id === 'scope') controller.scopeTo(group, name);
  else if (id === 'closest') controller.showContext(group, hit, 'bookmark', name);
}

export function hitMenuNodes(controller: DeepSearchController, group: DeepGroup, hit: DeepHit, conv: ConvState, name: string): MenuNode[] {
  const ids = hitActions(conv, group, hit);
  if (splitActions(ids).menu.length === 0) return [];
  return MENU_ORDER.filter((id) => ids.includes(id)).map((id, i, all): MenuNode => ({
    id,
    label: t(`deepsearch.action.${id}`),
    hint: MENU_HINT[id],
    sep: i > 0 && !PRIMARY.includes(id) && PRIMARY.includes(all[i - 1]!) ? true : undefined,
    run: () => runHitAction(controller, group, hit, name, id),
  }));
}
