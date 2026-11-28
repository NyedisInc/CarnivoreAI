import { describe, expect, test } from 'vitest';
import type { AuthorCrumb, SwarmEntry } from './chat-api';
import { chatRows, partyOf, recipientOf } from './chat-model';

const SELF = { id: 3, name: 'Echo (Riverbed)' };
const LOOK = { idOfName: (name: string) => (name === 'Docs' ? 11 : null), idOfUuid: (uuid: string) => (uuid === 'u-docs' ? 11 : null) };
const own: AuthorCrumb[] = [{ kind: 'project', name: 'Cobalt', agent_id: 2 }, { kind: 'agent', name: 'Boss', agent_id: SELF.id }];
const child: AuthorCrumb[] = [{ kind: 'project', name: 'Cobalt', agent_id: 2 }, { kind: 'agent', name: 'Kid', agent_id: 9 }];
const you: AuthorCrumb[] = [{ kind: 'owner', name: 'alex', agent_id: null }];

let n = 0;
const post = (path: AuthorCrumb[] | null, over: Record<string, unknown> = {}): SwarmEntry =>
  ({ kind: 'agent', id: `a:${++n}`, at: 100 + n, text: 'hi', ...(path ? { author_path: path } : {}), ...over }) as SwarmEntry;
const ownerMsg = (): SwarmEntry => ({ kind: 'owner', id: `msg:${++n}`, at: 100 + n, text: 'go', author_path: you });
const traffic = (direction: 'in' | 'out', peer: string, path?: AuthorCrumb[], uuid: string | null = null): SwarmEntry =>
  ({ kind: 'traffic', id: `xt:${++n}`, at: 100 + n, direction, peer, peer_session_uuid: uuid, text: 'm', ...(path ? { author_path: path } : {}) }) as SwarmEntry;
const event = (name: string): SwarmEntry =>
  ({ kind: 'event', id: `ev:${++n}`, at: 100 + n, event: name, ref: '1', text: `${name} happened`, author_path: own }) as SwarmEntry;
const review = (path: AuthorCrumb[]): SwarmEntry => ({
  kind: 'card', id: `item:${++n}`, at: 100 + n, card: 'review', author_path: path, waits_on_owner: true,
  item: { id: n, list: 'agent:3', text: 'ship', note: '', position: 1, created_by: 'claude', state: 'open', kind: 'done', revision: 1, created_seq: 1, seq: 1, deleted: false, status: 'review', thread: [] },
}) as unknown as SwarmEntry;

const shape = (entries: SwarmEntry[]) => chatRows(entries, SELF, LOOK)
  .map((r) => (r.kind === 'fold' ? `F${r.entries.length}` : !r.party ? '-' : r.first ? 'H' : 'f'));

describe('burst grouping', () => {
  test('consecutive entries from one party share one header; a new party opens a new one', () => {
    expect(shape([post(own), post(own), ownerMsg(), ownerMsg(), post(own)])).toEqual(['H', 'f', 'H', 'f', 'H']);
  });

  test('a needs-you card always opens its own header and closes the burst after it', () => {
    expect(shape([post(child), review(child), post(child)])).toEqual(['H', 'H', 'H']);
  });

  test('an entry with no author path draws plain, as before', () => {
    expect(shape([post(null), post(null)])).toEqual(['-', '-']);
  });
});

describe('event folding', () => {
  test('a run of two or more quiet events folds into one row and ends the burst', () => {
    expect(shape([post(own), event('reported'), event('accepted'), event('spawned'), post(own)])).toEqual(['H', 'F3', 'H']);
  });

  test('a lone quiet event draws in place', () => {
    expect(shape([post(own), event('spawned'), post(own)])).toEqual(['H', '-', 'H']);
  });
});

describe('direction: arrows on agent-to-agent traffic only (#1435)', () => {
  test('no arrow on the chat agent\'s own posts or the owner\'s; the own post wears the agent\'s own name', () => {
    expect(partyOf(post(own), SELF, LOOK)).toMatchObject({ dir: null, agentId: SELF.id });
    expect(partyOf(post(own), SELF, LOOK)?.path.at(-1)).toEqual({ kind: 'agent', name: 'Echo (Riverbed)', agent_id: SELF.id });
    expect(partyOf(ownerMsg(), SELF, LOOK)).toMatchObject({ dir: null, owner: true });
  });

  test('a server-posted card for a project agent (its path ends at the PROJECT crumb) is the agent itself, no arrow', () => {
    const naming: AuthorCrumb[] = [{ kind: 'company', name: 'Nyedis', agent_id: 1 }, { kind: 'project', name: 'Riverbed', agent_id: SELF.id }];
    const party = partyOf(review(naming), SELF, LOOK);
    expect(party?.dir).toBeNull();
    expect(party?.path.at(-1)).toMatchObject({ name: 'Echo (Riverbed)', agent_id: SELF.id });
  });

  test('sent TO an agent is the agent itself with the recipient beside it; FROM an agent is "from" with the sender', () => {
    expect(partyOf(traffic('out', 'Docs', own), SELF, LOOK)).toMatchObject({ dir: null, agentId: SELF.id });
    const to = recipientOf(traffic('out', 'Docs', own), LOOK);
    expect(to).toMatchObject({ dir: null, agentId: 11 });
    expect(to?.path).toEqual([{ kind: 'agent', name: 'Docs', agent_id: 11 }]);
    expect(partyOf(traffic('in', 'Kid', child), SELF, LOOK)).toMatchObject({ dir: 'from', agentId: 9 });
    expect(partyOf(post(child), SELF, LOOK)).toMatchObject({ dir: 'from', agentId: 9 });
    expect(shape([traffic('out', 'Docs', own), traffic('out', 'Docs', own), traffic('out', 'Other', own)])).toEqual(['H', 'f', 'f']);
  });

  test('a non-Swarm crosstalk peer keeps its session uuid as its node key', () => {
    const party = partyOf(traffic('in', 'Cv-Layer1', [{ kind: 'agent', name: 'Cv-Layer1', agent_id: null }], 'uuid-cv'), SELF, LOOK);
    expect(party).toMatchObject({ dir: 'from', agentId: null, sessionUuid: 'uuid-cv' });
  });
});
