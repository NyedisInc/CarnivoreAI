import { MAX_PER_REPLY, readyIds } from './task-manager-files';
import type { UploadedFile } from './task-manager-files-api';

export interface Chip {
  key: number;
  name: string;
  size: number;
  status: 'uploading' | 'ready' | 'failed';
  ref?: UploadedFile;
  error?: string;
}

export function createAttachments(upload: (file: File) => Promise<UploadedFile>): {
  readonly chips: Chip[];
  readonly busy: boolean;
  readonly ids: string[];
  add: (files: File[]) => void;
  remove: (key: number) => void;
  clear: () => void;
} {
  let chips = $state<Chip[]>([]);
  let next = 0;

  function start(file: File): void {
    const chip: Chip = { key: next++, name: file.name, size: file.size, status: 'uploading' };
    chips.push(chip);
    const key = chip.key;
    const settle = (change: Partial<Chip>): void => {
      const live = chips.find((c) => c.key === key);
      if (live) Object.assign(live, change);
    };
    upload(file).then(
      (ref) => settle({ status: 'ready', ref }),
      (error: unknown) => settle({ status: 'failed', error: error instanceof Error ? error.message : String(error) }),
    );
  }

  return {
    get chips() { return chips; },
    get busy() { return chips.some((c) => c.status === 'uploading'); },
    get ids() { return readyIds(chips); },
    add(files) {
      for (const file of files.slice(0, Math.max(0, MAX_PER_REPLY - chips.length))) start(file);
    },
    remove(key) { chips = chips.filter((c) => c.key !== key); },
    clear() { chips = []; },
  };
}
