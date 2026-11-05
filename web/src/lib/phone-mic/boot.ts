import { legacyGlobal } from '../legacy-globals';
import { hostWindow } from '../sessions/env';
import { mountInto } from '../mount';
import PhoneMic from './PhoneMic.svelte';
import { createMic, type MicDeps } from './controller.svelte';
import { nativeStarter, recordStarter, speechStarter, transcribeReady } from './engines';

function realDeps(): MicDeps {
    return {
        claim: () => legacyGlobal<{ claim(what: string): unknown }>('TerminalInputOwnership')?.claim('mic') ?? null,
        deliver: (text, ticket) => legacyGlobal<{ injectText(term: unknown, text: string, ticket: unknown): void }>('ClipboardTools')
            ?.injectText(legacyGlobal('TerminalController'), text, ticket),
        speech: nativeStarter() ?? speechStarter(),
        record: recordStarter(),
        transcribeReady,
    };
}

export function bootPhoneMic(): void {
    let mic: ReturnType<typeof createMic> | null = null;
    Object.assign(hostWindow() ?? {}, { PhoneMic: {
        start() {
            if (!mic) {
                const host = document.createElement('div');
                host.id = 'phone-mic-host';
                document.body.appendChild(host);
                mic = createMic(realDeps());
                mountInto(host, PhoneMic, { mic });
            }
            mic.start();
        },
    } });
}
