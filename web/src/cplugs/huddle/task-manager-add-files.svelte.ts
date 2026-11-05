import { createAttachments } from './task-manager-attachments.svelte';
import { dragOverFiles, dropFiles, pasteFiles } from './task-manager-file-transfer';
import { stageFile } from './task-manager-files-api';

export interface AddFiles {
  readonly attached: ReturnType<typeof createAttachments>;
  readonly dropping: boolean;
  readonly staging: boolean;
  followTarget(): void;
  onPaste(event: ClipboardEvent): void;
  onDragOver(event: DragEvent): void;
  onDragLeave(): void;
  onDrop(event: DragEvent): void;
}

export function createAddFiles(target: () => string): AddFiles {
  const attached = createAttachments((file) => stageFile(target(), file));
  let dropping = $state(false);
  let staged = target();

  return {
    attached,
    get dropping() { return dropping; },
    get staging() { return attached.busy; },
    followTarget() {
      const now = target();
      if (now !== staged) { staged = now; attached.clear(); }
    },
    onPaste: (event) => pasteFiles(event, attached.add),
    onDragOver(event) { if (dragOverFiles(event)) dropping = true; },
    onDragLeave() { dropping = false; },
    onDrop(event) { dropping = false; dropFiles(event, attached.add); },
  };
}
