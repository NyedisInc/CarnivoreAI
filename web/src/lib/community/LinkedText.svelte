
<script lang="ts">
    import { pieces } from './linkify';

    interface Props {
        text: string;
    }

    const { text }: Props = $props();
    const parts = $derived(pieces(text));
</script>

<span class="ltext">{#each parts as part}{#if part.href}<a
                    class="ltext__link"
                    href={part.href}
                    target="_blank"
                    rel="nofollow ugc noopener noreferrer">{part.text}</a>{:else}{part.text}{/if}{/each}</span>

<style>
  @layer components {
    .ltext {
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }
    .ltext__link {
        color: var(--oc-cyan);
        text-decoration: underline;
    }
  }
</style>
