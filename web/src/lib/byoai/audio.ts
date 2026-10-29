
export function bytesOfBase64(data: string): Uint8Array {
    const raw = atob(data);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
    return bytes;
}

export async function playBase64(data: string): Promise<void> {
    const Ctx = globalThis.AudioContext ?? (globalThis as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) throw new Error('web audio is not available in this browser');
    const context = new Ctx();
    try {
        const bytes = bytesOfBase64(data);
        const buffer = await context.decodeAudioData(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer);
        const source = context.createBufferSource();
        source.buffer = buffer;
        source.connect(context.destination);
        await new Promise<void>((resolve) => {
            source.onended = () => resolve();
            source.start();
        });
    } finally {
        await context.close();
    }
}
