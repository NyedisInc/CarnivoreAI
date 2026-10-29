import { ApiError, authFetch } from '../../sdk';
import { refusalCode } from '../huddle-model';
import { explain, pushIsLive, refreshTaskManager, trackWrite } from '../huddle.svelte';
import { answersText, outboxPost } from '../task-manager-outbox';
import type { AskAnswer, AskQuestion } from './ask-model';

export interface AskRead {
  item: number;
  message: number;
  typed: boolean;
  ask: { context: string; questions: AskQuestion[] };
  answered: boolean;
  answer_message_id: number | null;
}

export interface AskOutcome {
  ok: boolean;
  error: string;
  code: string | null;
  /* did not answer */
  kept?: boolean;
}

export interface AskWhere { list: string | null; item: number | null; title: string; ackThrough?: number }

export async function readAsk(messageId: number): Promise<AskRead | null> {
  try {
    return await authFetch<AskRead>(`/cplugs/huddle/questions/${messageId}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/* did not answer */
export async function submitAsk(messageId: number, answers: Record<string, Record<string, unknown>>, where: AskWhere = { list: null, item: null, title: '' }): Promise<AskOutcome> {
  try {
    const out = await trackWrite(() => outboxPost({
      kind: 'answer', path: `/cplugs/huddle/questions/${messageId}/answer`, body: where.ackThrough === undefined ? { answers } : { answers, ack_through: where.ackThrough }, idempotent: false, sendList: where.list,
      where: where.title, text: answersText(answers), list: where.list, item: where.item,
    }));
    if (out.kept) return { ok: true, error: '', code: null, kept: true };
    if (!pushIsLive()) void refreshTaskManager();
    return { ok: true, error: '', code: null };
  } catch (error) {
    void refreshTaskManager();
    const code = error instanceof ApiError ? refusalCode(error.payload) : null;
    const detail = (error instanceof ApiError ? (error.payload as { detail?: { detail?: string } } | null)?.detail?.detail : '') ?? '';
    return { ok: false, error: code === 'task_manager_invalid' && detail ? detail : explain(error), code };
  }
}

export type AskAnswers = Record<string, AskAnswer>;
