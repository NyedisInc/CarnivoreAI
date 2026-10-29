
export type FeedKeyAction = 'next' | 'prev' | 'next_changed' | 'prev_changed' | 'next_unread' | 'toggle_fold' | 'search' | 'close_sheet';

export interface KeyLike {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
}

export function inField(target: EventTarget | null): boolean {
  const el = target as { tagName?: string; isContentEditable?: boolean } | null;
  return !!el && (/^(input|select|textarea)$/i.test(el.tagName ?? '') || el.isContentEditable === true);
}

export function feedKeyAction(e: KeyLike, o: { onList: boolean; sheetOpen: boolean }): FeedKeyAction | null {
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  switch (e.key) {
    case 'j':
      return 'next';
    case 'ArrowDown':
      return o.onList ? 'next' : null;
    case 'k':
      return 'prev';
    case 'ArrowUp':
      return o.onList ? 'prev' : null;
    case 'u':
      return 'next_changed';
    case 'U':
      return 'prev_changed';
    case 'n':
      return 'next_unread';
    case 'o':
      return 'toggle_fold';
    case '/':
      return 'search';
    case 'Escape':
      return o.sheetOpen ? 'close_sheet' : null;
    default:
      return null;
  }
}
