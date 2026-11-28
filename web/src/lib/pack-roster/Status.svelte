
<script lang="ts" module>
  import { alphaVouches, type RosterComputer } from './roster-model';
  import { stateWord } from '../sidebar-shell/pack-stats';
  import { probeVerdict } from '../hosts-page/hosts-adapter';

  export const DIAL_LOOK: Readonly<Record<string, { shape: string; tone: string }>> = {
    self: { shape: 'filled', tone: 'ok' }, linked: { shape: 'filled', tone: 'ok' }, dialing: { shape: 'hollow', tone: 'ok' },
    unreachable: { shape: 'slash', tone: 'bad' }, refused: { shape: 'slash', tone: 'bad' }, local_network_blocked: { shape: 'slash', tone: 'bad' },
    cert_mismatch: { shape: 'tri', tone: 'warn' },
    held_over: { shape: 'hollow', tone: 'warn' }, excluded: { shape: 'slash', tone: 'warn' }, not_held: { shape: 'dot', tone: 'dim' }, never: { shape: 'dot', tone: 'dim' }, ssh: { shape: 'dot', tone: 'dim' },
  };

  export function dialKey(c: RosterComputer): string {
    return c.dial in DIAL_LOOK ? c.dial : 'never';
  }

  export function statusWord(c: RosterComputer, t: (key: string) => string): string {
    if (c.member && c.machine) return stateWord(c.machine.state, c.mesh, c.relayerUp !== false);
    return dialKey(c) === 'ssh' && c.host ? probeVerdict(c.host.probe_state, t) : t(`roster.dial.${dialKey(c)}`);
  }

  export function statusLook(c: RosterComputer): { shape: string; tone: string } {
    return alphaVouches(c) && ['never', 'not_held', 'dialing', 'unreachable'].includes(dialKey(c)) ? DIAL_LOOK.dialing! : DIAL_LOOK[dialKey(c)] ?? DIAL_LOOK.never!;
  }
</script>

<script lang="ts">
  import { t } from '../i18n/index.svelte';

  const { c }: { c: RosterComputer } = $props();
  const key = $derived(dialKey(c));
  const look = $derived(statusLook(c));
</script>

<span class="pp-st" data-shape={look.shape} data-tone={look.tone} data-for={c.id} data-dial={key}>
  <i class="pp-st__mark" aria-hidden="true"></i>
  <span class="pp-st__word">{statusWord(c, t)}</span>
</span>
