import { authFetch } from '../../opscenter/api/auth.svelte';
import { fetchConfig } from '../byoai/api';
import { onNativeMessage, shellHasSpeech, postToNative } from '../native-shell/shell';
import { glueText, type EngineEvents, type EngineStarter } from './controller.svelte';

interface SpeechResultList { length: number; [i: number]: { 0: { transcript: string }; length: number; isFinal?: boolean } }
interface Recognizer {
    continuous: boolean; interimResults: boolean; lang: string;
    onresult: ((ev: { results: SpeechResultList }) => void) | null;
    onerror: ((ev: { error: string }) => void) | null;
    onstart: (() => void) | null;
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
        let rec = new Ctor();
        let committed = '';
        let fin = 0;
        let lastLen = 0;
        let live = '';
        let dead = false;
        let stopped = false;
        let quiet = 0;
        const shown = () => glueText(committed, live);
        const wire = (r: Recognizer) => {
            r.continuous = true;
            r.interimResults = true;
            r.lang = navigator.language || 'en-US';
            r.onstart = () => { if (!dead) events.ready(); };
            r.onresult = (ev) => {
                const list = ev.results;
                quiet = 0;
                if (list.length < lastLen || list.length < fin) { committed = shown(); live = ''; fin = 0; }
                lastLen = list.length;
                while (fin < list.length && list[fin]?.isFinal) { committed = glueText(committed, list[fin]?.[0]?.transcript ?? ''); fin += 1; }
                let rest = '';
                for (let i = fin; i < list.length; i += 1) rest += list[i]?.[0]?.transcript ?? '';
                live = rest;
                if (!dead) events.text(shown());
            };
            r.onerror = (ev) => {
                if (dead || ev.error === 'no-speech' || ev.error === 'aborted') return;
                events.error(ev.error === 'not-allowed' || ev.error === 'service-not-allowed' ? 'blocked' : 'failed');
            };
            r.onend = () => {
                if (dead) return;
                committed = shown();
                live = ''; fin = 0; lastLen = 0;
                quiet += 1;
                if (stopped || quiet > 5) { events.end(committed); return; }
                rec = new Ctor();
                wire(rec);
                try { rec.start(); } catch { events.end(committed); }
            };
        };
        wire(rec);
        try { rec.start(); } catch { events.error('failed'); }
        return {
            stop: () => { stopped = true; rec.stop(); },
            abort: () => { dead = true; try { rec.abort(); } catch {  } },
        };
    };
}

function firstWord(t: string): string { return (t.trim().split(/\s+/)[0] ?? '').toLowerCase().replace(/[^\p{L}\p{N}]/gu, ''); }
function wordCount(t: string): number { return t.trim().split(/\s+/).filter(Boolean).length; }


export function utteranceJoiner(): { feed(text: string): string; value(): string } {
    let committed = '';
    let prev = '';
    const joined = () => [committed, prev].filter(Boolean).join(' ');
    return {
        feed(text: string): string {
            if (!text) {
                if (prev) { committed = joined(); prev = ''; }
                return joined();
            }
            if (prev && text !== prev && firstWord(text) !== firstWord(prev) && wordCount(text) < wordCount(prev)) { committed = joined(); prev = ''; }
            if (!prev && committed && text.startsWith(committed)) committed = '';
            prev = text;
            return joined();
        },
        value: joined,
    };
}

export function nativeStarter(): EngineStarter | null {
    if (!shellHasSpeech()) return null;
    return (events: EngineEvents) => {
        let off: (() => void) | null = null;
        const joiner = utteranceJoiner();
        const close = () => { off?.(); off = null; };
        off = onNativeMessage((m) => {
            if (m.type !== 'speech') return;
            if (m.kind === 'ready') { events.ready(); return; }
            if (m.kind === 'text') { events.text(joiner.feed(m.text)); return; }
            close();
            if (m.kind === 'end') { events.end(joiner.feed(m.text)); return; }
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
