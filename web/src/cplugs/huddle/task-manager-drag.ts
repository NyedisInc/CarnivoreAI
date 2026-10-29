export function followGrip(event: PointerEvent, onMove: (y: number, x: number) => void, onEnd: (dropped: boolean) => void): void {
  const grip = event.currentTarget as HTMLElement | null;
  grip?.setPointerCapture?.(event.pointerId);
  const moved = (e: PointerEvent): void => onMove(e.clientY, e.clientX);
  let done = false;
  const finish = (dropped: boolean): void => {
    if (done) return;
    done = true;
    window.removeEventListener('keydown', key, true);
    grip?.removeEventListener('pointermove', moved);
    grip?.removeEventListener('pointerup', up);
    grip?.removeEventListener('pointercancel', cancel);
    onEnd(dropped);
  };
  const up = (): void => finish(true);
  const cancel = (): void => finish(false);
  const key = (e: KeyboardEvent): void => {
    if (e.key !== 'Escape') return;
    e.preventDefault();
    e.stopPropagation();
    finish(false);
  };
  window.addEventListener('keydown', key, true);
  grip?.addEventListener('pointermove', moved);
  grip?.addEventListener('pointerup', up);
  grip?.addEventListener('pointercancel', cancel);
}
