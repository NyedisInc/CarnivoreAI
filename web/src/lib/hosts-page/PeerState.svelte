
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import { peerStateLabel } from './hosts-adapter';

    interface Props {
        state: string;
        t: Translate;
    }

    const { state, t }: Props = $props();
</script>

<span class="host-state host-state--{state}" data-peer-state={state}>{peerStateLabel(state, t)}</span>

<style>
  @layer components {
    .host-state {
        display: inline-block;
        padding: 1px 6px;
        border: 1px solid var(--_c, var(--oc-line-panel));
        border-radius: var(--oc-radius-sm);
        color: var(--_c, var(--oc-text-secondary));
        font-family: var(--font-mono);
        font-size: var(--oc-fs-micro);
        letter-spacing: var(--oc-tracking-label);
        text-transform: uppercase;
    }
    .host-state--connected { --_c: var(--oc-green); }
    .host-state--connecting,
    .host-state--disconnected { --_c: var(--oc-yellow); }
    .host-state--incompatible,
    .host-state--identity_changed { --_c: var(--oc-coral); }
    .host-state--unpaired { --_c: var(--oc-text-muted); }
  }
</style>
