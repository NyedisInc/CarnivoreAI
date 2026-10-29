import { ApiError } from '../sdk';
import { draftApi, refusalText } from './lab-api';
import { HOST_FILES, needsWatching, NO_DRAFTS, withHost, type DraftRequest, type DraftsState, type DraftSummary } from './drafts-model';

export const WATCH_MS = 2000;

export interface ActionResult {
  ok: boolean;
  error: string;
  draft?: DraftSummary;
}

export class DraftStore {
  state = $state<DraftsState>(NO_DRAFTS);
  error = $state('');
  busy = $state(false);
  added = $state<Record<string, string[]>>({});
  onchange: (() => void) | undefined;
  #timer: ReturnType<typeof setTimeout> | null = null;
  #gone = false;

  async refresh(): Promise<void> {
    try {
      const next = await draftApi.list();
      this.state = { ...next, drafts: next.drafts ?? [], source: next.source ?? NO_DRAFTS.source };
      this.error = '';
    } catch (error) {
      this.error = error instanceof ApiError ? refusalText(error) : String(error);
    }
    this.#watch();
  }

  #watch(): void {
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#timer = null;
    if (this.#gone || !needsWatching(this.state)) return;
    this.#timer = setTimeout(() => void this.refresh(), WATCH_MS);
  }

  async #act(call: () => Promise<DraftSummary | unknown>): Promise<ActionResult> {
    this.busy = true;
    try {
      const value = await call();
      this.error = '';
      return { ok: true, error: '', draft: value && typeof value === 'object' && 'slug' in value ? (value as DraftSummary) : undefined };
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      this.error = refusalText(error);
      return { ok: false, error: this.error };
    } finally {
      this.busy = false;
      await this.refresh();
      this.onchange?.();
    }
  }

  create = (request: DraftRequest): Promise<ActionResult> => this.#act(() => draftApi.create(request));
  build = (slug: string): Promise<ActionResult> => {
    this.added = { ...this.added, [slug]: [] };
    return this.#act(() => draftApi.build(slug));
  };
  addHost = (slug: string, host: string): Promise<ActionResult> => this.#act(async () => {
    for (const path of HOST_FILES) await draftApi.putFile(slug, path, withHost((await draftApi.file(slug, path)).content, host));
    this.added = { ...this.added, [slug]: [...(this.added[slug] ?? []), host] };
  });
  handToClaude = (slug: string): Promise<ActionResult> => this.#act(() => draftApi.handToClaude(slug));
  discard = (slug: string): Promise<ActionResult> => this.#act(() => draftApi.discard(slug));

  find(slug: string | null): DraftSummary | undefined {
    return slug === null ? undefined : this.state.drafts.find((one) => one.slug === slug);
  }

  destroy(): void {
    this.#gone = true;
    if (this.#timer !== null) clearTimeout(this.#timer);
  }
}
