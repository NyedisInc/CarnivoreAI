import type { Component } from 'svelte';
import { mountPanel, unmountPanel } from '../mount';
import MoveFolderModal from './MoveFolderModal.svelte';

const MODAL_ID = 'move-folder-modal';

const MODAL = MoveFolderModal as unknown as Component<{ uuid: string; name: string; onClose: () => void }, Record<string, unknown>>;

export interface MoveSubject {
  sessionUuid: string;
  name: string;
}

function close(): void {
  unmountPanel(MODAL_ID);
}

function open(subject: MoveSubject): boolean {
  return mountPanel(MODAL_ID, MODAL, { uuid: subject.sessionUuid, name: subject.name, onClose: close }) !== null;
}

export const moveToFolderBridge = { open, close };
