import type { SyncPeer } from './api';

export type PeerState = 'off' | 'older' | 'disconnected' | 'refused' | 'rate_limited' | 'error' | 'waiting' | 'synced';

export function peerState(peer: SyncPeer): PeerState {
    if (!peer.enabled) return 'off';
    if (peer.protocol === 'older') return 'older';
    if (!peer.connected) return 'disconnected';
    switch (peer.last_result) {
        case 'refused': return 'refused';
        case 'rate_limited': return 'rate_limited';
        case 'error': return 'error';
        case 'ok':
        case 'no_change': return 'synced';
        default: return 'waiting';
    }
}

export const stateKey = (state: PeerState): string => `settings.notify.sync.state.${state}`;
