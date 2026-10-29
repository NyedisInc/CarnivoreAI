<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import { formatBytes } from '../session-move/move-api';
  import type { SendCarry } from './send-api';

  interface Props {
    carry: SendCarry;
    machine: string;
    ticked: string[];
    onTick: (path: string, on: boolean) => void;
  }
  const { carry, machine, ticked, onTick }: Props = $props();

  const outside = $derived(carry.outside ?? []);
  const comes = $derived(carry.units ?? []);
  const stays = $derived([
    ...(carry.left_behind ?? []).map((l) => ({ text: l.what + (l.size != null ? ` (${formatBytes(l.size)})` : ''), why: l.why })),
    ...(carry.other_projects ?? []).map((o) => ({ text: o.path, why: t('session.send.carry.other_project', { project: o.project }) })),
    ...outside.filter((o) => !o.carryable).map((o) => ({ text: o.path + (o.size != null ? ` (${formatBytes(o.size)})` : ''), why: t('session.send.carry.update', { machine }) })),
  ]);
  const tools = $derived(carry.tools ?? []);
  const servers = $derived(carry.servers ?? []);
  const empty = $derived(!comes.length && !stays.length && !tools.length && !servers.length && !outside.some((o) => o.carryable));

  const unitName = (path: string): string => (path === '.' ? t('session.send.carry.project_folder') : path);
</script>

{#if !empty}
  <div class="stm-carry" data-send="carry">
    {#if comes.length || outside.some((o) => o.carryable)}
      <div class="stm-carry-head">{t('session.send.carry.comes')}</div>
      {#each comes as u (u.kind + u.path)}
        <div class="stm-carry-row" data-carry="comes">{unitName(u.path)}<span class="stm-carry-why">{u.state}</span></div>
      {/each}
      {#each outside.filter((o) => o.carryable) as o (o.path)}
        <div class="stm-carry-row" data-carry="outside">
          <Check label={o.path + (o.size != null ? ` (${formatBytes(o.size)})` : '')} checked={ticked.includes(o.path)} disabled={!o.tick}
            onToggle={(next) => onTick(o.path, next)} />
        </div>
      {/each}
    {/if}
    {#if stays.length}
      <div class="stm-carry-head">{t('session.send.carry.stays')}</div>
      {#each stays as s (s.text)}
        <div class="stm-carry-row" data-carry="stays">{s.text}<span class="stm-carry-why">{s.why}</span></div>
      {/each}
    {/if}
    {#if tools.length}
      <div class="stm-carry-head">{t('session.send.carry.tools')}</div>
      {#each tools as tool (tool.name)}
        <div class="stm-carry-row" data-carry="tool">{tool.name}<span class="stm-carry-why">{t(`session.send.carry.tool.${tool.status}`, { machine })}</span></div>
      {/each}
    {/if}
    {#if servers.length}
      <div class="stm-carry-head">{t('session.send.carry.servers')}</div>
      {#each servers as sv (sv.command)}
        <div class="stm-carry-row" data-carry="server">{sv.port != null ? t('session.send.carry.server_port', { port: String(sv.port) }) : t('session.send.carry.server')}<span class="stm-carry-why">{sv.command}</span></div>
      {/each}
    {/if}
  </div>
{/if}
