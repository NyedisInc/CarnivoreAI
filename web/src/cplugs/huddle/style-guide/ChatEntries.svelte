<script lang="ts">
  import type { HuddleItem } from '../huddle-model';
  import AuthorPath from '../chat/AuthorPath.svelte';
  import ChatCard from '../chat/ChatCard.svelte';
  import EventCard from '../chat/EventCard.svelte';
  import RewindView from '../chat/RewindView.svelte';
  import TrafficCard from '../chat/TrafficCard.svelte';
  import type { AuthorCrumb, SwarmQuestion, SwarmTrafficEntry } from '../chat/chat-api';

  const STATUSES = ['queued', 'held', 'delivering', 'delivered', 'failed', 'expired'];
  const traffic = (status: string, i: number): SwarmTrafficEntry => ({
    kind: 'traffic', id: `xt:${i}`, at: 1, direction: i % 2 ? 'in' : 'out', peer: i % 2 ? 'Tully' : 'Ivy',
    text: i % 2 ? 'the schema review is ready for you' : 'can you check the migration order',
    receipt: { status, reason: status === 'failed' ? 'the peer was not running' : null },
  });
  const EVENTS: Array<[string, string]> = [
    ['spawned', 'Loki spawned Rook'],
    ['reported', 'Rook reported to Loki'],
    ['accepted', "Loki accepted Rook's report"],
    ['rallied', 'the swarm rallied at dawn'],
  ];
  const promoted = {
    id: 2, list: 'agent:1', text: 'Rook is now a feature agent: task type migrations reached 5 accepted reports. approve to keep it, or decline to flip it back.',
    note: '', position: 2, created_by: 'claude', state: 'open', kind: 'question', revision: 1, created_seq: 2, seq: 2, deleted: false, status: 'question',
    title: 'promoted: Rook', thread: [], swarm_ref: 'promotion:3',
  } as unknown as HuddleItem;
  const trusting = {
    id: 3, list: 'agent:1', text: 'Loki is starting in repo. Claude Code asks whether you trust this folder. trust it, or not now to leave it asleep.',
    note: '', position: 3, created_by: 'claude', state: 'open', kind: 'question', revision: 1, created_seq: 3, seq: 3, deleted: false, status: 'question',
    title: 'trust this folder?', thread: [], swarm_ref: 'trust:4:ab12',
  } as unknown as HuddleItem;
  const COMMITS = [
    { sha: 'db4e9413871817e67fbb2161406ef74acefca07c', at: '2026-10-05T14:02:00-04:00', subject: 'swarm: rook memory rewound to 9f8e7d6c', kind: 'rewind' },
    { sha: '9f8e7d6c5b4a39281706f5e4d3c2b1a098765432', at: '2026-10-05T11:30:00-04:00', subject: 'swarm: rook memory', kind: 'memory' },
    { sha: '0011223344556677889900aabbccddeeff001122', at: '2026-10-04T18:10:00-04:00', subject: 'swarm: rook promoted to a feature agent', kind: 'promotion' },
  ];
  const CONVERSATIONS = [
    { wake_id: 4, conversation_uuid: 'ee624b77-93d3-4cee-862a-92af6504ff14', started_at: '2026-10-05T11:00:00-04:00', reason: 'owner_message', authority: 'owner', transcript_present: true },
    { wake_id: 2, conversation_uuid: '3a40100b-042b-4ebe-8480-76e921f5148b', started_at: '2026-10-04T17:40:00-04:00', reason: 'spawn', authority: 'data', transcript_present: false },
  ];
  const noop = (): void => {};
  const NOW = Date.now();
  const PATH: AuthorCrumb[] = [
    { kind: 'company', name: 'Nyedis', agent_id: 3 }, { kind: 'project', name: 'Orchardco', agent_id: null }, { kind: 'agent', name: 'Orchard-Research', agent_id: 9 },
  ];
  const asking = {
    id: 4, list: 'all', text: '', note: '', position: 4, created_by: 'claude', state: 'open', kind: 'question', revision: 1, created_seq: 4, seq: 4,
    deleted: false, status: 'question', thread: [], swarm_ref: 'question:4',
  } as unknown as HuddleItem;
  const QUESTION: SwarmQuestion = {
    summary: 'keep the current dlp vendor for one more quarter while the new ones are tested?', task: 'researching new dlp providers',
    details: 'the two shortlisted vendors both need a 90 day pilot; cancelling the current contract now leaves a gap.',
    askers: [{ agent_id: 9, name: 'Orchard-Research', author_path: PATH }, { agent_id: 11, name: 'Orchard-QnA' }],
    asked_at: Math.floor(NOW / 1000) - 240,
  };
  const decided = {
    id: 1, list: 'agent:1', text: 'use the volcano family for names', note: '', position: 1, created_by: 'claude',
    state: 'done', kind: '', revision: 1, created_seq: 1, seq: 1, deleted: false, status: 'done', title: 'naming family', thread: [],
  } as HuddleItem;
</script>

<div class="sge">
  {#each STATUSES as status, i (status)}<TrafficCard entry={traffic(status, i)} />{/each}
  {#each EVENTS as [event, text] (event)}<EventCard {event} {text} />{/each}
  <ChatCard item={decided} card="review" agentName="Loki" />
  <ChatCard item={promoted} card="question" agentName="Loki" />
  <ChatCard item={trusting} card="question" agentName="Loki" />
  {#snippet askHead()}<AuthorPath path={PATH} at={QUESTION.asked_at} more={1} now={NOW} />{/snippet}
  <ChatCard item={asking} card="question" agentName="SysOp" question={QUESTION} head={askHead} now={NOW} />
  <RewindView agentState="asleep" commits={COMMITS} reason={null} conversations={CONVERSATIONS} loading={false} failed="" busy="" onRewind={noop} onResume={noop} onClose={noop} />
  <RewindView agentState="awake" commits={[]} reason="its memory is local to this computer and is not in git, so there is nothing to rewind" conversations={[]} loading={false} failed="" busy="" onRewind={noop} onResume={noop} onClose={noop} />
</div>

<style>
  @layer components {
    .sge {
      display: flex;
      flex-direction: column;
      gap: 8px;
      width: 640px;
      max-width: 100%;
    }
  }
</style>
