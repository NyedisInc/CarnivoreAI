import { clock, startClock } from '../../lib/frozen-clock.svelte';
import { followTimeZone, readTimeZone } from '../../../lib/time-zone/time-zone';
import type { TaskClock } from '../../../cplugs/sdk/task-clock';

export class TaskAgeClock implements TaskClock {
  private readonly frozenAt = clock.frozen ? Date.now() : null;
  readonly nowSec = $derived.by(() => {
    void clock.now;
    return (this.frozenAt ?? Date.now()) / 1000;
  });
  readonly minuteSec = $derived(Math.floor(this.nowSec / 60) * 60);
  zone = $state(readTimeZone());

  wording(): TaskClock {
    return { nowSec: this.minuteSec, zone: this.zone };
  }

  hold(): () => void {
    const stopClock = startClock();
    this.zone = readTimeZone();
    const stopZone = followTimeZone((zone) => (this.zone = zone));
    return () => {
      stopClock();
      stopZone();
    };
  }
}
