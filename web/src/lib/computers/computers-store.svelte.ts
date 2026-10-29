
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { t } from '../i18n/index.svelte';
import { apiErrorMessageOr } from '../errors/failure-reason';
import * as api from './computers-api';

export const COMPUTERS_POLL_MS = 15000;
export const JOIN_POLL_MS = 1000;

export const computers: Resource<api.ComputersView> = resource<api.ComputersView>(api.readComputers, {
  intervalMs: COMPUTERS_POLL_MS,
  name: 'computers',
  topics: ['computers', 'pack_machines'],
  body: { key: 'computers', read: (body) => (body as api.ComputersView | null) ?? null },
});

export const activity = $state<{
  busy: string | null;
  error: string | null;
  invite: api.MintedInvite | null;
  inviteSeen: boolean;
  notTold: string | null;
  preview: api.AddPreview | null;
  join: api.JoinStatus | null;
  looking: boolean;
}>({ busy: null, error: null, invite: null, inviteSeen: false, notTold: null, preview: null, join: null, looking: false });

let joinTimer: ReturnType<typeof setTimeout> | null = null;

async function write(key: string, send: () => Promise<void>): Promise<void> {
  if (activity.busy) return;
  activity.busy = key;
  activity.error = null;
  try {
    await send();
  } catch (error) {
    activity.error = apiErrorMessageOr(error, t('computers.error.failed'));
  } finally {
    activity.busy = null;
    await computers.refresh(true);
  }
}

export function addComputer(): Promise<void> {
  return write('invite', async () => {
    activity.invite = await api.mintInvite();
    activity.inviteSeen = false;
  });
}

export function dropInvite(): Promise<void> {
  const invite = activity.invite;
  activity.invite = null;
  if (invite === null) return Promise.resolve();
  return write('invite', async () => {
    await api.cancelInvite(invite.id);
  });
}

export function reconcileInvite(view: api.ComputersView | null): void {
  if (activity.invite === null || view === null) return;
  const id = activity.invite.id;
  if (view.invites.some((i) => i.id === id)) activity.inviteSeen = true;
  else if (activity.inviteSeen) activity.invite = null;
}

export function remove(installId: string, label: string): Promise<void> {
  return write(`remove:${installId}`, async () => {
    const done = await api.removeComputer(installId);
    activity.notTold = done.peer_told ? null : label;
  });
}

export function setDirection(installId: string, canControl: boolean): Promise<void> {
  return write(`direction:${installId}`, async () => {
    await api.putDirection(installId, canControl ? 'both' : 'one_way');
  });
}

export async function check(target: string, port: number | null): Promise<void> {
  if (activity.busy) return;
  activity.busy = 'preview';
  activity.error = null;
  activity.preview = null;
  try {
    activity.preview = await api.previewAdd(target, port);
  } catch (error) {
    activity.error = apiErrorMessageOr(error, t('computers.error.failed'));
  } finally {
    activity.busy = null;
  }
}

export function addOverSsh(target: string, port: number | null): Promise<void> {
  const preview = activity.preview;
  if (preview === null) return Promise.resolve();
  return write('add', async () => {
    await api.startAdd(target, port, preview.host_key_sha256);
    activity.preview = null;
  });
}

async function pollJoin(): Promise<void> {
  joinTimer = null;
  try {
    activity.join = await api.readJoin();
  } catch (error) {
    activity.error = apiErrorMessageOr(error, t('computers.error.failed'));
    return;
  }
  const join = activity.join;
  const waitingOnPick = join !== null && join.state === 'finding' && join.candidates.length > (activity.looking ? 0 : 1);
  if (join !== null && !waitingOnPick && ['waiting_relay', 'finding', 'connecting', 'checking', 'linking'].includes(join.state)) {
    joinTimer = setTimeout(() => void pollJoin(), JOIN_POLL_MS);
  } else {
    await computers.refresh(true);
  }
}

export function stopJoinPoll(): void {
  if (joinTimer !== null) clearTimeout(joinTimer);
  joinTimer = null;
}

export async function join(body: api.JoinBody): Promise<void> {
  if (activity.busy) return;
  activity.busy = 'join';
  activity.error = null;
  try {
    activity.join = await api.startJoin(body);
    activity.looking = false;
    stopJoinPoll();
    joinTimer = setTimeout(() => void pollJoin(), JOIN_POLL_MS);
  } catch (error) {
    activity.error = apiErrorMessageOr(error, t('computers.error.failed'));
  } finally {
    activity.busy = null;
  }
}

export async function look(): Promise<void> {
  if (activity.busy) return;
  activity.busy = 'join';
  activity.error = null;
  try {
    activity.join = await api.startLook();
    activity.looking = true;
    stopJoinPoll();
    joinTimer = setTimeout(() => void pollJoin(), JOIN_POLL_MS);
  } catch (error) {
    activity.error = apiErrorMessageOr(error, t('computers.error.failed'));
  } finally {
    activity.busy = null;
  }
}

export function leave(): Promise<void> {
  return write('leave', async () => {
    const done = await api.leavePack();
    activity.notTold = done.main_told ? null : 'main';
  });
}
