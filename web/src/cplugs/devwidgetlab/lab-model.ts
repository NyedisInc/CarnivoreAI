import type { LabHost, LabSize, SidebarView } from '../sdk/widget-lab';
import type { FixtureChoice } from './frame-url';

export function defaultSize(host: LabHost): LabSize | null {
  return host.sizes.find((size) => size.name === 'm') ?? host.sizes[0] ?? null;
}

export function sizeLine(size: LabSize): string {
  return `${size.name} ${size.w} x ${size.h ?? 'auto'}`;
}

export interface CaptureRequest {
  widget: string;
  host: string;
  size: string;
  theme: string;
  fixture: FixtureChoice;
  state: 'normal' | 'menu';
  scenario?: string;
  sidebar?: SidebarView;
}

/* the real left sidebar */
export function captureRequest(
  draw: { widget: string; host: string; size: string; theme: string; fixture: FixtureChoice },
  scenario: string | null,
  state: 'normal' | 'menu' = 'normal',
  sidebar: SidebarView | null = null,
): CaptureRequest {
  return { ...draw, state, ...(scenario === null ? {} : { scenario }), ...(sidebar ? { sidebar } : {}) };
}

export interface CaptureOutcome {
  ok: boolean;
  /* could not */
  determined: boolean;
  failures: string[];
  widget?: string;
  host?: string;
  theme?: string;
  state?: string;
  size?: { name: string; w?: number; h?: number | null; viewport?: number };
  png?: { path: string; pixels: number[] | null };
  metadata?: string;
}

export interface FitCell {
  verdict: 'pass' | 'fail' | 'unsupported';
  red: boolean;
  draws: number;
  reasons: string[];
}

export interface FitRow {
  widget: string;
  ok: boolean;
  determined: boolean;
  failures: number;
  cells: Record<string, FitCell>;
}

export interface FitTable {
  schema: number;
  generated_at: string;
  hosts: Record<string, string[]>;
  counts: { pass: number; fail: number; unsupported: number };
  widgets: FitRow[];
}

export interface MatrixState {
  available: boolean;
  reason: string;
  running: boolean;
  started: string | null;
  /* could not */
  exit: number | null;
  table: FitTable | null;
}

export interface FitColumn {
  host: string;
  size: string;
  key: string;
}

export function fitColumns(table: FitTable): FitColumn[] {
  return Object.entries(table.hosts).flatMap(([host, sizes]) => sizes.map((size) => ({ host, size, key: `${host}/${size}` })));
}

/* could not be determined */
export function cellState(row: FitRow, key: string): 'red' | 'fail' | 'pass' | 'unsupported' {
  const cell = row.cells[key];
  if (!row.determined) return 'fail';
  if (!cell || cell.verdict === 'unsupported') return 'unsupported';
  if (cell.verdict === 'fail') return cell.red ? 'red' : 'fail';
  return 'pass';
}

export type WidgetVerdict = 'pass' | 'fail' | 'none';

export function widgetOf(key: string): string {
  return key.startsWith(DRAFT_KEY_PREFIX) ? key : key.split(':')[0]!;
}

/* label: ' */
export function distinctWidgets(leaves: readonly { key: string }[]): number {
  return new Set(leaves.map((leaf) => widgetOf(leaf.key))).size;
}

function rowFor(table: FitTable | null, key: string): FitTable['widgets'][number] | undefined {
  return table?.widgets.find((one) => one.widget === key) ?? table?.widgets.find((one) => one.widget === widgetOf(key));
}

/* could not */
export function widgetVerdict(table: FitTable | null, key: string): WidgetVerdict {
  const row = rowFor(table, key);
  if (!row) return 'none';
  if (!row.determined) return 'fail';
  const states = Object.keys(row.cells).map((cell) => cellState(row, cell));
  if (states.some((state) => state === 'fail' || state === 'red')) return 'fail';
  return states.includes('pass') ? 'pass' : 'none';
}

export interface WidgetStatus {
  verdict: WidgetVerdict;
  failures: number;
}

export function widgetStatus(table: FitTable | null, key: string): WidgetStatus {
  const verdict = widgetVerdict(table, key);
  const row = rowFor(table, key);
  return { verdict, failures: verdict === 'fail' ? (row?.failures ?? 0) : 0 };
}

export interface TreeLeaf {
  key: string;
  label: string;
  tag?: string;
  status?: string;
  statusKey?: string;
  category?: string;
  categoryLabel?: string;
}

export const DRAFT_KEY_PREFIX = 'draft:';

export interface TreeGroup {
  id: string;
  label: string;
  leaves: TreeLeaf[];
  open?: boolean;
}

export const OTHER_GROUP = 'other';

export function treeGroups(
  widgets: readonly { key: string; title: string; category: string }[],
  label: (category: string) => string,
  order: readonly string[],
): TreeGroup[] {
  const ids = [...order, OTHER_GROUP];
  const groups = ids.map((id): TreeGroup => ({ id, label: label(id), leaves: [] }));
  for (const widget of widgets) {
    const group = groups.find((one) => one.id === widget.category) ?? groups[groups.length - 1]!;
    group.leaves.push({ key: widget.key, label: widget.title });
  }
  return groups.filter((group) => group.leaves.length > 0);
}

export function sizeChoices(hosts: readonly LabHost[]): string[] {
  const names: string[] = [];
  for (const host of hosts) if (host.supported) for (const size of host.sizes) if (!names.includes(size.name)) names.push(size.name);
  return names;
}

export function sizesToDraw(host: LabHost, picked: readonly string[]): LabSize[] {
  const chosen = host.sizes.filter((size) => picked.includes(size.name));
  const fallback = defaultSize(host);
  return chosen.length > 0 ? chosen : fallback ? [fallback] : [];
}

export type FrameVerdict = 'pass' | 'fail' | 'clip';

/* the widget does not declare it */
export function frameVerdict(table: FitTable | null, widget: string, host: string, size: string): { verdict: FrameVerdict; reasons: string[] } | null {
  const row = table?.widgets.find((one) => one.widget === widget);
  if (!row) return null;
  const state = cellState(row, `${host}/${size}`);
  if (state === 'unsupported') return null;
  const reasons = !row.determined ? [] : (row.cells[`${host}/${size}`]?.reasons ?? []);
  return { verdict: state === 'red' ? 'clip' : state, reasons };
}

export type ResultFilter = 'all' | 'failing' | 'unchecked';

export function filterGroups(groups: readonly TreeGroup[], query: string, result: ResultFilter, table: FitTable | null): TreeGroup[] {
  const needle = query.trim().toLowerCase();
  if (needle === '' && result === 'all') return [...groups];
  return groups
    .map((group) => ({
      ...group,
      leaves: group.leaves.filter(
        (leaf) =>
          (needle === '' || `${leaf.label} ${leaf.key} ${group.label}`.toLowerCase().includes(needle)) &&
          (result === 'all' || (result === 'failing' ? widgetVerdict(table, leaf.key) === 'fail' : widgetVerdict(table, leaf.key) === 'none')),
      ),
    }))
    .filter((group) => group.leaves.length > 0);
}

export function uncheckedCount(groups: readonly TreeGroup[], table: FitTable | null): number {
  return groups.reduce((sum, group) => sum + distinctWidgets(group.leaves.filter((leaf) => widgetVerdict(table, leaf.key) === 'none')), 0);
}

export function failingCount(table: FitTable | null): number {
  return (table?.widgets ?? []).filter((row) => widgetVerdict(table, row.widget) === 'fail').length;
}
