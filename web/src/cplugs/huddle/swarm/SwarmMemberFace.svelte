
<script lang="ts">
  import { Character } from './characters';
  import { avatarColorOf, rosterAgent } from '../chat/chat-avatar';
  import type { SwarmFaceProps } from '../../sdk';

  let { state, agentId, rank, seed, size }: SwarmFaceProps = $props();

  const color = $derived(avatarColorOf(rosterAgent(agentId)));
</script>

<Character {state} {size} {seed} {color} {rank} />
