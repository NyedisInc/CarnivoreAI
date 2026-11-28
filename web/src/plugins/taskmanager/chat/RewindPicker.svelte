<script lang="ts">
  import { onMount } from 'svelte';
  import { ApiError, t } from '../../sdk';
  import type { SwarmAgentState, SwarmCheckpoint, SwarmEarlierConversation } from './chat-api';
  import { readCheckpoints, readEarlierConversations, resumeConversation, rewindAgent } from './chat-api';
  import RewindView from './RewindView.svelte';

  let { agentId, agentState, onDone, onClose }: { agentId: number; agentState: SwarmAgentState | null; onDone: (notice: string) => void; onClose: () => void } = $props();

  let commits = $state<SwarmCheckpoint[]>([]);
  let reason = $state<string | null>(null);
  let conversations = $state<SwarmEarlierConversation[]>([]);
  let loading = $state(true);
  let failed = $state('');
  let busy = $state('');

  onMount(() => {
    void Promise.all([readCheckpoints(agentId), readEarlierConversations(agentId)])
      .then(([points, earlier]) => {
        commits = points.commits;
        reason = points.reason;
        conversations = earlier;
      })
      .catch(() => { failed = t('cplug.huddle.chat.rewind.read_failed'); })
      .finally(() => { loading = false; });
  });

  async function act(key: string, work: () => Promise<void>, done: string): Promise<void> {
    if (busy) return;
    busy = key;
    failed = '';
    try {
      await work();
      onDone(t(done));
      onClose();
    } catch (error) {
      failed = error instanceof ApiError && error.message ? error.message : t('cplug.huddle.chat.action_failed');
    }
    busy = '';
  }
</script>

<RewindView {agentState} {commits} {reason} {conversations} {loading} {failed} {busy} {onClose}
            onRewind={(sha) => act(sha, () => rewindAgent(agentId, sha), 'cplug.huddle.chat.rewind.rewound')}
            onResume={(uuid) => act(uuid, () => resumeConversation(agentId, uuid), 'cplug.huddle.chat.rewind.resumed')} />
