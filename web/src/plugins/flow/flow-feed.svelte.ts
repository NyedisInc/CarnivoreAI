import { ApiError, authFetch, familyOf, resourcePush } from '../sdk';
import { TASK_MANAGER_LIST_FAMILY, deltaTouchesIds, followTaskManagerDelta } from '../sdk/task-manager-delta';
import { emptyFeed, feedItemIds, feedPath, mergeFeed, type FeedAnswer, type FeedItem, type FeedLane, type FlowSeed } from './flow-model';

export const WATCHED = new Set(['cplug.flow.feed', 'crosstalk', 'cplug.huddle.cards', '$live']);

export class FlowFeed {
  seed = $state<FlowSeed | null>(null);
  items = $state.raw<FeedItem[]>([]);
  lanes = $state.raw<Map<string, FeedLane>>(new Map());
  title = $state('');
  warnings = $state.raw<string[]>([]);
  error = $state<string | null>(null);
  loading = $state(false);
  appended = $state(0);

  private held = emptyFeed();
  private generation = 0;
  private inFlight = false;
  private dirty = false;
  private stopPush: (() => void) | null = null;

  open(seed: FlowSeed): void {
    this.generation += 1;
    this.seed = seed;
    this.held = emptyFeed();
    this.items = [];
    this.lanes = new Map();
    this.title = '';
    this.warnings = [];
    this.error = null;
    this.inFlight = false;
    this.dirty = false;
    void this.read();
  }

  start(): void {
    if (this.stopPush) return;
    const stopTopics = resourcePush().onChange((topics) => {
      if (this.seed && topics.some((topic) => WATCHED.has(familyOf(topic)))) this.schedule();
    });
    const stopDelta = followTaskManagerDelta({
      touches: (delta) => this.seed !== null && deltaTouchesIds(delta, feedItemIds(this.seed, this.items)),
      fallback: (topic) => this.seed !== null && familyOf(topic) === TASK_MANAGER_LIST_FAMILY,
      refresh: () => {
        if (this.seed) this.schedule();
      },
    });
    this.stopPush = () => {
      stopTopics();
      stopDelta();
    };
  }

  stop(): void {
    this.stopPush?.();
    this.stopPush = null;
    this.generation += 1;
    this.inFlight = false;
  }

  schedule(): void {
    if (this.inFlight) {
      this.dirty = true;
      return;
    }
    void this.read();
  }

  async read(): Promise<void> {
    const seed = this.seed;
    if (!seed) return;
    const generation = this.generation;
    this.inFlight = true;
    this.dirty = false;
    if (this.held.cursor === null) this.loading = true;
    try {
      const answer = await authFetch<FeedAnswer>(feedPath(seed, this.held));
      if (generation !== this.generation) return;
      const { resync, added } = mergeFeed(this.held, answer);
      if (resync) {
        this.held.cursor = null;
        this.dirty = true;
      }
      this.items = this.held.ordered;
      this.lanes = this.held.lanes;
      this.title = answer.seed?.title ?? '';
      this.warnings = Array.isArray(answer.warnings) ? answer.warnings : [];
      this.error = null;
      if (added.length) this.appended += 1;
    } catch (err) {
      if (generation !== this.generation) return;
      this.error = errorKey(err);
    } finally {
      if (generation === this.generation) {
        this.loading = false;
        this.inFlight = false;
        if (this.dirty) {
          this.dirty = false;
          void this.read();
        }
      }
    }
  }
}

export function errorKey(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return 'cplug.flow.chat.error.not_found';
    if (err.status === 422) return 'cplug.flow.chat.error.invalid';
    if (err.status === 409) return 'cplug.flow.chat.error.off';
  }
  return 'cplug.flow.chat.error.unavailable';
}
