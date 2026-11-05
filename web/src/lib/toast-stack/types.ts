
export type ToastRecord = Record<string, unknown>;

export interface ToastSessionLine {
  text: string;
  unknown: boolean;
  canNavigate: boolean;
}

export interface ToastCardView {
  uid: string;
  key: string;
  id: string;
  kind: string;
  severity: number;
  alertSeverity: string | null;
  count: number;
  badgeCount: number;
  color: string | null;
  role: 'alert' | 'status';
  mode: 'compact' | 'detailed';
  title: string;
  sleepIcon: string | null;
  session: ToastSessionLine;
  sessionId: string;
  body: string | null;
  actionLabel: string | null;
  thumbs: ToastRecord[] | null;
  canExpand: boolean;
  clickable: boolean;
  winner: ToastRecord;
  dismissing: boolean;
}

export interface ToastOverflowView {
  expanded: boolean;
  count: number;
  worst: number;
  worstCount: number | null;
}

export interface ToastView {
  cards: ToastCardView[];
  dismissAll: { total: number; blocking: number } | null;
  waiting: number | null;
  overflow: ToastOverflowView | null;
}

export interface ToastStackManager {
  subscribe(listener: (view: ToastView) => void): () => void;
  openGroup(key: string): void;
  clickSession(key: string): void;
  runCardAction(key: string): void;
  toggleOverflow(): void;
  dismissGroup(key: string): void;
  dismissAll(): number;
}
