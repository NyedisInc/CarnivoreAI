<script lang="ts">
  /* the same words */
  import StatusLed from '../../lib/StatusLed.svelte';
  import { loginExpiredLabel } from '../../lib/led';
  import { t } from '../../lib/i18n/index.svelte';

  interface LedCase {
    status: string | null;
    unread?: boolean;
    startupGate?: string | null;
    transport?: string | null;
    usageLimit?: string | null;
    loginExpired?: string | null;
    activityHint?: string | null;
    note: string;
  }

  const cases: LedCase[] = [
    { status: 'working', note: 'green, breathing ring' },
    { status: 'working_subagent', note: 'green, sub agents running' },
    { status: 'working_subagent', activityHint: 'background', note: 'background' },
    { status: 'question', note: 'yellow, blocked on you' },
    { status: 'notice', note: 'light blue, wants attention' },
    { status: 'finished_unread', note: 'crisp still ring, unread turn' },
    { status: 'idle', note: 'grey, solid centre' },
    { status: 'idle', unread: true, note: 'idle with unread flag' },
    { status: 'unknown', note: 'grey, hollow centre' },
    { status: null, note: 'no status at all reads unknown' },
    { status: 'dead', note: 'dark grey, no ring' },
    { status: 'asleep', note: 'grey moon in place of the dot' },
    { status: 'asleep', unread: true, note: 'moon in the unread color: flagged for follow-up (#749)' },
    { status: 'idle', startupGate: 'awaiting_startup_prompt', note: 'startup gate: yellow' },
    { status: 'working', transport: 'disconnected', note: 'socket dropped: red wins' },
    { status: 'working', usageLimit: 'over limit, resets oct 20 9pm', note: 'over its usage limit: the red skull, static (#1902)' },
    { status: 'idle', loginExpired: loginExpiredLabel({ login_expired: { message: '', since: null } }), note: t('session.status.login_expired') },
    { status: 'working', usageLimit: 'over limit', transport: 'disconnected', note: 'socket dropped outranks the skull' },
  ];
</script>

<ul class="sg-led-matrix">
  {#each cases as c, i (i)}
    <li class="sg-led-case">
      <StatusLed
        status={c.status}
        unread={c.unread ?? false}
        startupGate={c.startupGate ?? null}
        transport={c.transport ?? null}
        usageLimit={c.usageLimit ?? null}
        loginExpired={c.loginExpired ?? null}
        activityHint={c.activityHint ?? null}
        showLabel={true}
      />
      <code class="sg-led-props"
        >{c.status ?? 'null'}{c.unread ? ' unread' : ''}{c.startupGate ? ' startupGate' : ''}{c.transport
          ? ' transport=' + c.transport
          : ''}{c.usageLimit ? ' usageLimit' : ''}{c.loginExpired ? ' loginExpired' : ''}{c.activityHint ? ' hint=' + c.activityHint : ''}</code
      >
      <span class="sg-led-note">{c.note}</span>
    </li>
  {/each}
</ul>
