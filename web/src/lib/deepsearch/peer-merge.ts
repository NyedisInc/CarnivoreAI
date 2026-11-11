import type { DeepAnswer, DeepGroup } from './deepsearch-api';
import type { SortChoice } from './result-model';

export function mergePeerAnswer(mine: readonly DeepGroup[], answer: DeepAnswer, sort: SortChoice = 'relevance'): { groups: DeepGroup[]; fresh: DeepGroup[] } {
  const local = mine.map((g) => ({ ...g, alsoOn: [...g.alsoOn] }));
  const byId = new Map(local.map((g) => [g.conversationId, g]));
  const fresh: DeepGroup[] = [];
  for (const g of answer.groups) {
    const twin = byId.get(g.conversationId);
    if (twin) {
      if (g.hostLabel && !twin.alsoOn.includes(g.hostLabel)) twin.alsoOn.push(g.hostLabel);
    } else {
      byId.set(g.conversationId, g);
      fresh.push(g);
    }
  }
  const groups: DeepGroup[] = [];
  for (let i = 0; i < Math.max(local.length, fresh.length); i++) {
    if (i < local.length) groups.push(local[i]!);
    if (i < fresh.length) groups.push(fresh[i]!);
  }
  if (groups.some((g) => g.exact !== null)) {
    if (sort === 'date') groups.sort((a, b) => (b.lastActive ?? '').localeCompare(a.lastActive ?? ''));
    groups.sort((a, b) => Number(a.exact !== true) - Number(b.exact !== true));
  }
  return { groups, fresh };
}
