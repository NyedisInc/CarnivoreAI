import { draftLabWidget, type LabDraftManifest, type LabWidget } from '../sdk/widget-lab';
import { DRAFT_KEY_PREFIX, OTHER_GROUP, type TreeGroup } from './lab-model';

export type DraftState = 'starter' | 'working' | 'building' | 'built' | 'failed';

export interface DraftBuild {
  state: 'none' | 'building' | 'built' | 'failed';
  sha: string | null;
  built_at: string | null;
  log: string | null;
  error: string;
}

export interface DraftSummary {
  slug: string;
  kind: 'new' | 'revision';
  widget: string;
  title: string;
  created: string;
  state: DraftState;
  base_sha: string;
  session: string | null;
  files: string[];
  build: DraftBuild;
  manifest: (LabDraftManifest & Record<string, unknown>) | null;
  stale: boolean;
  build_stale: boolean;
  code: DraftCode;
}

export interface DraftCode {
  app: string;
  build: string;
  source: string;
}

const SHORT_SHA = 7;

export function codeGap(code: DraftCode | undefined): { app: string; build: string } | null {
  if (!code?.app || !code.build) return null;
  const app = code.app.slice(0, SHORT_SHA);
  const build = code.build.slice(0, SHORT_SHA);
  return code.app.startsWith(build) || code.build.startsWith(app) ? null : { app, build };
}

export interface DraftSource {
  root: string;
  origin: 'setting' | 'auto' | 'own_tree' | 'none';
  setting: string;
  problems: string[];
}

export interface DraftsState {
  available: boolean;
  reason: string;
  building: string | null;
  drafts: DraftSummary[];
  source: DraftSource;
}

export const NO_DRAFTS: DraftsState = { available: false, reason: 'unknown', building: null, drafts: [], source: { root: '', origin: 'none', setting: '', problems: [] } };

export interface DraftRequest {
  kind: 'new' | 'revision';
  widget?: string;
  name: string;
  what: string;
  hosts?: string[];
  sizes?: string[];
  category?: string;
  context?: Record<string, string>;
}

export const NEW_HOSTS = ['home', 'terminal', 'drawer', 'popout'] as const;
export const NEW_HOSTS_DEFAULT: readonly string[] = ['home', 'terminal'];
export const NEW_SIZES = ['small', 'wide', 'tall', 'medium', 'large', 'full'] as const;
export const NEW_CATEGORIES = ['overview', 'sessions', 'catalog', 'monitoring', 'tools', 'live'] as const;

export function rowPrefix(draft: DraftSummary): 'new' | 'rev' {
  return draft.kind === 'new' ? 'new' : 'rev';
}

export function stateWord(draft: DraftSummary): DraftState | 'stale' {
  if (draft.state === 'built' && draft.build_stale) return 'stale';
  return draft.state;
}

export function needsWatching(state: DraftsState): boolean {
  return state.building !== null || state.drafts.some((draft) => draft.state === 'building');
}

export function draftWidget(draft: DraftSummary, widgets: readonly LabWidget[]): LabWidget | undefined {
  if (draft.kind === 'revision') return widgets.find((one) => one.key === draft.widget);
  return draft.manifest ? draftLabWidget(draft.manifest) : undefined;
}

export function revisionContext(sel: { theme: string; fixture: string; hosts: readonly string[]; sizes: readonly string[]; scenarioRoutes: number }): Record<string, string> {
  return {
    theme: sel.theme,
    fixture: sel.fixture,
    hosts: sel.hosts.join(', '),
    sizes: sel.sizes.join(', '),
    scenario: sel.scenarioRoutes > 0 ? `${sel.scenarioRoutes} routes applied` : 'none',
  };
}

export function buildFailure(draft: DraftSummary): string {
  return draft.build.state === 'failed' ? draft.build.error || 'the build failed' : '';
}

export interface CompareDelta {
  kind: 'new' | 'waiting' | 'same' | 'more' | 'fewer';
  current: number;
  draft: number;
}

export function compareDelta(counts: Readonly<Record<string, number>>, frames: number, hasCurrent: boolean): CompareDelta {
  const keys = Object.keys(counts);
  const draftKeys = keys.filter((key) => key.endsWith('/draft'));
  const sum = (side: 'current' | 'draft'): number => keys.filter((key) => key.endsWith(`/${side}`)).reduce((all, key) => all + (counts[key] ?? 0), 0);
  if (!hasCurrent) return { kind: 'new', current: 0, draft: sum('draft') };
  const reported = keys.filter((key) => key.endsWith('/current')).length;
  if (reported < frames || draftKeys.length < frames) return { kind: 'waiting', current: sum('current'), draft: sum('draft') };
  const current = sum('current');
  const draft = sum('draft');
  return { kind: draft === current ? 'same' : draft > current ? 'more' : 'fewer', current, draft };
}

export function findingCount(report: { error: string; result?: { findings: unknown[] } } | null): number {
  if (report === null || report.error) return 1;
  return report.result?.findings.length ?? 0;
}

export const DRAFTS_GROUP_ID = 'drafts';

export function draftCategory(draft: DraftSummary, widgets: readonly { key: string; category: string }[], order: readonly string[]): string {
  const own = draft.kind === 'revision' ? widgets.find((one) => one.key === draft.widget)?.category : draft.manifest?.category;
  return own && order.includes(own) ? own : OTHER_GROUP;
}

export function draftsTreeGroup(
  drafts: readonly DraftSummary[],
  translate: (key: string, vars?: Record<string, string | number>) => string,
  widgets: readonly { key: string; category: string }[] = [],
  order: readonly string[] = [],
): TreeGroup {
  const rank = (id: string): number => (id === OTHER_GROUP ? order.length : order.indexOf(id));
  const filed = drafts.map((draft) => ({ draft, category: draftCategory(draft, widgets, order) }));
  filed.sort((a, b) => rank(a.category) - rank(b.category));
  return {
    id: DRAFTS_GROUP_ID,
    open: drafts.length > 0,
    label: translate('cplug.devwidgetlab.drafts.group', { count: drafts.length }),
    leaves: filed.map(({ draft, category }) => ({
      key: `${DRAFT_KEY_PREFIX}${draft.slug}`,
      label: draft.title,
      tag: translate(`cplug.devwidgetlab.drafts.prefix.${rowPrefix(draft)}`),
      status: translate(`cplug.devwidgetlab.drafts.state.${stateWord(draft)}`),
      statusKey: stateWord(draft),
      category,
      categoryLabel: category === OTHER_GROUP ? translate('cplug.devwidgetlab.tree.other') : translate(`widgets.page.category.${category}`),
    })),
  };
}

export const HOST_FILES: readonly string[] = ['widget.json', 'contract.json'];

export function withHost(text: string, host: string): string {
  const record = JSON.parse(text) as { hosts?: unknown };
  const hosts = Array.isArray(record.hosts) ? record.hosts.map(String) : [];
  return `${JSON.stringify({ ...record, hosts: hosts.includes(host) ? hosts : [...hosts, host] }, null, 2)}\n`;
}
