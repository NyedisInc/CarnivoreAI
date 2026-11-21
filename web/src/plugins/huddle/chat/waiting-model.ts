import type { AuthorCrumb, SwarmWaitingItem } from './chat-api';

const REF_KINDS: ReadonlyArray<readonly [string, string]> = [
  ['question:', 'question'], ['promotion:', 'promotion'], ['trust:', 'trust'], ['held:', 'held'], ['choice:', 'choice'],
  ['import:', 'import'], ['naming:', 'naming'], ['gitinit:', 'gitinit'], ['visibility:', 'visibility'], ['conflict:', 'conflict'],
  ['suggest:', 'suggestion'], ['alert:', 'alert'], ['stuck:', 'stuck'],
];

export const ROLLUP_RANKS: ReadonlySet<string> = new Set(['alpha', 'company']);

export function feedTopic(topic: string): boolean {
  return topic === 'swarm_roster' || topic === 'approvals' || topic.startsWith('swarm_agent:') || topic.startsWith('cplug.huddle.list');
}

export function kindOf(item: SwarmWaitingItem): string {
  if (item.kind !== 'card') return item.kind;
  const ref = String((item.entry as { item?: { swarm_ref?: string } } | null | undefined)?.item?.swarm_ref ?? '');
  return REF_KINDS.find(([prefix]) => ref.startsWith(prefix))?.[1] ?? 'decision';
}

export function toneOf(kind: string): 'approval' | 'review' | 'card' {
  return kind === 'approval' ? 'approval' : kind === 'review' ? 'review' : 'card';
}

export function reviewAsk(result: string | undefined): string {
  const text = String(result ?? '');
  return (text.replace(/^needs you:/, '').split('\n')[0] ?? '').trim();
}

export interface WaitingGroup {
  agentId: number;
  path: AuthorCrumb[];
  items: SwarmWaitingItem[];
}

export function groupsOf(items: SwarmWaitingItem[]): WaitingGroup[] {
  const out: WaitingGroup[] = [];
  const at = new Map<number, WaitingGroup>();
  for (const item of items) {
    let group = at.get(item.agent_id);
    if (!group) {
      group = { agentId: item.agent_id, path: item.author_path ?? [], items: [] };
      at.set(item.agent_id, group);
      out.push(group);
    }
    group.items.push(item);
  }
  return out;
}

export interface MixPart {
  count: number;
  kind?: string;
  name?: string;
  here?: boolean;
}

export function mixOf(items: SwarmWaitingItem[], rootId: number, rollup: boolean): MixPart[] {
  const parts: MixPart[] = [];
  const find = (match: (p: MixPart) => boolean, make: () => MixPart): void => {
    const part = parts.find(match);
    if (part) part.count += 1;
    else parts.push({ ...make(), count: 1 });
  };
  for (const item of items) {
    if (!rollup) {
      const kind = kindOf(item);
      find((p) => p.kind === kind, () => ({ count: 0, kind }));
    } else if (item.agent_id === rootId) {
      find((p) => p.here === true, () => ({ count: 0, here: true }));
    } else {
      const name = item.author_path?.[0]?.name ?? '';
      find((p) => !p.here && p.name === name, () => ({ count: 0, name }));
    }
  }
  return parts;
}

export function oldestAt(items: SwarmWaitingItem[]): number | null {
  const stamps = items.map((i) => i.at).filter((at) => typeof at === 'number' && at > 0);
  return stamps.length ? Math.min(...stamps) : null;
}
