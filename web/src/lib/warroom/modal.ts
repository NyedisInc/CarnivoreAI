import { openModal } from '../modal';
import type { SessionInfo } from '../../opscenter/api/types';
import WarroomModal from './WarroomModal.svelte';

let current: (() => void) | null = null;

export function openWarroomModal(info: SessionInfo): void {
  current?.();
  let mine: (() => void) | null = null;
  void openModal<null, { info: SessionInfo; register: (close: () => void) => void }>(WarroomModal, {
    info,
    register: (close) => {
      mine = close;
      current = close;
    },
  }).then(() => {
    if (current === mine) current = null;
  });
}
