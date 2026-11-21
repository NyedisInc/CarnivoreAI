import { LAB_CHANNEL } from './lab-selection';

let listening: BroadcastChannel | null = null;

export function listenForMenuRequests(open: () => void): void {
  if (listening || typeof BroadcastChannel === 'undefined') return;
  listening = new BroadcastChannel(LAB_CHANNEL);
  listening.addEventListener('message', (event: MessageEvent<{ kind?: string; intent?: { intent?: string } }>) => {
    if (event.data?.kind === 'intent' && event.data.intent?.intent === 'open-menu') open();
  });
}

export function stopListeningForMenuRequests(): void {
  listening?.close();
  listening = null;
}
