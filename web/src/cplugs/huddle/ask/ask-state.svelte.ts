import { t } from '../../sdk';
import { submitNow } from '../task-submit';
import { findItem, huddle } from '../huddle.svelte';
import { applyAnswered } from '../task-manager-optimistic';
import type { HuddleItem } from '../huddle-model';
import { readAsk, submitAsk, type AskRead } from './ask-api';
import { itemWhere } from '../task-manager-outbox';
import { boundaryOf } from '../task-manager-boundary';
import { keptNoticeKey } from '../../../lib/outbox/outbox';
import { EXTRA_KEY, dismissPayload, drawnQuestions, hiddenSkips, payloadOf, progress, recommendable, takeAll, takeRecommendation, type AskAnswer, type AskProgress, type AskQuestion, type AskValue, type AskValues } from './ask-model';

export interface AskController {
  readonly read: AskRead | null;
  readonly loading: boolean;
  readonly missing: boolean;
  readonly error: string;
  readonly submitting: boolean;
  readonly values: AskValues;
  readonly extra: string;
  readonly questions: AskQuestion[];
  readonly progress: AskProgress;
  readonly answered: boolean;
  readonly item: HuddleItem | null;
  readonly answers: Record<string, AskAnswer>;
  readonly canTakeAll: number;
  readonly savedExtra: string;
  load(): Promise<void>;
  set(id: string, patch: AskValue): void;
  setExtra(text: string): void;
  take(id: string): void;
  takeAll(): void;
  reset(): void;
  submit(): Promise<boolean>;
  dismiss(): Promise<boolean>;
}

export function createAsk(messageId: number): AskController {
  const s = $state({ read: null as AskRead | null, loading: true, missing: false, error: '', submitting: false, values: {} as AskValues, extra: '' });
  const stored = (): AskQuestion[] => s.read?.ask.questions ?? [];
  const questions = (): AskQuestion[] => drawnQuestions(stored());
  const item = (): HuddleItem | null => (s.read ? findItem(s.read.item) : null);

  async function load(): Promise<void> {
    s.loading = true;
    try {
      s.read = await readAsk(messageId);
      s.missing = s.read === null;
    } catch (error) {
      console.warn('huddle: could not read the question', error);
      s.error = String(error instanceof Error ? error.message : error);
    } finally {
      s.loading = false;
    }
  }

  function set(id: string, patch: AskValue): void {
    s.values[id] = { ...s.values[id], ...patch };
    s.error = '';
  }

  function take(id: string): void {
    const q = questions().find((x) => x.id === id);
    const rec = q ? takeRecommendation(q) : null;
    if (rec) set(id, rec);
  }

  /* no longer holds */
  async function submit(): Promise<boolean> {
    if (!s.read || progress(questions(), s.values).requiredLeft > 0) return false;
    return run(() => ({ ...hiddenSkips(stored(), questions()), ...payloadOf(questions(), s.values, s.extra) }));
  }

  async function dismiss(): Promise<boolean> {
    return run(() => dismissPayload(stored()));
  }

  async function run(payload: () => Record<string, Record<string, unknown>>): Promise<boolean> {
    if (s.submitting || !s.read || s.read.answered) return false;
    s.submitting = true;
    s.error = '';
    const body = payload();
    const target = item();
    const undo = target ? applyAnswered(target, messageId) : () => {};
    s.read.answered = true;
    const list = target?.list;
    void (async () => {
      let saved = false;
      let reread = false;
      const save = async (): Promise<boolean> => {
        const out = await submitAsk(messageId, body, { list: list ?? null, item: target?.id ?? null, title: target ? itemWhere(target) : '', ackThrough: boundaryOf(target) });
        saved = out.ok;
        if (out.kept) huddle.notice = t(keptNoticeKey());
        if (!out.ok) {
          s.error = out.error;
          if (out.code === 'task_manager_answered') { reread = true; await load(); }
        }
        return out.ok && !out.kept;
      };
      if (!list) await save();
      else await submitNow(list, save);
      s.submitting = false;
      if (!saved) {
        undo();
        if (s.read && !reread) s.read.answered = false;
        if (s.error) huddle.notice = s.error;
      }
    })();
    return true;
  }

  return {
    get read() { return s.read; },
    get loading() { return s.loading; },
    get missing() { return s.missing; },
    get error() { return s.error; },
    get submitting() { return s.submitting; },
    get values() { return s.values; },
    get extra() { return s.extra; },
    get savedExtra() { return item()?.thread.find((m) => m.id === s.read?.answer_message_id)?.answers?.[EXTRA_KEY]?.text ?? ''; },
    get questions() { return questions(); },
    get progress() { return progress(questions(), s.values); },
    get answered() { return s.read?.answered === true; },
    get item() { return item(); },
    get answers() {
      const found = item()?.thread.find((m) => m.id === s.read?.answer_message_id);
      return found?.answers ?? {};
    },
    get canTakeAll() { return recommendable(questions(), s.values); },
    load,
    set,
    take,
    takeAll() { s.values = takeAll(questions(), s.values); },
    setExtra(text: string) { s.extra = text; s.error = ''; },
    reset() { s.values = {}; s.extra = ''; s.error = ''; },
    submit,
    dismiss,
  };
}
