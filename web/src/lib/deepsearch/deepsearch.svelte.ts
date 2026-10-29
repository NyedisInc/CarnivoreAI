import { openConversation, type ConversationTarget, type OpenOutcome } from '../conversation-open/open';
import { openModal } from '../modal';
import { sessionRowForConversation } from '../../cplugs/sdk/sessions.svelte';
import { t } from '../i18n/index.svelte';
import type { DrawerSearchController } from './provider-types';
import ContextModal from './ContextModal.svelte';
import type { ContextRequest } from './context-api';
import { browserDeepSearchApi, PAGE_SIZE, type DeepAnswer, type DeepGroup, type DeepHit, type DeepIngest, type DeepSearchApi, type DeepSuggestion, type PeerDown, type SearchScope } from './deepsearch-api';
import { HitRunner, targetOf } from './hit-runner';
import { mergePeerAnswer } from './peer-merge';
import { conversationName, conversationState, needsFetch, readLayout, walk, writeLayout, type ConvState, type Layout, type WalkedHit } from './result-model';

export const DEBOUNCE_MS = 250;
export const MIN_QUERY_CHARS = 2;

export const MIN_SUGGEST_CHARS = 2;
const TRAILING_WORD = /[\p{L}\p{N}_]+$/u;
export const SUGGEST_ID_PREFIX = 'dps-sug-';
export const SUGGEST_LIST_ID = 'dps-suggest';

export type DeepPhase = 'idle' | 'short' | 'searching' | 'done' | 'failed';

export type FlatDeepHit = WalkedHit;

export type KindFilter = 'all' | 'user' | 'assistant' | 'tool';
export const KIND_FILTERS: readonly KindFilter[] = ['all', 'user', 'assistant', 'tool'];

export type Opener = (target: ConversationTarget) => Promise<OpenOutcome>;

export interface ContextShow {
  title: string;
  request: ContextRequest;
  target: ConversationTarget;
  hostLabel: string | null;
  bookmark: DeepHit['bookmark'];
  focus: 'hit' | 'bookmark';
  hitLine: number | null;
}

export type ContextOpener = (show: ContextShow) => void;

const openContextModal: ContextOpener = (show) => {
  void openModal(ContextModal as never, show as unknown as Record<string, unknown>);
};

export class DeepSearchController implements DrawerSearchController {
  query = $state('');
  phase = $state<DeepPhase>('idle');
  groups = $state.raw<DeepGroup[]>([]);
  total = $state(0);
  localTotal = $state(0);
  /* did not answer */
  peerDown = $state.raw<PeerDown[]>([]);
  matches = $state(0);
  ingest = $state.raw<DeepIngest | null>(null);
  active = $state(-1);
  keyMoves = $state(0);
  loadingMore = $state(false);
  suggestions = $state.raw<DeepSuggestion[]>([]);
  suggestActive = $state(-1);
  onReplaceQuery?: (text: string) => void;
  notes = $state.raw<Record<string, OpenOutcome>>({});
  layout = $state<Layout>(readLayout());
  kind = $state<KindFilter>('all');
  scope = $state.raw<{ conversationId: string; name: string } | null>(null);
  expanded = $state.raw<Record<string, true>>({});
  stale = $state.raw<string[]>([]);
  actionNote = $state('');

  readonly noMatchesKey: string;

  #api: DeepSearchApi;
  #open: Opener;
  #contextOpener: ContextOpener;
  #timer: ReturnType<typeof setTimeout> | null = null;
  #abort: AbortController | null = null;
  #seq = 0;
  #peerAbort: AbortController | null = null;
  #peerSeq = 0;
  #searched = '';
  #suggestTimer: ReturnType<typeof setTimeout> | null = null;
  #suggestAbort: AbortController | null = null;
  #suggestSeq = 0;
  #runner: HitRunner;

  showActions = false;

  promptStyle = false;

  constructor(
    api: DeepSearchApi = browserDeepSearchApi,
    open: Opener = (t) => openConversation(t),
    noMatchesKey: string = 'deepsearch.no_matches',
    showContext: ContextOpener = openContextModal,
  ) {
    this.#api = api;
    this.#open = open;
    this.#contextOpener = showContext;
    this.noMatchesKey = noMatchesKey;
    this.#runner = new HitRunner({ say: (line) => { this.actionNote = line; }, open: (target) => this.#open(target) });
  }

