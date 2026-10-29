<script lang="ts">
  import DrawerLedger from '../../lib/ledger-drawer/DrawerLedger.svelte';
  import TerminalFoot from '../../opscenter/cells/terminal-live/TerminalFoot.svelte';
  import type {
    AccountUsage,
    LedgerSnapshot,
    Resource,
    SessionTokenUsage,
    UsageWindow,
  } from '../../opscenter/api';

  let { part = 'drawer' }: { part?: 'drawer' | 'foot' } = $props();

  const now = Date.now();
  const at = (hours: number): string => new Date(now + hours * 3600_000).toISOString();

  function win(kind: string, label: string, used: number, hours: number): UsageWindow {
    return { kind, label, used_pct: used, window_seconds: kind === 'five_hour' ? 18000 : 604800, resets_at: at(hours) };
  }

  function account(id: string, name: string, five: number, seven: number): AccountUsage {
    return {
      id,
      name,
      short_name: null,
      provider: 'claude',
      plan: 'max',
      identity: null,
      credential_state: 'ok',
      fetched_at: at(-0.01),
      next_poll_at: null,
      error: null,
      windows: [win('five_hour', '5h', five, 3.4), win('seven_day', '7d', seven, 90)],
      color: null,
      managed: true,
    };
  }

  const work = account('work', 'work', 35, 68);
  const expired: AccountUsage = { ...account('old', 'old login', 0, 0), provider: 'codex', plan: 'plus', credential_state: 'expired', windows: [] };
  const accounts: AccountUsage[] = [account('personal', 'personal', 0, 35), work, account('spare', 'spare', 0, 0), expired];

  const source: Resource<LedgerSnapshot> = {
    status: 'ok',
    data: { accounts, total: { accounts: 3, windows: [] }, loop: { alive: true, last_pass_at: at(-0.01) } },
    fetchedAt: now - 27_000,
    error: null,
    async refresh() {},
    stop() {},
  };

  const usage: SessionTokenUsage = {
    state: 'ok',
    family: 'claude',
    model: 'claude-opus-5-5',
    model_display_name: 'Opus 5.5',
    model_cost_tier: 5,
    effort: 'medium',
    input_tokens: 120_000,
    output_tokens: 365_000,
    cache_read_input_tokens: 170_000_000,
    cache_creation_input_tokens: 580_000,
    total_tokens: 171_065_000,
    cost_estimate_usd: 412.5,
    context_used_tokens: 438_000,
    context_window_tokens: 1_000_000,
    context_remaining_pct: 56,
    as_of: at(0),
    detail: null,
    account: work,
  };

  const absent: SessionTokenUsage = { ...usage, state: 'absent', detail: 'no transcript yet', account: null };
  const unchecked: SessionTokenUsage = { ...usage, state: 'unchecked', detail: 'the transcript could not be read', account: null };

  let wide = $state(0);
</script>

{#if part === 'drawer'}
  <div class="sg-grid-2">
    <div class="sg-drawer-host session-sidebar-ledger">
      <DrawerLedger {source} activeAccount="work" startOpen={false} />
    </div>
    <div class="sg-drawer-host session-sidebar-ledger">
      <DrawerLedger {source} activeAccount="work" startOpen={true} />
    </div>
  </div>
{:else}
  <div class="sg-stack sg-app-type">
    <div bind:clientWidth={wide}>
      <TerminalFoot sessionId="sg-foot-wide" width={wide} {usage} />
    </div>
    <div class="sg-foot-narrow">
      <TerminalFoot sessionId="sg-foot-narrow" width={420} {usage} />
    </div>
    <TerminalFoot sessionId="sg-foot-absent" width={wide} usage={absent} />
    <TerminalFoot sessionId="sg-foot-unchecked" width={wide} usage={unchecked} />
  </div>
{/if}
