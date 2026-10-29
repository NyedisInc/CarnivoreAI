
<script lang="ts" module>
  import type { RosterComputer } from './roster-model';

  export const DIAL_LOOK: Readonly<Record<string, { shape: string; tone: string }>> = {
    self: { shape: 'filled', tone: 'ok' }, linked: { shape: 'filled', tone: 'ok' }, dialing: { shape: 'hollow', tone: 'ok' },
    unreachable: { shape: 'slash', tone: 'bad' }, refused: { shape: 'slash', tone: 'bad' }, local_network_blocked: { shape: 'slash', tone: 'bad' },
    cert_mismatch: { shape: 'tri', tone: 'warn' }, never: { shape: 'dot', tone: 'dim' }, ssh: { shape: 'dot', tone: 'dim' },
  };

  export function dialKey(c: RosterComputer): string {
    return c.dial in DIAL_LOOK ? c.dial : 'never';
  }
</script>

<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { probeVerdict } from '../hosts-page/hosts-adapter';

  const { c }: { c: RosterComputer } = $props();
  const key = $derived(dialKey(c));
  const look = $derived(DIAL_LOOK[key] ?? DIAL_LOOK.never!);
</script>

<span class="pp-st" data-shape={look.shape} data-tone={look.tone} data-for={c.id} data-dial={key}>
  <i class="pp-st__mark" aria-hidden="true"></i>
  <span class="pp-st__word">{key === 'ssh' && c.host ? probeVerdict(c.host.probe_state, t) : t(`roster.dial.${key}`)}</span>
</span>
