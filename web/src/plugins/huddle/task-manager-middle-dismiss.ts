import { isDismissTarget } from './task-manager-posts';

export function isMiddleDismiss(event: Pick<MouseEvent, 'button' | 'target'>): boolean {
  return event.button === 1 && isDismissTarget(event.target as Element | null);
}

export function cancelMiddleScroll(event: MouseEvent): void {
  if (isMiddleDismiss(event)) event.preventDefault();
}

export function onMiddleDismiss(event: MouseEvent, dismiss: () => void): void {
  if (!isMiddleDismiss(event)) return;
  event.preventDefault();
  dismiss();
}
