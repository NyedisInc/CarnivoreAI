<script lang="ts">
  import '../../lib/ledger/ledger-chrome.css';
  import '../../lib/computers/computers.css';
  import '../../lib/pack-machines/pack-settings.css';
  import ComputerRow from '../../lib/computers/ComputerRow.svelte';
  import MachineBadge from '../../opscenter/ui/MachineBadge.svelte';
  import PackMarks from '../../lib/pack-machines/PackMarks.svelte';
  import PackMeter from '../../lib/pack-machines/PackMeter.svelte';
  import type { PackMachine } from '../../lib/pack-machines/pack-machines-store.svelte';

  let { part = 'computers' }: { part?: 'computers' | 'meters' | 'marks' } = $props();

  const snap = (cpu: number, mem: number, disk: number): NonNullable<PackMachine['snapshot']> =>
    ({
      load: { cores: 10, load_1: cpu, memory_percent: mem, disk_percent: disk },
      battery: null,
      reserve: { level: 'away', cpu_pct: 10, mem_pct: 10, source: 'schedule', config: null },
      restrictions: {},
      toolchain: { python3: true, node: true, git: true, docker: false, claude: true },
    }) as unknown as NonNullable<PackMachine['snapshot']>;
  const machine = (id: string, over: Partial<PackMachine>): PackMachine => ({
    install_id: id, label: id, is_self: false, is_master: false, paired: true, state: 'connected', capabilities: [],
    specs: { model: 'MacBookPro18,2', cores: 10, mem_total_gb: 64 }, snapshot: snap(5, 58, 76), age_seconds: 2, ...over,
  });
  const nostromo = machine('nostromo', { is_self: true, is_master: true, state: 'self' });
  const studio = machine('studio', { snapshot: snap(8, 81, 93), specs: { model: 'Mac16,10', cores: 10, mem_total_gb: 16 } });
  const thorPair = {
    install_id: 'studio', label: 'studio', host_key: null, transport: 'tls', role: 'member', state: 'connected', direction: 'both',
    fid: 'thorfid', fid_short: 'a1b2c3', cert_sha256: null, joined_at: null, last_link_at: null, possible_duplicate_of: null,
  } as const;
</script>

{#if part === 'computers'}
  <section class="cmp-panel pl-panel pledger">
    <div class="cmp-body">
      <ul class="cmp-list">
        <ComputerRow machine={nostromo} nowMs={Date.now()} busy={false} />
        <ComputerRow machine={studio} computer={thorPair} nowMs={Date.now()} busy={false} />
      </ul>
    </div>
  </section>
{:else if part === 'meters'}
  <section class="pl-panel pledger"><div class="pk-meters" style="padding: 12px">
    <PackMeter label="cpu" pct={50} text="5/10" reservePct={10} title="cpu normal, 50 percent, 10 percent held back" />
    <PackMeter label="mem" pct={81} text="81%" reservePct={10} title="memory high, 81 percent, 10 percent held back" />
    <PackMeter label="disk" pct={93} text="93%" title="disk critical, 93 percent" />
    <PackMeter label="mem" pct={null} text="-" title="memory not measured" />
  </div></section>
{:else}
  <section class="pl-panel pledger"><div class="pk-meters" style="padding: 12px">
    <PackMarks alpha self />
    <PackMarks link="linked" />
    <PackMarks link="connecting" />
    <PackMarks link="down" />
    <PackMarks link="error" />
    <span><MachineBadge hostKey="studio" label="studio" /> <MachineBadge hostKey="studio" label="studio" state="offline" /></span>
  </div></section>
{/if}
