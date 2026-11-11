import { fetchBoard, postToBoard, saveDraftTo, waitNextFrom, type AnswerSet, type BoardResult, type DraftResult, type Fetcher, type NextResult,
  type PostBody, type PostResult, type PostRoute } from './board-client';
import { forgetLinkSecret, takeLinkSecret, type FragmentWindow } from './fragment';
import { visitorKey, type VisitorWindow } from './visitor-id';

export type SessionWindow = FragmentWindow & VisitorWindow;

export async function openBoard(win: SessionWindow, fetcher?: Fetcher, revision?: string): Promise<BoardResult> {
  const secret = takeLinkSecret(win);
  const answer = await fetchBoard(secret, fetcher, visitorKey(win, secret), revision ?? null);
  if (answer.kind === 'state' && (answer.state === 'ended' || answer.state === 'invalid')) forgetLinkSecret(win);
  return answer;
}

export async function sendPost(win: SessionWindow, route: PostRoute, body: PostBody, fetcher?: Fetcher): Promise<PostResult> {
  const secret = takeLinkSecret(win);
  const answer = await postToBoard(secret, route, body, fetcher, visitorKey(win, secret));
  if (answer.kind === 'state' && (answer.state === 'ended' || answer.state === 'invalid')) forgetLinkSecret(win);
  return answer;
}

export async function saveDraft(win: SessionWindow, body: { revision: string } & AnswerSet, fetcher?: Fetcher): Promise<DraftResult> {
  const secret = takeLinkSecret(win);
  const answer = await saveDraftTo(secret, visitorKey(win, secret), body, fetcher);
  if (answer.kind === 'state' && (answer.state === 'ended' || answer.state === 'invalid')) forgetLinkSecret(win);
  return answer;
}

export async function waitNext(win: SessionWindow, revision: string, fetcher?: Fetcher): Promise<NextResult> {
  const secret = takeLinkSecret(win);
  return waitNextFrom(secret, revision, fetcher, visitorKey(win, secret));
}