  get flat(): FlatDeepHit[] {
    return walk(this.groups, this.expanded);
  }

  get filterable(): boolean {
    return this.#api.filters === true;
  }

  setLayout(layout: Layout): void {
    this.layout = layout;
    writeLayout(layout);
  }

  setKind(kind: KindFilter): void {
    if (kind === this.kind) return;
    this.kind = kind;
    if (this.#searched) void this.run(this.#searched, 0);
  }

  scopeTo(group: DeepGroup, name: string): void {
    this.scope = { conversationId: group.conversationId, name };
    if (this.#searched) void this.run(this.#searched, 0);
  }

  clearScope(): void {
    this.scope = null;
    if (this.#searched) void this.run(this.#searched, 0);
  }

  #scopeArg(): SearchScope {
    return { kinds: this.kind === 'all' ? undefined : this.kind, conversationId: this.scope?.conversationId };
  }

  async expand(group: DeepGroup): Promise<void> {
    const id = group.conversationId;
    if (this.expanded[id]) return;
    if (needsFetch(group) && this.#api.filters) {
      const seq = this.#seq;
      try {
        const answer = await this.#api.search(this.#searched, 0, new AbortController().signal, { ...this.#scopeArg(), conversationId: id });
        const full = answer.groups.find((g) => g.conversationId === id);
        if (seq !== this.#seq) return;
        if (full) this.groups = this.groups.map((g) => (g.conversationId === id ? { ...g, hits: full.hits } : g));
      } catch (err) {
        console.warn('DeepSearch: the rest of the conversation could not be read', err);
        this.actionNote = t('deepsearch.action.more_failed');
        return;
      }
    }
    this.expanded = { ...this.expanded, [id]: true };
  }

  stateOf(group: DeepGroup): ConvState {
    return conversationState(group, sessionRowForConversation(group.conversationId));
  }

  go(group: DeepGroup): Promise<boolean> {
    this.cancel();
    return this.#runner.go(group, this.stateOf(group));
  }

  goActive(): Promise<boolean> {
    const row = this.flat[Math.max(this.active, 0)];
    return row ? this.go(row.group) : Promise.resolve(false);
  }

  branch(group: DeepGroup, hit: DeepHit): Promise<boolean> {
    return this.#runner.branch(group, hit);
  }

  bookmark(group: DeepGroup, hit: DeepHit): Promise<boolean> {
    return this.#runner.bookmark(group, hit);
  }

  copyLink(group: DeepGroup, hit: DeepHit): Promise<boolean> {
    return this.#runner.link(group, hit);
  }

  get hasHits(): boolean {
    return this.phase === 'done' && this.flat.length > 0;
  }

  get hasMore(): boolean {
    return this.phase === 'done' && this.#localShown() < this.localTotal;
  }

  #localShown(): number {
    return this.groups.filter((g) => g.hostKey === null || g.hostKey === 'local').length;
  }

  get suggesting(): boolean {
    return this.suggestions.length > 0;
  }

  get suggestActiveId(): string | null {
    return this.suggestActive >= 0 ? `${SUGGEST_ID_PREFIX}${this.suggestActive}` : null;
  }

  onType(): void {
    this.cancel();
    this.scope = null;
    this.#scheduleSuggest();
    const q = this.query.trim();
    if (q.length === 0) {
      this.#reset('idle');
      return;
    }
    if (q.length < MIN_QUERY_CHARS) {
      this.#reset('short');
      return;
    }
    this.phase = 'searching';
    this.#timer = setTimeout(() => {
      this.#timer = null;
      void this.run(q, 0);
    }, DEBOUNCE_MS);
  }

