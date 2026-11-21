
import { motionReduced, watchMotion } from '../../../../lib/motion/motion';

let reduced = $state(false);

function watch(): void {
  reduced = motionReduced();
  watchMotion((now) => {
    reduced = now;
  });
}

export function reducedMotion(): boolean {
  return reduced;
}

watch();
