import { authFetch } from '../../opscenter/api/auth.svelte';
import { fetchConfig } from '../byoai/api';
import { inNativeShell, onNativeMessage, postToNative } from '../native-shell/shell';
import type { EngineEvents, EngineStarter } from './controller.svelte';

interface SpeechResultList { length: number; [i: number]: { 0: { transcript: string }; length: number } }
interface Recognizer {
    continuous: boolean; interimResults: boolean; lang: string;
    onresult: ((ev: { results: SpeechResultList }) => void) | null;
    onerror: ((ev: { error: string }) => void) | null;
    onend: (() => void) | null;
    start(): void; stop(): void; abort(): void;
}

function recognizerCtor(): (new () => Recognizer) | null {
    const w: Window & { SpeechRecognition?: new () => Recognizer; webkitSpeechRecognition?: new () => Recognizer } = window;
    return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function speechStarter(): EngineStarter | null {
    const Ctor = recognizerCtor();
    if (!Ctor) return null;
    return (events: EngineEvents) => {
        const rec = new Ctor();
        let heard = '';
        let dead = false;
        rec.continuous = true;
        rec.interimResults = true;
        rec.lang = navigator.language || 'en-US';
        rec.onresult = (ev) => {
            let all = '';
            for (let i = 0; i < ev.results.length; i += 1) all += ev.results[i]?.[0]?.transcript ?? '';
            heard = all;
            if (!dead) events.text(all);
        };
        rec.onerror = (ev) => {
            if (dead || ev.error === 'no-speech' || ev.error === 'aborted') return;
            events.error(ev.error === 'not-allowed' || ev.error === 'service-not-allowed' ? 'blocked' : 'failed');
        };
        rec.onend = () => { if (!dead) events.end(heard); };
        try { rec.start(); } catch { events.error('failed'); }
        return {
            stop: () => rec.stop(),
            abort: () => { dead = true; try { rec.abort(); } catch {  } },
        };
    };
}

export function nativeStarter(): EngineStarter | null {
    if (!inNativeShell()) return null;
    return (events: EngineEvents) => {
        let off: (() => void) | null = null;
        const close = () => { off?.(); off = null; };
        off = onNativeMessage((m) => {
            if (m.type !== 'speech') return;
            if (m.kind === 'text') { events.text(m.text); return; }
            close();
            if (m.kind === 'end') { events.end(m.text); return; }
            events.error(m.reason === 'denied' || m.reason === 'restricted' ? 'blocked' : m.reason === 'unavailable' ? 'unavailable' : 'failed');
        });
        postToNative({ type: 'speechStart' });
        return {
            stop: () => { postToNative({ type: 'speechStop' }); },
            abort: () => { const open = off !== null; close(); if (open) postToNative({ type: 'speechCancel' }); },
        };
    };
}

function recordMime(): string {
    const want = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm', 'audio/ogg'];
    return want.find((m) => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(m)) ?? '';
}

export function recordStarter(): EngineStarter | null {
    if (typeof MediaRecorder === 'undefined' || !navigator.mediaDevices?.getUserMedia) return null;
    return (events: EngineEvents) => {
        let dead = false;
        let recorder: MediaRecorder | null = null;
        let stream: MediaStream | null = null;
        const chunks: Blob[] = [];
        const closeMic = () => stream?.getTracks().forEach((t) => t.stop());
        navigator.mediaDevices.getUserMedia({ audio: true }).then((s) => {
            stream = s;
            if (dead) { closeMic(); return; }
            const mime = recordMime();
            recorder = new MediaRecorder(s, mime ? { mimeType: mime } : undefined);
            recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
            recorder.onstop = () => {
                closeMic();
                if (dead) return;
                const type = (recorder?.mimeType || mime || 'audio/webm').split(';')[0] ?? 'audio/webm';
                void transcribe(new Blob(chunks, { type }), type).then(
                    (text) => { if (!dead) events.end(text); },
                    () => { if (!dead) events.error('failed'); },
                );
            };
            recorder.start();
        }, () => { if (!dead) events.error('blocked'); });
        return {
            stop: () => { if (recorder && recorder.state !== 'inactive') recorder.stop(); else events.end(''); },
            abort: () => { dead = true; if (recorder && recorder.state !== 'inactive') recorder.stop(); closeMic(); },
        };
    };
}

export async function transcribeReady(): Promise<boolean> {
    return !!(await fetchConfig()).defaults?.transcribe?.connection;
}

async function transcribe(audio: Blob, mime: string): Promise<string> {
    const target = (await fetchConfig()).defaults?.transcribe;
    if (!target?.connection) throw new Error('no_transcribe');
    const q = new URLSearchParams({ connection: target.connection });
    if (target.model) q.set('model', target.model);
    const out = await authFetch<{ text?: string }>(`/ai/transcribe?${q}`, { method: 'POST', body: audio, headers: { 'Content-Type': mime } });
    return out?.text ?? '';
}
