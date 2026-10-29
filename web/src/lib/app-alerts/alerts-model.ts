
export type Severity = 'info' | 'warn' | 'error';

export type AlertKind = 'needs_you' | 'fyi' | 'question';

export interface AlertAction {
  id: string;
  label_key: string;
  method?: string;
  route?: string;
  body?: unknown;
  href?: string;
  tone?: string;
  explain_key?: string;
  actions?: AlertAction[];
}

export interface AppAlert {
  id: number;
  key: string;
  source: string;
  severity: Severity;
  title_key: string;
  params: Record<string, string | number | boolean | null>;
  detail_key: string | null;
  state: 'active' | 'resolved' | 'dismissed' | 'snoozed';
  sticky: boolean;
  auto_resolve: boolean;
  first_seen: string;
  last_seen: string;
  count: number;
  resolved_at: string | null;
  dismissed_at: string | null;
  snoozed_until: string | null;
  actions: AlertAction[];
  source_label_key?: string | null;
  source_icon?: string | null;
  source_name?: string | null;
  kind?: AlertKind;
  notify_type?: string | null;
}

export interface AlertSourceEntry {
  id: string;
  label_key: string;
  icon: string;
}

export interface AlertCounts {
  error: number;
  warn: number;
  info: number;
}

export interface AlertFrame {
  type?: string;
  id?: number;
  key?: string;
  severity?: string;
  state?: string;
  count?: number;
}

export const FRAME_RAISED = 'app_alert.raised';
export const FRAME_UPDATED = 'app_alert.updated';
export const FRAME_RESOLVED = 'app_alert.resolved';
export const ALERT_FRAMES = [FRAME_RAISED, FRAME_UPDATED, FRAME_RESOLVED] as const;

export const RESOLVED_WINDOW_MS = 24 * 60 * 60 * 1000;

export function badgeFor(counts: AlertCounts | null | undefined): { count: number; severity: 'error' | 'warn' | null } {
  const error = Math.max(0, counts?.error ?? 0);
  const warn = Math.max(0, counts?.warn ?? 0);
  const count = error + warn;
  return { count, severity: error > 0 ? 'error' : warn > 0 ? 'warn' : null };
}

export function shouldToast(frame: AlertFrame, seen: Set<number>): boolean {
  if (frame.type !== FRAME_RAISED || typeof frame.id !== 'number') return false;
  if (seen.has(frame.id)) return false;
  seen.add(frame.id);
  return true;
}

export function panelSections(alerts: AppAlert[], now: number = Date.now()): { open: AppAlert[]; resolved: AppAlert[] } {
  const rank: Record<string, number> = { error: 0, warn: 1, info: 2 };
  const byNewest = (a: AppAlert, b: AppAlert): number => (b.last_seen > a.last_seen ? 1 : b.last_seen < a.last_seen ? -1 : 0);
  const open = alerts
    .filter((a) => a.state === 'active' || a.state === 'snoozed')
    .sort((a, b) => (rank[a.severity] ?? 3) - (rank[b.severity] ?? 3) || byNewest(a, b));
  const resolved = alerts
    .filter((a) => a.state === 'resolved' && a.resolved_at && now - Date.parse(a.resolved_at) <= RESOLVED_WINDOW_MS)
    .sort(byNewest);
  return { open, resolved };
}

export function kindOf(alert: Pick<AppAlert, 'kind' | 'severity'>): AlertKind {
  return alert.kind ?? (alert.severity === 'info' ? 'fyi' : 'needs_you');
}

export function primaryAction(alert: Pick<AppAlert, 'actions'>): AlertAction | null {
  return alert.actions[0] ?? null;
}

export function senderText(alert: Pick<AppAlert, 'source' | 'source_label_key' | 'source_name'>, translate: (key: string, params?: Record<string, string>) => string): string {
  const base = alert.source_label_key ? translate(alert.source_label_key) : alert.source.replace(/_/g, ' ');
  return alert.source_name ? translate('app_alert.row.source_named', { source: base, name: alert.source_name }) : base;
}
