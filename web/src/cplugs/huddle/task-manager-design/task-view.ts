import { isSystemLine, type HuddleItem, type TaskManagerArtifact, type TaskManagerBoardRound, type TaskManagerFile, type TaskManagerMessage } from '../huddle-model';
import { webLink } from './model';

export interface Entry {
  item: HuddleItem;
  project: string;
  list: string;
}

export type MainFilter = 'all' | 'needs' | 'unread' | 'scheduled';

function isComment(message: TaskManagerMessage): boolean {
  return (message.kind as string) === 'comment' || message.kind === 'correction' || message.quiet === true;
}

export function newMessageIds(item: Pick<HuddleItem, 'unread' | 'thread'>): number[] {
  if (!item.unread) return [];
  let line = -1;
  item.thread.forEach((m, at) => {
    if (m.author === 'joe' && !isComment(m) && m.id > 0) line = at;
  });
  return item.thread.slice(line + 1).filter((m) => m.author === 'claude' && m.id > 0 && !isSystemLine(m)).map((m) => m.id);
}

export function titleOf(item: Pick<HuddleItem, 'title' | 'text'>): string {
  const title = item.title?.trim();
  return title || (item.text.split('\n', 1)[0] ?? '').trim();
}

export function advanceFrom(selected: number, before: readonly number[], after: readonly number[]): number {
  if (!selected || after.includes(selected)) return selected;
  const at = before.indexOf(selected);
  return at < 0 ? 0 : (after[Math.min(at, after.length - 1)] ?? 0);
}

export interface Shared {
  key: string;
  kind: 'artifact' | 'file' | 'round' | 'link';
  name: string;
  messageId: number;
  artifact?: TaskManagerArtifact;
  file?: TaskManagerFile;
  round?: TaskManagerBoardRound;
  href?: string;
}

const URL_TAIL = /[).,;:!?\]>'"]+$/;

/* the whole conversation */
export function sharedOf(item: Pick<HuddleItem, 'thread' | 'github_issue'>): Shared[] {
  const out: Shared[] = [];
  const seen = new Set<string>();
  const add = (entry: Shared): void => {
    if (seen.has(entry.key)) return;
    seen.add(entry.key);
    out.push(entry);
  };
  const titles = new Map(item.thread.flatMap((m) => (m.board?.title ? [[m.board.slug, m.board.title] as const] : [])));
  for (const m of item.thread) {
    if (m.board) {
      const round = { slug: m.board.slug, round: '', revision: m.board.revision };
      add({ key: `r:${round.slug}::${round.revision}`, kind: 'round', name: m.board.title || m.board.slug, messageId: m.id, round });
    }
    if (m.board_round) {
      const board = titles.get(m.board_round.slug) ?? m.board_round.slug;
      add({ key: `r:${m.board_round.slug}:${m.board_round.round}:${m.board_round.revision}`, kind: 'round', name: `${board} ${m.board_round.round}`.trim(), messageId: m.id, round: m.board_round });
    }
    if (m.artifact) add({ key: `a:${m.artifact.id}`, kind: 'artifact', name: m.artifact.title, messageId: m.id, artifact: m.artifact });
    for (const file of m.files ?? []) add({ key: `f:${file.id}`, kind: 'file', name: file.name, messageId: m.id, file });
    for (const found of m.text.match(/https?:\/\/[^\s]+/g) ?? []) {
      const href = webLink(found.replace(URL_TAIL, ''));
      if (href && href !== webLink(item.github_issue ?? undefined)) add({ key: `l:${href}`, kind: 'link', name: href, messageId: m.id, href });
    }
  }
  return out;
}
