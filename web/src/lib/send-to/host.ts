import type { Component } from 'svelte';
import { mountPanel, unmountPanel } from '../mount';
import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { ADD_TO_CASCADE_CONTAINER_ID } from '../add-to-menu/host';
import { packMachines, type PackMachine } from '../pack-machines/pack-machines-store.svelte';
import { t } from '../i18n/index.svelte';
import SendToModal from './SendToModal.svelte';
import { computerBlock } from './send-api';

const MODAL_ID = 'send-to-modal';

const CASCADE = CascadeMenu as unknown as Component<
  { root: MenuNode[]; anchor: HTMLElement | null; label: string; onClose: () => void; nestedIn?: HTMLElement | null },
  Record<string, unknown>
>;
const MODAL = SendToModal as unknown as Component<
  { uuid: string; name: string; machine: PackMachine; projectName: string | null; onClose: () => void },
  Record<string, unknown>
>;

export interface SendSubject {
  sessionUuid: string;
  name: string;
  projectName: () => Promise<string | null>;
}

interface OpenOptions {
  parentEl?: HTMLElement | null;
  onFinish?: () => void;
}

function close(): void {
  unmountPanel(ADD_TO_CASCADE_CONTAINER_ID);
}

function closeModal(): void {
  unmountPanel(MODAL_ID);
}

export function computerNodes(machines: PackMachine[], subject: SendSubject, finish: () => void): MenuNode[] {
  const peers = machines.filter((m) => !m.is_self);
  if (peers.length === 0) {
    return [{ id: 'none', label: t('session.send.none'), blocked: t('session.send.none'), icon: 'wolf' }];
  }
  return peers.map((machine) => {
    const label = machine.label || machine.install_id.slice(0, 8);
    const why = computerBlock(machine);
    return {
      id: machine.install_id,
      label,
      icon: 'wolf',
      ...(why ? { blocked: why } : machine.is_master ? { badge: t('pack.machines.master') } : {}),
      run: () => {
        finish();
        void subject.projectName().then((projectName) => {
          mountPanel(MODAL_ID, MODAL, { uuid: subject.sessionUuid, name: subject.name, machine, projectName, onClose: closeModal });
        });
      },
    };
  });
}

function openForSession(anchor: HTMLElement, subject: SendSubject, opts: OpenOptions = {}): void {
  const finish = (): void => {
    close();
    opts.onFinish?.();
  };
  const show = (): void => {
    mountPanel(ADD_TO_CASCADE_CONTAINER_ID, CASCADE, {
      root: computerNodes(packMachines.data?.machines ?? [], subject, finish), anchor, label: t('session.send.cascade', { name: subject.name }), onClose: close, nestedIn: opts.parentEl ?? null,
    });
  };
  if (packMachines.data) {
    show();
    void packMachines.refresh(true);
  } else {
    void packMachines.refresh(true).then(show);
  }
}

export const sendToBridge = { openForSession, close, closeModal };
