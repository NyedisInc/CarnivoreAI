import { homeBoards } from '../engine/home-sync.svelte';
import { isWidgetId, openDashboardPopout, openHomePopout, openWallboard, openWidgetPopout, parseWidgetTarget } from '../../popout/popout';
import { openTabPopout } from '../../lib/dynamic-tabs/tab-popout';
import { popoutTabOn } from '../../lib/dynamic-tabs/popout-tabs';
import { cplugPopoutTabsOn } from '../../plugins/host/readers';
import { popoutWidgetFor } from '../../plugins/host/popout-widgets';
import { runtimePopoutTabDefs } from '../../lib/cplug-ui/plugin-tabs.svelte';
import { panelOf } from '../../lib/cplug-ui/panel-views.svelte';
import { resolveActiveSlots, runSlotDescriptorAction } from '../../lib/plugins/slot-actions';
import { manifestById } from '../widgets/core-manifests';
import { t } from '../../lib/i18n/index.svelte';

export type OpenTargetKind = 'home' | 'wallboard' | 'dashboard' | 'tab' | 'plugin';

export interface OpenTarget {
  id: string;
  kind: OpenTargetKind;
  label: string;
  board: string | null;
  open: () => void;
}

/* the home screen */
export function popOutHome(win: Window = window): Window | null {
  return homeBoards.ready ? openDashboardPopout(homeBoards.active, win) : openHomePopout(win);
}

export function otherDashboards(): { id: string; name: string }[] {
  return homeBoards.ready ? homeBoards.list.filter((board) => board.id !== homeBoards.active) : [];
}

export function openTargets(): OpenTarget[] {
  const active = homeBoards.ready ? (homeBoards.list.find((board) => board.id === homeBoards.active) ?? null) : null;
  return [
    {
      id: 'home',
      kind: 'home',
      label: active ? t('opscenter.open.home_named', { name: active.name }) : t('opscenter.open.home'),
      board: active?.id ?? null,
      open: () => void popOutHome(),
    },
    { id: 'wallboard', kind: 'wallboard', label: t('opscenter.open.wallboard'), board: null, open: () => void openWallboard() },
    ...otherDashboards().map((board) => ({
      id: `dashboard:${board.id}`,
      kind: 'dashboard' as const,
      label: board.name,
      board: board.id,
      open: () => void openDashboardPopout(board.id),
    })),
    ...(() => {
      const seen = new Set<string>();
      const tabs = [...cplugPopoutTabsOn(), ...runtimePopoutTabDefs()];
      return tabs
        .filter((def) => {
          if (seen.has(def.id)) return false;
          seen.add(def.id);
          return true;
        })
        .map((def) => ({
          id: `tab:${def.id}`,
          kind: 'tab' as const,
          label: t(def.labelKey, { count: 0 }),
          board: null,
          open: () => void openTabPopout(def.id, window, def.popoutParams?.(), def.popoutMulti === true),
        }));
    })(),
    ...(() => {
      const items: OpenTarget[] = [];
      for (const [idx, entry] of resolveActiveSlots('popout').entries()) {
        if (entry.kind !== 'descriptor' || entry.disabled) continue;
        const label = entry.title || entry.label || entry.id;
        if (!label) continue;
        const raw = entry.entry.item;
        const rawWidget = typeof raw.widget === 'string' ? raw.widget : '';
        const rawTab = typeof raw.tab === 'string' ? raw.tab : '';
        if (rawWidget) {
          if (!isWidgetId(rawWidget) || rawWidget.startsWith('core.')) continue;
          const { kind } = parseWidgetTarget(rawWidget);
          const panel = panelOf(kind);
          const compiled = popoutWidgetFor(rawWidget);
          if (panel?.popout !== true && compiled?.enabled !== true) continue;
          const fits = manifestById(kind)?.fits ?? { sizes: ['medium'], min: { w: 4, h: 4 }, anySize: true };
          items.push({
            id: `plugin:${entry.entry.plugin_id}:${entry.id || idx}`,
            kind: 'plugin',
            label,
            board: null,
            open: () => void openWidgetPopout(rawWidget, fits),
          });
        } else if (rawTab) {
          const targetTab = popoutTabOn(rawTab);
          if (!targetTab) continue;
          items.push({
            id: `plugin:${entry.entry.plugin_id}:${entry.id || idx}`,
            kind: 'plugin',
            label,
            board: null,
            open: () => void openTabPopout(targetTab.id, window, targetTab.popoutParams?.(), targetTab.popoutMulti === true),
          });
        } else if (entry.action) {
          const pluginId = entry.entry.plugin_id;
          const action = entry.action;
          items.push({
            id: `plugin:${pluginId}:${entry.id || idx}`,
            kind: 'plugin',
            label,
            board: null,
            open: () => {
              void runSlotDescriptorAction(pluginId, action, {
                confirm: entry.confirm,
                title: label,
                tone: entry.tone,
              }).catch((err: unknown) => console.error('[plugins] popout slot action failed', pluginId, entry.id, err));
            },
          });
        }
      }
      return items;
    })(),
  ];
}

export function menuRowPopout(id: string): (() => void) | null {
  const tab = openTargets().find((one) => one.kind === 'tab' && one.id === `tab:${id}`);
  return tab ? tab.open : null;
}
