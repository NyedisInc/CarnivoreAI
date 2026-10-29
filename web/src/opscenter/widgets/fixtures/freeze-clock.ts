/* the widgets page */
import { FROZEN_NOW } from './clock';

export function freezeClock(): void {
  const RealDate = Date;
  class FrozenDate extends RealDate {
    constructor(...args: unknown[]) {
      if (args.length === 0) super(FROZEN_NOW);
      else super(...(args as [string | number | Date]));
    }
    static override now(): number {
      return FROZEN_NOW;
    }
  }
  globalThis.Date = FrozenDate as DateConstructor;
}
