import type { MotionHandle } from '../../lib/motion-grid/types';

export function createEnableGate(handle: Pick<MotionHandle, 'setEnabled' | 'isBusy' | 'on'>): (on: boolean) => void {
  let want = false;
  let waiting = false;
  const apply = (): void => {
    if (handle.isBusy()) {
      if (waiting) return;
      waiting = true;
      const off = handle.on('settle', () => {
        off();
        waiting = false;
        apply();
      });
      return;
    }
    handle.setEnabled(want);
  };
  return (on) => {
    want = on;
    apply();
  };
}
