import { harnessWidgets, type HarnessWidget } from '../../widget-harness/catalog';
import { manifestById } from '../../opscenter/widgets/core-manifests';
import { suggestedSizes } from '../../opscenter/widgets/fits';
import { standardSizes } from '../../opscenter/widgets/standard-sizes';
import { GLANCE_TILE_HEIGHT_PX } from '../../lib/drawer-zone/glance';
import { PRESETS, presetTitleKey } from '../../opscenter/viz/presets';
import { t } from '../../lib/i18n/index.svelte';
import { WIDGET_CATEGORIES, type FitZone } from '../../opscenter/widgets/types';

export { parseScenario, MAX_SCENARIO_CHARS } from '../../widget-harness/scenario';
export type { ScenarioResult } from '../../widget-harness/scenario';
export { DEFAULT_SIDEBAR_VIEW, SIDEBAR_AREAS, SIDEBAR_DENSITIES, SIDEBAR_WIDTHS, viewToQuery } from '../../widget-harness/sidebar/sidebar-state';
export type { SidebarArea, SidebarDensity, SidebarView, SidebarWidth } from '../../widget-harness/sidebar/sidebar-state';
export { KEY_MENU_MESSAGE, readKeyMenuMessage } from '../../widget-harness/key-menu-message';
export type { KeyMenuMessage } from '../../widget-harness/key-menu-message';

export const LAB_CATEGORIES: readonly string[] = WIDGET_CATEGORIES;

export const LAB_HOSTS: readonly FitZone[] = ['home', 'terminal', 'drawer', 'popout'];

export type HostRefusal = 'canvas' | 'popout';

export interface LabSize {
  name: string;
  w: number;
  h: number | null;
  viewport: number;
  declared: boolean;
  floor: boolean;
}

export interface LabHost {
  zone: FitZone;
  supported: boolean;
  refusal: HostRefusal | null;
  sizes: LabSize[];
}

export interface LabWidget {
  key: string;
  title: string;
  manifest: string;
  category: string;
  icon?: LabIcon;
  hosts: LabHost[];
}

export interface LabIcon {
  name: string;
  tone: string;
}

export interface IdleReport {
  shown: { requests: number };
  hidden: { requests: number };
  shell: number;
  hiddenRoutes: Record<string, number>;
  failures: string[];
}

export interface FrameReport {
  ready: boolean;
  error: string;
  misses: string[];
  result?: {
    error: string;
    findings: { rule: string; selector: string; px: number; detail: string }[];
    misses: string[];
    text: string;
    hasFixture: boolean;
    fixtureJson: string;
    unusedScenarioRoutes: string[];
    plate: boolean;
    menu: { asked: boolean; open: boolean; reason: string };
    clip?: { w: number; h: number } | null;
  };
}

function refusalFor(canvases: readonly string[], zone: FitZone): HostRefusal | null {
  if (zone === 'drawer') return null;
  if (zone === 'popout') return canvases.includes('home') ? null : 'popout';
  return canvases.includes(zone) ? null : 'canvas';
}

function labWidget(widget: HarnessWidget): LabWidget {
  const manifest = manifestById(widget.manifest);
  const canvases = manifest?.canvases ?? [];
  const preset = PRESETS.find((one) => widget.key === `core.analytics:${one.id}`);
  const title = preset ? `${t(manifest?.titleKey ?? '')} / ${t(presetTitleKey(preset))}` : manifest ? t(manifest.titleKey) : widget.key;
  const hosts = LAB_HOSTS.map((zone): LabHost => {
    const refusal = refusalFor(canvases, zone);
    const sizes = (widget.sizes[zone === 'popout' ? 'home' : zone] ?? []).map((size): LabSize => ({
      name: size.name, w: size.w, h: size.h, viewport: size.viewport, declared: size.declared === true, floor: size.name === 's',
    }));
    return { zone, supported: refusal === null && sizes.length > 0, refusal, sizes };
  });
  return { key: widget.key, title, manifest: widget.manifest, category: manifest?.category ?? '', ...(manifest ? { icon: { name: manifest.icon, tone: manifest.iconTone } } : {}), hosts };
}

export function labWidgets(): LabWidget[] {
  return harnessWidgets().map(labWidget);
}

export interface LabDraftManifest {
  id: string;
  title: string;
  hosts: string[];
  fits: { sizes: string[] };
  cell: { minPx: number; minHeight: number; icon?: string; iconTone?: string };
  category?: string;
}

export function draftLabWidget(manifest: LabDraftManifest): LabWidget {
  const named = suggestedSizes({ sizes: manifest.fits.sizes as never });
  const floor = { minPx: manifest.cell.minPx, minHeight: manifest.cell.minHeight };
  const hosts = LAB_HOSTS.map((zone): LabHost => {
    const supported = manifest.hosts.includes(zone);
    const sizes = supported ? standardSizes(floor, zone === 'popout' ? 'home' : zone, GLANCE_TILE_HEIGHT_PX, named) : [];
    return {
      zone, supported, refusal: supported ? null : zone === 'popout' ? 'popout' : 'canvas',
      sizes: sizes.map((size): LabSize => ({ name: size.name, w: size.w, h: size.h, viewport: size.viewport, declared: size.declared === true, floor: size.name === 's' })),
    };
  });
  const icon = manifest.cell.icon ? { icon: { name: manifest.cell.icon, tone: manifest.cell.iconTone ?? 'oc-text-secondary' } } : {};
  return { key: manifest.id, title: manifest.title, manifest: manifest.id, category: manifest.category ?? '', ...icon, hosts };
}

export { MENU_CHOOSE, MENU_CLOSE, MENU_HIDE, MENU_SHOW, readMenuMessage } from '../../lib/drawer-tabs/menu-remote-messages';
export type { MenuChooseMessage, MenuCloseMessage, MenuHideMessage, MenuShowMessage } from '../../lib/drawer-tabs/menu-remote-messages';
export type { WireNode } from '../../lib/drawer-tabs/menu-remote';
