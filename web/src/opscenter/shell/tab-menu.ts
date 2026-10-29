/* running sessions */
import type { ProjectResponse, SessionInfo } from '../api/types';
import { bucketByProject, type MenuNode } from '../../lib/drawer-tabs/add-component-menu';
import { t } from '../../lib/i18n/index.svelte';
import { agentMarkFacts } from '../../lib/sessions/agent-marks';
import type { Blueprint } from '../../lib/blueprints/types';
import { isAsleepRow } from '../cells/running-sessions/asleep';
import type { PageMenuRow } from '../cells/terminal-group/page-tab-item';

export interface TabMenuInputs {
  rows: readonly SessionInfo[];
  name: (row: SessionInfo) => string;
  open: (sessionId: string) => void;
  wake: (row: SessionInfo) => void;
  newAgent: () => void;
  openBlueprints: () => void;
  blueprints: readonly Blueprint[];
  launchBlueprint: (blueprint: Blueprint) => void;
  newAgentInProject: (project: ProjectResponse) => void;
  newTerminal: () => void;
  openSessionIds: ReadonlySet<string>;
  layoutSessionIds: readonly string[];
  pages?: readonly PageMenuRow[] | null;
  openPage?: (browserId: string) => void;
  newBrowser?: () => void;
  widgets?: readonly MenuNode[] | null;
  projects: readonly ProjectResponse[];
}

export function buildTabMenu(input: TabMenuInputs): MenuNode[] {
  const available = input.rows.filter(
    (row) => row.agent_family !== 'shell' && !input.openSessionIds.has(row.session.id),
  );
  const projectByKey = new Map<string, ProjectResponse>(
    input.projects
      .filter((p): p is ProjectResponse & { id: number } => p.id !== null && p.id !== undefined)
      .map((p) => [`p:${p.id}`, p]),
  );
  const buckets = bucketByProject(available, '', input.projects);
  const rogue = buckets.filter((b) => b.key === 'rogue');
  const sortName = (label: string): string => label.replace(/^[^\p{L}\p{N}]+/u, '') || label;
  const byName = (a: { label: string }, b: { label: string }) =>
    sortName(a.label).localeCompare(sortName(b.label), undefined, { sensitivity: 'base' });
  const named = buckets.filter((b) => b.key !== 'rogue');
  const awake = input.rows.filter((row) => row.agent_family !== 'shell' && !isAsleepRow(row));
  const layoutOrder = new Map<string, number>();
  input.layoutSessionIds.forEach((id, i) => layoutOrder.has(id) || layoutOrder.set(id, i));
  const firstTab = new Map<string, number>();
  for (const row of awake) {
    const at = layoutOrder.get(row.session.id);
    if (at === undefined) continue;
    const key = bucketByProject([row], '').map((b) => b.key)[0];
    if (key === undefined) continue;
    firstTab.set(key, Math.min(at, firstTab.get(key) ?? at));
  }
  const openKeys = new Set(bucketByProject(awake, '').map((b) => b.key));
  const inLayout = named.filter((b) => firstTab.has(b.key)).sort((a, b) => firstTab.get(a.key)! - firstTab.get(b.key)!);
  const open = named.filter((b) => openKeys.has(b.key) && !firstTab.has(b.key)).sort(byName);
  const rest = [...named.filter((b) => !openKeys.has(b.key) && !firstTab.has(b.key)).sort(byName), ...rogue];
  const starts = new Set([inLayout, open, rest].flatMap((g) => (g[0] ? [g[0].key] : [])));
  const projects: MenuNode[] = [...inLayout, ...open, ...rest].map((bucket) => {
    const project = projectByKey.get(bucket.key);
    const newHere: MenuNode[] = project
      ? [{ id: `agent/${bucket.key}/new`, label: t('opscenter.tabs.new_agent'), run: () => input.newAgentInProject(project) }]
      : [];
    return {
      id: `agent/${bucket.key}`,
      label: bucket.label,
      ...(starts.has(bucket.key) ? { sep: true } : {}),
      children: [
        ...newHere,
        ...bucket.rows.map((row) => {
          const id = row.session.id;
          const asleep = isAsleepRow(row);
          return {
            id: `agent/${bucket.key}/${id}`,
            label: input.name(row),
            agent: asleep ? { ...agentMarkFacts(row), status: 'asleep' } : agentMarkFacts(row),
            ...(asleep ? { badge: t('session.asleep.label') } : {}),
            run: asleep ? () => input.wake(row) : () => input.open(id),
          };
        }),
      ],
    };
  });
  const newAgent: MenuNode = { id: 'agent/new', label: t('opscenter.tabs.new_agent'), run: input.newAgent };
  const browser = t('drawer.new.browser');
  const pages = input.pages;
  const browserNode: MenuNode = pages && input.newBrowser && input.openPage
    ? {
        id: 'browser',
        label: browser,
        children: [
          { id: 'browser/new', label: t('opscenter.tabs.new_browser'), run: input.newBrowser },
          ...pages.map((row, i) => ({
            id: `browser/${row.id}`,
            label: row.label,
            ...(i === 0 ? { sep: true } : {}),
            run: () => input.openPage?.(row.id),
          })),
        ],
      }
    : { id: 'browser', label: browser, blocked: browser };
  const widgetLabel = t('opscenter.tabs.widget');
  const widgetNode: MenuNode = input.widgets
    ? { id: 'widget', label: widgetLabel, children: [...input.widgets] }
    : { id: 'widget', label: widgetLabel, blocked: t('opscenter.tabs.widget_phone') };
  return [
    { id: 'agent', label: t('drawer.new.agent'), children: [newAgent, ...projects] },
    { id: 'terminal', label: t('drawer.new.terminal'), run: input.newTerminal },
    { id: 'blueprint', label: t('blueprint.title'), children: buildBlueprintChildren(input.blueprints, input.launchBlueprint, input.openBlueprints) },
    browserNode,
    widgetNode,
  ];
}

export function buildBlueprintChildren(
  blueprints: readonly Blueprint[],
  launch: (blueprint: Blueprint) => void,
  manage: () => void,
): MenuNode[] {
  const items: MenuNode[] = blueprints.length
    ? blueprints.map((bp) => ({ id: `blueprint/${bp.blueprint_uuid}`, label: bp.name, run: () => launch(bp) }))
    : [{ id: 'blueprint/empty', label: t('blueprint.empty'), blocked: t('blueprint.empty') }];
  return [...items, { id: 'blueprint/manage', label: t('opscenter.frame.view_all'), sep: true, run: manage }];
}