  #reset(phase: DeepPhase): void {
    this.phase = phase;
    this.groups = [];
    this.total = 0;
    this.localTotal = 0;
    this.peerDown = [];
    this.notes = {};
    this.expanded = {};
    this.stale = [];
    this.actionNote = '';
  }

  async run(q: string, offset: number): Promise<void> {
    const seq = ++this.#seq;
    this.#abort?.abort();
    const abort = new AbortController();
    this.#abort = abort;
    if (offset === 0) this.phase = 'searching';
    else this.loadingMore = true;
    let peerAnswer: DeepAnswer | null = null;
    let shownLocal = false;
    if (offset === 0) this.#stopPeers();
    const peerSeq = this.#peerSeq;
    const mergePeers = (): void => {
      if (!shownLocal || peerAnswer === null || peerSeq !== this.#peerSeq) return;
      this.#mergePeerAnswer(peerAnswer);
      peerAnswer = null;
    };
    const scopeArg = this.#scopeArg();
    if (offset === 0 && this.#api.peers && !scopeArg.conversationId) {
      const peerSignal = new AbortController();
      this.#peerAbort = peerSignal;
      this.#api.peers(q, peerSignal.signal, scopeArg).then(
        (answer) => {
          peerAnswer = answer;
          mergePeers();
        },
        (err) => {
          if (peerSeq === this.#peerSeq && !peerSignal.signal.aborted) console.warn('DeepSearch: the paired computers could not be asked', err);
        },
      );
    }
    try {
      const answer: DeepAnswer = await this.#api.search(q, offset, abort.signal, scopeArg);
      if (seq !== this.#seq) return;
      this.#searched = q;
      const shown = new Set(offset === 0 ? [] : this.groups.map((g) => g.conversationId));
      this.groups = offset === 0 ? answer.groups : [...this.groups, ...answer.groups.filter((g) => !shown.has(g.conversationId))];
      this.localTotal = answer.localTotal;
      if (offset === 0) {
        this.total = answer.totalConversations;
        this.matches = answer.totalMatches;
        this.peerDown = answer.peerDown;
      }
      this.ingest = answer.ingest;
      this.stale = offset === 0 ? answer.stale : [...new Set([...this.stale, ...answer.stale])];
      if (offset === 0) {
        this.active = -1;
        this.notes = {};
        this.actionNote = '';
        this.expanded = this.scope ? { [this.scope.conversationId]: true } : {};
      }
      this.phase = 'done';
      shownLocal = true;
      mergePeers();
    } catch (err) {
      if (seq !== this.#seq || abort.signal.aborted) return;
      console.warn('DeepSearch: search failed', err);
      if (offset === 0) this.#reset('failed');
    } finally {
      if (seq === this.#seq) this.loadingMore = false;
    }
  }

  async refreshExports(): Promise<void> {
    if (this.phase !== 'done' || !this.#searched) return;
    const seq = this.#seq;
    const fresh = new Map<string, DeepGroup['exported']>();
    try {
      for (let offset = 0; offset < this.#localShown(); offset += PAGE_SIZE) {
        const answer = await this.#api.search(this.#searched, offset, new AbortController().signal, this.#scopeArg());
        for (const g of answer.groups) fresh.set(g.conversationId, g.exported);
      }
    } catch (err) {
      console.warn('DeepSearch: the export status could not be refreshed', err);
      return;
    }
    if (seq !== this.#seq) return;
    this.groups = this.groups.map((g) => (fresh.has(g.conversationId) && (g.hostKey === null || g.hostKey === 'local') ? { ...g, exported: fresh.get(g.conversationId) ?? null } : g));
  }

  #mergePeerAnswer(answer: DeepAnswer): void {
    const merged = mergePeerAnswer(this.groups, answer);
    this.groups = merged.groups;
    this.total += merged.fresh.length;
    this.matches += merged.fresh.reduce((n, g) => n + g.matches, 0);
    this.peerDown = answer.peerDown;
  }

  #prefix(): string {
    return TRAILING_WORD.exec(this.query)?.[0] ?? '';
  }

  #scheduleSuggest(): void {
    this.#stopSuggest();
    const prefix = this.#prefix();
    const suggest = this.#api.suggest;
    if (!suggest || prefix.length < MIN_SUGGEST_CHARS) return;
    this.#suggestTimer = setTimeout(() => {
      this.#suggestTimer = null;
      void this.#fetchSuggest(prefix);
    }, DEBOUNCE_MS);
  }

  async #fetchSuggest(prefix: string): Promise<void> {
    const seq = ++this.#suggestSeq;
    const abort = new AbortController();
    this.#suggestAbort = abort;
    try {
      const terms = await this.#api.suggest!(prefix, abort.signal);
      if (seq !== this.#suggestSeq) return;
      const lower = prefix.toLowerCase();
      this.suggestions = terms.length === 1 && terms[0]!.term === lower ? [] : terms;
      this.suggestActive = -1;
    } catch (err) {
      if (seq !== this.#suggestSeq || abort.signal.aborted) return;
      console.warn('DeepSearch: suggest failed', err);
      this.suggestions = [];
    }
  }

  #stopSuggest(): void {
    if (this.#suggestTimer !== null) {
      clearTimeout(this.#suggestTimer);
      this.#suggestTimer = null;
    }
    this.#suggestSeq++;
    this.#suggestAbort?.abort();
    this.#suggestAbort = null;
    this.suggestions = [];
    this.suggestActive = -1;
  }

  suggestMove(delta: number): void {
    const n = this.suggestions.length;
    if (n === 0) return;
    const next = this.suggestActive + delta;
    this.suggestActive = next >= n ? 0 : next < 0 ? n - 1 : next;
  }

  suggestClose(): void {
    this.#stopSuggest();
  }

  acceptSuggestion(index: number): boolean {
    const row = this.suggestions[index];
    if (!row) return false;
    const text = `${this.query.slice(0, this.query.length - this.#prefix().length)}${row.term} `;
    this.#stopSuggest();
    this.onReplaceQuery?.(text);
    return true;
  }

  suggestPick(): boolean {
    return this.acceptSuggestion(this.suggestActive);
  }

  more(): Promise<void> {
    return this.hasMore ? this.run(this.#searched, this.#localShown()) : Promise.resolve();
  }

  move(delta: number): void {
    const n = this.flat.length;
    if (n === 0) return;
    this.active = this.active < 0 ? (delta > 0 ? 0 : n - 1) : (this.active + delta + n) % n;
    this.keyMoves += 1;
  }

  async pick(group: DeepGroup): Promise<boolean> {
    this.cancel();
    const outcome = await this.#open({ conversationId: group.conversationId, sessionUuid: group.sessionUuid, projectId: group.projectId });
    if (outcome === 'none' || outcome === 'failed') {
      this.notes = { ...this.notes, [group.conversationId]: outcome };
      return false;
    }
    return true;
  }

  static nameOf(group: DeepGroup): string {
    return conversationName(group, sessionRowForConversation(group.conversationId)?.label, t);
  }

  showContext(group: DeepGroup, hit: DeepHit, focus: 'hit' | 'bookmark', title: string): boolean {
    const base = { conversationId: group.conversationId, fileKind: hit.fileKind, hostKey: group.hostKey };
    const request: ContextRequest | null = focus === 'bookmark' && hit.bookmark ? { ...base, at: hit.bookmark.at }
      : hit.line !== null ? { ...base, line: hit.line } : null;
    if (request === null) return false;
    this.#contextOpener({ title, request, target: targetOf(group), hostLabel: group.hostKey !== null && group.hostKey !== 'local' ? (group.hostLabel ?? group.hostKey) : null,
      bookmark: hit.bookmark, focus, hitLine: hit.line });
    return true;
  }

  async pickHit(group: DeepGroup, hit: DeepHit, title: string): Promise<boolean> {
    return this.showContext(group, hit, 'hit', title) || this.pick(group);
  }

  async clickHit(index: number, group: DeepGroup, hit: DeepHit, title: string): Promise<boolean> {
    this.active = index;
    return this.pickHit(group, hit, title);
  }

  pickActive(): Promise<boolean> {
    const row = this.flat[Math.max(this.active, 0)];
    return row ? this.pickHit(row.group, row.hit, DeepSearchController.nameOf(row.group)) : Promise.resolve(false);
  }

  #stopPeers(): void {
    this.#peerSeq++;
    this.#peerAbort?.abort();
    this.#peerAbort = null;
  }

  cancel(): void {
    this.#stopSuggest();
    if (this.#timer !== null) {
      clearTimeout(this.#timer);
      this.#timer = null;
    }
    this.#seq++;
    this.#abort?.abort();
    this.#abort = null;
    this.#stopPeers();
    this.loadingMore = false;
    if (this.phase === 'searching') this.phase = this.groups.length ? 'done' : 'idle';
  }
}
