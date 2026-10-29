export { inField } from '../feed/feed-keys';

export type ReviewKeyAction = 'next' | 'prev' | 'open' | 'good';

export interface ReviewKeyLike {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
}

export function reviewKeyAction(e: ReviewKeyLike, onButton: boolean): ReviewKeyAction | null {
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  if (e.key === 'j') return 'next';
  if (e.key === 'k') return 'prev';
  if (e.key === 'Enter') return onButton ? null : 'open';
  if (e.key === 'r') return 'good';
  return null;
}
