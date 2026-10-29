
const ICON_OF: Readonly<Record<string, string>> = {
    chat: 'chat', embed: 'cap-embed', decide: 'cap-decide', agent: 'bot', speak: 'cap-speak',
    transcribe: 'cap-transcribe', image: 'image', video: 'cap-video', audio: 'cap-audio',
};

export const capabilityIcon = (capability: string): string => ICON_OF[capability] ?? 'cube';
