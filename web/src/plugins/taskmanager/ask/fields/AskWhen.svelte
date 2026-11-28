<script lang="ts">
  import { Field } from '../../../sdk/ui';
  import type { AskQuestion, AskValue } from '../ask-model';
  import { mdPlain } from '../../task-manager-markdown';
  import { isoToLocal, localToIso } from './when-iso';

  let { question, value, onChange }: { question: AskQuestion; value: AskValue | undefined; onChange: (patch: AskValue) => void } = $props();
  const local = $derived(isoToLocal(value?.text ?? ''));
</script>

<Field block type="datetime-local" value={local} aria-label={mdPlain(question.prompt)} data-ask-field={question.id}
       oninput={(event) => onChange({ text: localToIso(event.currentTarget.value) })} />
