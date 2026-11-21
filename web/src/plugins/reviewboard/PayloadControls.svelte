<script lang="ts">
  import { t } from '../sdk';
  import { Button, EditorControls, IconButton, saveLight, type SaveLight } from '../sdk/ui';
  import type { BoardRevision } from './board-model';
  import type { PayloadLoop } from './payload-loop.svelte';
  import { savesOf } from './payload-model';

  interface Props {
    revision: BoardRevision;
    loop: PayloadLoop;
    noteOpen: boolean;
    onnote: () => void;
    onsend: () => void;
    onstep: (delta: number) => void;
  }

  let { revision, loop, noteOpen, onnote, onsend, onstep }: Props = $props();

  const saves = $derived(savesOf(revision));
  const viewed = $derived(saves.find((s) => s.n === loop.viewing) ?? null);
  const position = $derived(
    viewed ? t('cplug.reviewboard.payload.position', { n: viewed.n, total: saves.length }) : t(loop.payload ? 'cplug.reviewboard.payload.draft' : 'cplug.reviewboard.payload.none'),
  );
  const reason = $derived(loop.draftRefused ? t('cplug.reviewboard.payload.refused') : loop.draftError || t('cplug.reviewboard.payload.unknown'));
  const disk = $derived<SaveLight>(
    loop.draftState === 'idle' ? saveLight('no-session', 'idle', false)
      : loop.draftState === 'saved' ? saveLight('loaded', 'idle', false)
        : loop.draftState === 'saving' ? saveLight('loaded', 'saving', true)
          : loop.draftState === 'failed' ? saveLight('loaded', loop.draftRefused ? 'too_large' : 'failed', true)
            : saveLight('loaded', 'idle', true),
  );
  const failedText = $derived(t('cplug.reviewboard.payload.not_saved', { reason }));
  const diskProps = $derived<Record<string, string>>({
    'data-payload-light': '',
    'data-draft-state': loop.draftState,
    ...(loop.draftState === 'failed' ? { title: failedText, 'aria-label': failedText } : {}),
  });
</script>

<span class="rb-controls" data-payload-controls>
  <EditorControls showMode={false} light={disk} saveState={loop.draftState} saveDisabled={disk.tone === 'off'} saveProps={diskProps} onSave={() => void loop.saveNow()} />

  <span class="rb-saves" data-payload-saves>
    <IconButton label={t('cplug.reviewboard.payload.older')} icon="chevron-left" variant="quiet" iconSize={16}
                disabled={saves.length === 0 || viewed?.n === 1} data-payload-older onclick={() => onstep(-1)} />
    <span class="rb-label rb-position" data-payload-position>{position}</span>
    <IconButton label={t('cplug.reviewboard.payload.newer')} icon="chevron-right" variant="quiet" iconSize={16}
                disabled={!viewed} data-payload-newer onclick={() => onstep(1)} />
  </span>

  <IconButton label={t('cplug.reviewboard.payload.note_key')} icon="chat" variant="quiet" iconSize={16}
              aria-expanded={noteOpen} data-filled={loop.note.trim() !== ''} data-payload-note-key onclick={onnote} />

  <Button size="sm" variant={loop.payload ? 'confirm' : 'secondary'} title={t('cplug.reviewboard.payload.send_title')}
          disabled={!loop.payload || loop.sending} data-payload-send onclick={onsend}>{t('cplug.reviewboard.payload.send')}</Button>
</span>
