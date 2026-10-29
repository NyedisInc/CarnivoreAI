import { clockTime, elapsed } from '../../opscenter/lib/format';
import type { PipelineStatus } from './api';

export type Tone = 'ok' | 'wait' | 'bad' | 'off';

export interface Words {
    key: string;
    params: Record<string, string | number>;
    tone: Tone;
}

export const pluginNameKey = (id: string): string => `pipeline.plugin_name.${id}`;

export function statusWords(status: PipelineStatus, nameOf: (id: string) => string): Words {
    switch (status.state) {
        case 'behind':
            return { key: 'pipeline.status.behind', params: { files: status.lag.files, lag: elapsed(status.lag.seconds) }, tone: 'wait' };
        case 'stalled':
            return {
                key: 'pipeline.status.stalled',
                params: { time: status.stalled_since === null ? '' : clockTime(status.stalled_since * 1000) },
                tone: 'bad',
            };
        case 'rebuilding':
            return { key: 'pipeline.status.rebuilding', params: { plugin: status.rebuilding.map(nameOf).join(', ') }, tone: 'wait' };
        case 'off':
            return { key: 'pipeline.status.off', params: {}, tone: 'off' };
        default:
            return { key: 'pipeline.status.caught_up', params: {}, tone: 'ok' };
    }
}
