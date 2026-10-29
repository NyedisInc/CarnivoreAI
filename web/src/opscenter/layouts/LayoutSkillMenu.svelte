
<script lang="ts">
    import { t } from '../../lib/i18n/index.svelte';
    import type { SkillComplete } from './skill-complete.svelte';

    let { complete }: { complete: SkillComplete } = $props();
</script>

{#if complete.open}
    <div class="lsk popup-focus" role="listbox" id="lcb-skills" aria-label={t('layout.bar.skills')}>
        {#each complete.rows as skill, index (skill.scope + skill.name)}
            
            <div class="lsk__item" class:lsk__item--active={index === complete.active} role="option"
                id={`lcb-skill-${index}`} aria-selected={index === complete.active} tabindex="-1"
                data-skill={skill.name}
                onmousedown={(event) => { event.preventDefault(); complete.accept(index); }}>
                <span class="lsk__name">{complete.sigil}{skill.name}</span>
                <span class="lsk__scope">{t(skill.scope === 'project' ? 'layout.bar.skills.project' : 'layout.bar.skills.global')}</span>
                {#if skill.description}<span class="lsk__desc">{skill.description}</span>{/if}
            </div>
        {/each}
    </div>
{/if}

<style>
  @layer components {
      .lsk {
          position: absolute;
          top: calc(100% + 2px);
          left: 0;
          right: 0;
          z-index: 6;
          max-height: 260px;
          overflow-y: auto;
          padding: 5px;
          box-sizing: border-box;
          border-radius: 4px;
          color: var(--oc-text-primary);
          font-family: var(--font-mono);
      }

      .lsk__item {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          gap: 0 var(--oc-space-2);
          padding: var(--oc-space-1) var(--oc-space-2);
          border: 1px solid transparent;
          font-size: var(--oc-fs-body);
          cursor: pointer;
      }

      .lsk__item:hover,
      .lsk__item--active {
          border-color: var(--oc-orange);
          background: var(--oc-ground-hover);
      }

      .lsk__name {
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
      }

      .lsk__scope {
          color: var(--oc-text-muted);
          font-size: var(--oc-fs-micro);
          letter-spacing: var(--oc-tracking-label, 0.6px);
          text-transform: uppercase;
      }

      .lsk__desc {
          grid-column: 1 / -1;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          color: var(--oc-text-secondary);
          font-size: var(--oc-fs-micro);
      }

      @media (pointer: coarse) {
          .lsk__item {
              min-height: 44px;
          }
      }
  }
</style>
