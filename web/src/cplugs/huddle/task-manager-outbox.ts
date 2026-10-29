import { newClientId, sendOutbox, type OutboxResult } from '../sdk';
import { serverKey, type HuddleItem } from './huddle-model';

export interface OutboxPost {
  kind: 'reply' | 'answer' | 'add';
  path: string;
  body: Record<string, unknown>;
  idempotent: boolean;
  sendList: string | null;
  where: string;
  text: string;
  list: string | null;
  item: number | null;
}

export type OutboxPostResult = { kept: false; answer: unknown } | { kept: true };

export async function outboxPost(post: OutboxPost): Promise<OutboxPostResult> {
  const id = newClientId();
  const result: OutboxResult = await sendOutbox({
    id,
    kind: post.kind,
    request: { method: 'POST', path: post.path, body: post.idempotent ? { ...post.body, client_id: id } : post.body },
    ageField: post.idempotent ? 'retry_age_s' : null,
    after: post.sendList === null ? null : { path: '/cplugs/huddle/send', body: { lists: [serverKey(post.sendList)], queue: true } },
    label: { text: post.text, where: post.where, list: post.list, item: post.item },
  });
  if (result.ok) return { kept: false, answer: result.answer };
  if (result.kept) return { kept: true };
  throw result.cause;
}

export function itemWhere(item: Pick<HuddleItem, 'title' | 'text'>): string {
  const first = (item.title?.trim() || item.text.split('\n')[0] || '').trim();
  return first.length > 80 ? `${first.slice(0, 79)}...` : first;
}

export function answersText(answers: Record<string, Record<string, unknown>>): string {
  return Object.entries(answers).map(([question, answer]) => `${question}: ${JSON.stringify(answer)}`).join('\n');
}
