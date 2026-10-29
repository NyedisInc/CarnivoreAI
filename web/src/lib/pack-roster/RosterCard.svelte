
<script lang="ts">
  import Button from '../base/Button.svelte';
  import { t } from '../i18n/index.svelte';
  import Marks from './Marks.svelte';
  import Meters from './Meters.svelte';
  import Status from './Status.svelte';
  import WolfButton from './WolfButton.svelte';
  import { ageWords } from '../computers/computers-format';
  import { loginOf, type RosterComputer } from './roster-model';
  import '../catalog/warez-card.css';

  interface Props { c: RosterComputer; list?: boolean; open?: boolean; onOpen: (id: string) => void; nowMs: number }
  const { c, list = false, open = false, onOpen, nowMs }: Props = $props();

  const specs = $derived(c.machine?.specs ?? null);
  const model = $derived([specs?.model, specs?.cores != null ? t('roster.card.cores', { n: specs.cores }) : null, specs?.mem_total_gb != null ? t('roster.card.gb', { n: Math.round(specs.mem_total_gb) }) : null].filter(Boolean).join(' · ') || t('roster.card.no_carnivore'));
  const key = $derived(c.entry?.fid_short ?? '');
  const how = $derived(
    c.isSelf ? (key ? t('roster.card.key', { key }) : '')
      : c.kind === 'ssh-only' ? t('roster.card.reached_ssh', { login: loginOf(c.host) ?? '' })
      : c.transport === 'ssh' ? t('roster.card.over_ssh_as', { login: loginOf(c.host) ?? c.entry?.label ?? 'ssh', key })
      : t('roster.card.linked_over', { proto: c.peer?.protocol ?? 'tls', key }),
  );
  const seen = $derived(c.isSelf ? t('roster.card.this') : t('roster.card.last_seen', { age: c.lastSeen ? ageWords(c.lastSeen, nowMs) : t('roster.card.never_seen') }));
  const sshOnly = $derived(c.kind === 'ssh-only' && c.host !== null);

  function click(event: MouseEvent): void {
    if ((event.target as HTMLElement).closest('button, a, input, label')) return;
    onOpen(c.id);
  }
</script>

{#snippet nameButton()}
  <Button variant="quiet" aria-label={t('roster.card.open', { name: c.name })} data-name-open onclick={(e) => { e.stopPropagation(); onOpen(c.id); }}>{c.name}</Button>
{/snippet}
{#snippet icon()}<span class="oc-icon-tile" aria-hidden="true">{c.name.charAt(0).toUpperCase()}</span>{/snippet}

{#if list}
  <li class="m1-row" aria-current={open ? 'true' : 'false'} data-computer-card={c.id} onclick={click} role="presentation">
    <span class="m1-row__name">{@render icon()}{@render nameButton()}<Marks {c} /></span>
    <span class="m1-row__st"><Status {c} /></span>
    <span class="m1-row__txt pp-dim">{model}</span>
    <span class="m1-row__meters"><Meters {c} reserve={false} /></span>
    <span class="m1-row__act"><WolfButton {c} /></span>
  </li>
{:else}
  <li>
    <article class="catalog-card m1-card" data-computer-card={c.id} aria-current={open ? 'true' : 'false'} onclick={click} role="presentation">
      <header class="m1-top">
        <span class="m1-top__id">{@render icon()}{@render nameButton()}</span>
        <Marks {c} />
        <span class="m1-top__act"><WolfButton {c} /></span>
      </header>
      <div class="m1-cbody">
        <div class="catalog-card__media"><div class="catalog-card__thumb m1-thumb">
          <div class="m1-plate" data-computer={c.id}>
            {#if sshOnly && c.host}
              <span class="oc-label m1-plate__label">{t('roster.plate.ssh_host')}</span>
              <dl class="pp-facts">
                <dt>{t('roster.fact.ssh_target')}</dt><dd>{c.host.ssh_target}</dd>
                <dt>{t('roster.fact.port')}</dt><dd>{c.host.ssh_port ?? t('roster.fact.port_default')}</dd>
                <dt>{t('roster.fact.socket')}</dt><dd>{c.host.socket}</dd>
                <dt>{t('roster.fact.tmux_version')}</dt><dd>{c.host.tmux_version ?? '-'}</dd>
              </dl>
            {:else}
              <Meters {c} />
            {/if}
          </div>
        </div></div>
        <div class="catalog-card__ct">
          <div class="m1-brief"><span>{model}</span><span class="pp-dim">{how}</span><span class="m1-brief__st"><Status {c} /><span class="pp-dim">{seen}</span></span></div>
        </div>
      </div>
    </article>
  </li>
{/if}
