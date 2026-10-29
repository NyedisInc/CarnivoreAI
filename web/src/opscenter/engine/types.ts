
export type CellId =
  | 'stat-running'
  | 'stat-sessions'
  | 'stat-projects'
  | 'stat-ledger'
  | 'stat-alive'
  | 'stat-subagents'
  | 'running-sessions'
  | 'closed-sessions'
  | 'projects'
  | 'skills'
  | 'plugins'
  | 'themes'
  | 'ledger'
  | 'activity-log'
  | 'notes'
  | 'files'
  | 'scheduled-tasks'
  | 'keep-awake'
  | 'machine-stats'
  | 'changes'
  | 'task-manager'
  | 'task-manager-all'
  | 'crosstalk'
  | 'tasks'
  | 'tasks-all'
  | 'bookmarks'
  | 'bookmarks-all'
  | 'pipeline'
  | 'automations'
  | 'automations-all'
  | 'shell'
  | 'timeline'
  | 'questions'
  | 'developer'
  | 'task-list'
  | 'session-contents'
  | 'warroom'
  | 'task-manager-mk2'
  | 'task-manager-mk2-all';

export type InstanceKind = 'terminal' | 'browser' | 'analytics' | PluginKind;

export type PluginKind = `${string}.${string}`;

export type InstanceId = `terminal:${string}` | `browser:${string}` | `analytics:${string}` | `${PluginKind}:${string}`;

export type SlotId = CellId | InstanceId;

export type LayoutPage = 'home' | 'terminal' | 'warroom';

export type RowId = `r${number}`;

export type RowKind = 'px' | 'flex';

export interface Slot {
  id: SlotId;
  fr: number;
  span?: number;
}

export interface Reservation {
  of: SlotId;
  at: number;
}

export interface RowModel {
  id: RowId;
  kind: RowKind;
  size: number;
  slots: Slot[];
  reserved?: Reservation[];
}

/* no longer holds */
export interface Layout {
  v: 6;
  rows: RowModel[];
  hidden: SlotId[];
  heroCollapsed: boolean;
  collapsed: SlotId[];
  headerOff?: SlotId[];
}

export interface PhoneMark {
  tone: string;
  /* could not */
  shape?: 'solid' | 'hollow';
  count?: number | null;
  label: string;
}

export interface PhoneSummary {
  marks: PhoneMark[];
  note?: string;
}

export interface CellSize {
  name: string;
  min: number;
}

export type RightControl = 'view-all' | 'clear' | 'collapse' | 'refresh';

export interface CellMeta {
  id: SlotId;
  titleKey: string;
  titleShortKey?: string;
  titleName?: string;
  icon: string;
  iconTone: string;
  iconFill?: 'outline' | 'solid';
  rightControl?: RightControl;
  showCount: boolean;
  chrome: 'card' | 'bare';
  ownHead?: boolean;
  closable?: boolean;
  cornerSlot?: readonly [number, number, number];
  titleHeight: number;
  defaultRow: RowId;
  defaultIndex: number;
  defaultFr: number;
  defaultHeight: number;
  minPx: number;
  minHeight: number;
  widthStates: CellSize[];
  heightStates: CellSize[];
  phoneOrder: number;
  phoneCollapsedByDefault?: boolean;
  phoneCap?: number;
}

export type MetaMap = Readonly<Record<CellId, CellMeta>>;

export interface ColumnSpec {
  key: string;
  headKey: string;
  minPx: number;
  weight: number;
  align?: 'start' | 'end';
  tone?: string;
  /* running sessions */
  insetPx?: number;
  headInsetPx?: number;
  line?: 1 | 2;
  /* padding */
  minCh?: number;
}

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}
