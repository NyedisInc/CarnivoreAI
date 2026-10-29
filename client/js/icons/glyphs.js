/* <path> */

export const GLYPH_VIEWBOX = '0 0 16 16';
export const GLYPH_SIZE = 16;


export const GLYPHS = {
    gear: [
        { tag: 'circle', cx: '8', cy: '8', r: '4.2', stroke: 'currentColor', 'stroke-width': '1.5' },
        { tag: 'circle', cx: '8', cy: '8', r: '1.6', stroke: 'currentColor', 'stroke-width': '1.5' },
        { tag: 'path', d: 'M8 3.8V2.2', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round' },
        { tag: 'path', d: 'M11.64 5.9L13.02 5.1', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round' },
        { tag: 'path', d: 'M11.64 10.1L13.02 10.9', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round' },
        { tag: 'path', d: 'M8 12.2V13.8', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round' },
        { tag: 'path', d: 'M4.36 10.1L2.98 10.9', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round' },
        { tag: 'path', d: 'M4.36 5.9L2.98 5.1', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round' },
    ],
    pencil: [
        {
            tag: 'path',
            d: 'M10.5 2.5L13.5 5.5L5.5 13.5H2.5V10.5L10.5 2.5Z',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
        {
            tag: 'path',
            d: 'M9 4L12 7',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
        },
    ],
    archive: [
        {
            tag: 'rect',
            x: '2',
            y: '2.75',
            width: '12',
            height: '3',
            rx: '0.75',
            stroke: 'currentColor',
            'stroke-width': '1.5',
        },
        {
            tag: 'path',
            d: 'M3.25 5.75V12.5C3.25 12.9142 3.58579 13.25 4 13.25H12C12.4142 13.25 12.75 12.9142 12.75 12.5V5.75',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linejoin': 'round',
        },
        {
            tag: 'path',
            d: 'M6.5 8.5H9.5',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
        },
    ],
    close: [
        {
            tag: 'path',
            d: 'M4 4L12 12',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
        },
        {
            tag: 'path',
            d: 'M12 4L4 12',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
        },
    ],
    trash: [
        {
            tag: 'path',
            d: 'M3 4.5H13',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
        },
        {
            tag: 'path',
            d: 'M5.5 4.5V3.25C5.5 2.83579 5.83579 2.5 6.25 2.5H9.75C10.1642 2.5 10.5 2.83579 10.5 3.25V4.5',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
        {
            tag: 'path',
            d: 'M4.5 4.5L5 12.75C5 13.1642 5.33579 13.5 5.75 13.5H10.25C10.6642 13.5 11 13.1642 11 12.75L11.5 4.5',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
        {
            tag: 'path',
            d: 'M6.5 6.75V11',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
        },
        {
            tag: 'path',
            d: 'M9.5 6.75V11',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
        },
    ],
    /* already exists */
    restart: [
        {
            tag: 'path',
            d: 'M13 8A5 5 0 1 1 11.4 4.3',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
        },
        {
            tag: 'path',
            d: 'M12.9 1.9V5.1H9.7L12.9 1.9Z',
            fill: 'currentColor',
        },
    ],
    'envelope-outline': [
        {
            tag: 'rect',
            x: '2',
            y: '3.5',
            width: '12',
            height: '9',
            rx: '1.25',
            stroke: 'currentColor',
            'stroke-width': '1.5',
        },
        {
            tag: 'path',
            d: 'M2.5 4.25L8 8.5L13.5 4.25',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    'envelope-filled': [
        {
            tag: 'rect',
            x: '2',
            y: '3.5',
            width: '12',
            height: '9',
            rx: '1.25',
            stroke: 'currentColor',
            'stroke-width': '1.5',
        },
        {
            tag: 'path',
            d: 'M2.5 4.25L8 8.5L13.5 4.25',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
        {
            tag: 'circle',
            cx: '12.5',
            cy: '3.5',
            r: '2.5',
            fill: 'currentColor',
            stroke: 'var(--color-bg, #000)',
            'stroke-width': '0.75',
        },
    ],
    wrench: [
        {
            tag: 'path',
            d: 'M9.8 4.2a.67.67 0 0 0 0 .93l1.07 1.07a.67.67 0 0 0 .93 0l2.51-2.51a4 4 0 0'
                + ' 1-5.29 5.29l-4.61 4.61a1.41 1.41 0 0 1-2-2l4.61-4.61a4 4 0 0 1 5.29-5.29z',
            fill: 'currentColor',
        },
    ],
    cube: [
        {
            tag: 'path',
            d: 'M8 1.75 14 5.1v5.8L8 14.25 2 10.9V5.1z',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linejoin': 'round',
        },
        {
            tag: 'path',
            d: 'M2 5.1 8 8.45l6-3.35M8 8.45v5.8',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    telescope: [
        {
            tag: 'path',
            d: 'M3.42 7.35L11.08 2.06L13.12 5.74L4.58 9.45Z',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linejoin': 'round',
        },
        {
            tag: 'path',
            d: 'M7.14 8.33L5.1 14M7.14 8.33L9.5 14',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
        },
    ],
    /*  hidden  */
    coffee: [
        {
            tag: 'path',
            d: 'M2.75 7.25H11.25V10.5A3 3 0 0 1 8.25 13.5H5.75A3 3 0 0 1 2.75 10.5Z',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linejoin': 'round',
        },
        {
            tag: 'path',
            d: 'M11.25 8.25H12.25A1.75 1.75 0 0 1 12.25 11.75H11',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
        },
        {
            tag: 'path',
            d: 'M4.75 5.5C4.1 4.75 5.4 4 4.75 3',
            stroke: 'currentColor',
            'stroke-width': '1.2',
            'stroke-linecap': 'round',
            class: 'kaw-steam kaw-steam-1',
        },
        {
            tag: 'path',
            d: 'M7 5.5C6.35 4.5 7.65 3.5 7 2',
            stroke: 'currentColor',
            'stroke-width': '1.2',
            'stroke-linecap': 'round',
            class: 'kaw-steam kaw-steam-2',
        },
        {
            tag: 'path',
            d: 'M9.25 5.5C8.6 4.75 9.9 4 9.25 3',
            stroke: 'currentColor',
            'stroke-width': '1.2',
            'stroke-linecap': 'round',
            class: 'kaw-steam kaw-steam-3',
        },
    ],
    copy: [
        {
            tag: 'rect',
            x: '5.5',
            y: '5.5',
            width: '8',
            height: '8',
            rx: '1.5',
            stroke: 'currentColor',
            'stroke-width': '1.5',
        },
        {
            tag: 'path',
            d: 'M10.5 3.25C10.5 2.83579 10.1642 2.5 9.75 2.5H3.25C2.83579 2.5 2.5 2.83579 2.5 3.25V9.75C2.5 10.1642 2.83579 10.5 3.25 10.5H3.5',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    folder: [
        {
            tag: 'path',
            d: 'M2 4.25C2 3.69772 2.44772 3.25 3 3.25H6.5L7.75 4.75H13C13.5523 4.75 14 5.19772 14 5.75V11.25C14 11.8023 13.5523 12.25 13 12.25H3C2.44772 12.25 2 11.8023 2 11.25V4.25Z',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linejoin': 'round',
        },
    ],
    building: [
        {
            tag: 'path',
            d: 'M3.5 14.5V2.5C3.5 1.95 3.95 1.5 4.5 1.5H11.5C12.05 1.5 12.5 1.95 12.5 2.5V14.5M1.5 14.5H14.5'
                + 'M6.2 4.6H6.8M9.2 4.6H9.8M6.2 7.6H6.8M9.2 7.6H9.8M6.8 14.5V11.2H9.2V14.5',
            stroke: 'currentColor',
            'stroke-width': '1.4',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    'folder-tree': [
        {
            tag: 'path',
            d: 'M0.9 2.65C0.9 2.236 1.236 1.9 1.65 1.9H4.15L5.15 3.15H7.65C8.064 3.15 8.4 3.486 8.4 3.9'
                + 'V7.65C8.4 8.064 8.064 8.4 7.65 8.4H1.65C1.236 8.4 0.9 8.064 0.9 7.65V2.65Z',
            stroke: 'currentColor',
            'stroke-width': '1.4',
            'stroke-linejoin': 'round',
        },
        {
            tag: 'path',
            d: 'M4.9 6.65C4.9 6.236 5.236 5.9 5.65 5.9H8.15L9.15 7.15H11.65C12.064 7.15 12.4 7.486 12.4 7.9'
                + 'V11.65C12.4 12.064 12.064 12.4 11.65 12.4H5.65C5.236 12.4 4.9 12.064 4.9 11.65V6.65Z',
            stroke: 'currentColor',
            'stroke-width': '1.4',
            'stroke-linejoin': 'round',
        },
    ],
    pin: [
        {
            tag: 'path',
            d: 'M8 11.5V15M3.5 11.5h9l-1.4-2.6V2.5H4.9v6.4z',
            stroke: 'currentColor',
            'stroke-width': '1.3',
            'stroke-linejoin': 'round',
            'stroke-linecap': 'round',
        },
    ],
    bookmark: [
        {
            tag: 'path',
            d: 'M4.25 2.25H11.75V13.75L8 10.75L4.25 13.75Z',
            stroke: 'currentColor',
            'stroke-width': '1.4',
            'stroke-linejoin': 'round',
        },
    ],
    rewind: [
        {
            tag: 'path',
            d: 'M7.5 4L3.5 8L7.5 12M12.5 4L8.5 8L12.5 12',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    eye: [
        {
            tag: 'path',
            d: 'M1.5 8C3 5 5.3 3.75 8 3.75S13 5 14.5 8C13 11 10.7 12.25 8 12.25S3 11 1.5 8Z',
            stroke: 'currentColor',
            'stroke-width': '1.4',
            'stroke-linejoin': 'round',
        },
        { tag: 'circle', cx: '8', cy: '8', r: '1.9', stroke: 'currentColor', 'stroke-width': '1.4' },
    ],
    'bookmark-plus': [
        {
            tag: 'path',
            d: 'M4.25 2.25H11.75V13.75L8 10.75L4.25 13.75Z',
            stroke: 'currentColor',
            'stroke-width': '1.4',
            'stroke-linejoin': 'round',
        },
        {
            tag: 'path',
            d: 'M8 4.5V8.5M6 6.5H10',
            stroke: 'currentColor',
            'stroke-width': '1.3',
            'stroke-linecap': 'round',
        },
    ],
    terminal: [
        {
            tag: 'rect',
            x: '2',
            y: '2.5',
            width: '12',
            height: '11',
            rx: '1.5',
            stroke: 'currentColor',
            'stroke-width': '1.5',
        },
        {
            tag: 'path',
            d: 'M5 6.5L7.5 9L5 11.5',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
        {
            tag: 'path',
            d: 'M8.5 11.5H11',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
        },
    ],
    globe: [
        {
            tag: 'circle',
            cx: '8',
            cy: '8',
            r: '6',
            stroke: 'currentColor',
            'stroke-width': '1.5',
        },
        {
            tag: 'path',
            d: 'M2 8H14',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
        },
        {
            tag: 'path',
            d: 'M8 2C10.5 2 10.5 14 8 14C5.5 14 5.5 2 8 2Z',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linejoin': 'round',
        },
    ],
    wolf: [
        {
            tag: 'path',
            d: 'M4.2 22.0C4.25 21.5 4.2 20.02 4.5 19.0C4.8 17.98 5.33 16.87 6.0 15.9C6.67 14.93 7.71 14.03 8.5 13.2'
                + 'C9.29 12.37 10.38 11.31 10.75 10.93L7.21 10.85L11.71 7.85C11.84 7.71 12.05 7.29 12.47 7.01'
                + 'C12.89 6.73 13.55 6.64 14.23 6.2C14.91 5.76 15.69 5.1 16.53 4.38C17.38 3.66 18.84 2.3 19.3 1.88'
                + 'L20.27 2.22L17.42 7.74L21.62 5.9C21.59 6.22 21.89 7.06 21.46 7.84C21.03 8.62 19.65 9.7 19.03 10.58'
                + 'C18.41 11.46 17.97 12.69 17.76 13.11C17.92 13.56 18.46 14.85 18.7 15.8C18.94 16.75 19.17 17.77 19.2 18.8'
                + 'C19.23 19.83 18.95 21.47 18.9 22.0L4.2 22.0Z',
            transform: 'scale(0.6667)',
            stroke: 'currentColor',
            'stroke-width': '2.25',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
        {
            tag: 'circle',
            cx: '14.89',
            cy: '8.19',
            r: '0.75',
            transform: 'scale(0.6667)',
            fill: 'currentColor',
            stroke: 'none',
        },
    ],
    grid: [
        {
            tag: 'rect',
            x: '2',
            y: '2',
            width: '12',
            height: '12',
            rx: '1.5',
            stroke: 'currentColor',
            'stroke-width': '1.5',
        },
        {
            tag: 'path',
            d: 'M2 8H14',
            stroke: 'currentColor',
            'stroke-width': '1.5',
        },
        {
            tag: 'path',
            d: 'M8 2V14',
            stroke: 'currentColor',
            'stroke-width': '1.5',
        },
    ],
    home: [
        {
            tag: 'path',
            d: 'M2 6.67L8 2L14 6.67M3.33 6V14H6.67V9.33H9.33V14H12.67V6',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    star: [
        {
            tag: 'path',
            d: 'M8 1.33L10 5.33L14.67 6L11.33 9.33L12 14L8 12L4 14L4.67 9.33L1.33 6L6 5.33Z',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    bolt: [
        {
            tag: 'path',
            d: 'M9.33 0.67L2.67 8.67H7.33L6.67 15.33L14 6H8.67Z',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    bell: [
        {
            tag: 'path',
            d: 'M3.33 11.33h9.33l-1.33-2V6a3.33 3.33 0 0 0-6.67 0v3.33ZM6.67 13.33h2.67M8 1.33v1.33',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    chat: [
        {
            tag: 'path',
            d: 'M2.67 2.67h10.67v8H6.67l-3.33 3.33v-3.33H2V3.33Z',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    code: [
        {
            tag: 'path',
            d: 'm5.33 3.33-4 4.67 4 4.67m5.33-9.33 4 4.67-4 4.67m-3.33 0.67 1.33-10.67',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    database: [
        {
            tag: 'path',
            d: 'M2.67 3.33a5.33 2 0 1 0 10.67 0a5.33 2 0 1 0-10.67 0M2.67 3.33v9.33c0 2.67 10.67 2.67 10.67 0V3.33M2.67 8c0 2.67 10.67 2.67 10.67 0',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    cloud: [
        {
            tag: 'path',
            d: 'M4.67 12.67a3 3 0 0 1-0.27-5.99A3.67 3.67 0 0 1 11.73 6.33 2.67 2.67 0 0 1 11.33 12.67Z',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    flask: [
        {
            tag: 'path',
            d: 'M6 2h4m-3.33 0v4.67L2.67 13.33h10.67l-4-6.67V2M5.33 9.33h5.33',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    chart: [
        {
            tag: 'path',
            d: 'M2 14h12.67M3.33 13.33V8.67h1.33v4.67m2.67 0V4.67h1.33v8.67m2.67 0V1.33h1.33v12',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    users: [
        {
            tag: 'circle',
            cx: '6',
            cy: '5.33',
            r: '2.27',
            stroke: 'currentColor',
            'stroke-width': '1.5',
        },
        {
            tag: 'path',
            d: 'M1.67 13.33c0-2.67 2-4 4.33-4s4.33 1.33 4.33 4M10.67 3.47a2.27 2.27 0 0 1 0 4.4M11.33 9.6c1.73 0.4 3 1.67 3 3.73',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    'do-not-disturb': [
        {
            tag: 'path',
            d: 'M8 1.5A6.5 6.5 0 1 0 8 14.5A6.5 6.5 0 1 0 8 1.5ZM4.5 8H11.5',
            stroke: 'currentColor',
            'stroke-width': '1.8',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    'sleeping-agent': [
        {
            tag: 'path',
            d: 'M4 6h5a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2zM4 9.8q1 .9 2 0M7 9.8q1 .9 2 0M11.5 1.8h3l-3 3.2h3',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    'archive-box': [
        {
            tag: 'path',
            d: 'M2 3h12v3H2zM3 6v7h10V6M6.5 9h3',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    'project-inactive': [
        {
            tag: 'path',
            d: 'M2 4.5h4l1.5 1.5H14V12H2z',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-dasharray': '2.5 1.5',
            'stroke-linejoin': 'round',
        },
    ],
    workflow: [
        { tag: 'circle', cx: '3', cy: '8', r: '1.7', stroke: 'currentColor', 'stroke-width': '1.5' },
        { tag: 'circle', cx: '13', cy: '3.5', r: '1.7', stroke: 'currentColor', 'stroke-width': '1.5' },
        { tag: 'circle', cx: '13', cy: '12.5', r: '1.7', stroke: 'currentColor', 'stroke-width': '1.5' },
        {
            tag: 'path',
            d: 'M4.7 8h2.6l2.3-3.6c.4-.6.8-.9 1.7-.9M7.3 8l2.3 3.6c.4.6.8.9 1.7.9',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    clock: [
        {
            tag: 'circle',
            cx: '8',
            cy: '8',
            r: '6',
            stroke: 'currentColor',
            'stroke-width': '1.5',
        },
        {
            tag: 'path',
            d: 'M8 4.67v3.33l2.33 1.33',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    alarm: [
        {
            tag: 'circle',
            cx: '8',
            cy: '9',
            r: '5.3',
            stroke: 'currentColor',
            'stroke-width': '1.5',
        },
        {
            tag: 'path',
            d: 'M8 6.4v2.9l1.9 1.1M2.4 3.4l2.2-1.5M13.6 3.4l-2.2-1.5',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    link: [
        {
            tag: 'path',
            d: 'm5.33 9.33 4-4m-2.67 5.33-1.33 1.33a2.67 2.67 0 0 1-4-4l2.67-2.67a2.67 2.67 0 0 1 4 0m0-1.33 1.33-1.33a2.67 2.67 0 0 1 4 4l-2.67 2.67a2.67 2.67 0 0 1-4 0',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
    crown: [
        {
            tag: 'path',
            d: 'M2.5 11.5 1.75 5 5 8l3-5.25L11 8l3.25-3-.75 6.5z',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linejoin': 'round',
        },
        {
            tag: 'path',
            d: 'M2.5 13.75h11',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
        },
    ],
    spark: [
        {
            tag: 'path',
            d: 'm8 1.33 1.67 5L14.67 8l-5 1.67L8 14.67l-1.67-5L1.33 8l5-1.67Z',
            stroke: 'currentColor',
            'stroke-width': '1.5',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
        },
    ],
};

export function isWisp(element) {
    return typeof element.class === 'string' && element.class.indexOf('kaw-steam') >= 0;
}

export function wispHostAttrs(px) {
    return 'class="kaw-cup" style="position:relative;display:block;width:' + px + 'px;height:' + px
        + 'px;--kaw-u:' + (px / GLYPH_SIZE) + '"';
}

function withoutClass(element) {
    const { class: _drop, ...rest } = element;
    return rest;
}

export function wispSvgAttrs(element) {
    return 'class="' + element.class + '" style="position:absolute;left:0;top:0"';
}

/* width="16" */
export function glyphSvg(name, size) {
    const elements = GLYPHS[name];
    if (!elements) return '';
    const px = (typeof size === 'number' && size > 0) ? size : GLYPH_SIZE;
    const open = '<svg width="' + px + '" height="' + px + '" viewBox="' + GLYPH_VIEWBOX + '" fill="none"';
    const draw = (list) => {
        let out = '';
        for (const element of list) {
            out += '<' + element.tag;
            for (const key of Object.keys(element)) {
                if (key === 'tag') continue;
                out += ' ' + key + '="' + element[key] + '"';
            }
            out += '/>';
        }
        return out;
    };
    const wisps = elements.filter(isWisp);
    if (!wisps.length) return open + '>' + draw(elements) + '</svg>';
    return '<span ' + wispHostAttrs(px) + '>' + open + '>' + draw(elements.filter((e) => !isWisp(e))) + '</svg>'
        + wisps.map((w) => open + ' ' + wispSvgAttrs(w) + '>' + draw([withoutClass(w)]) + '</svg>').join('')
        + '</span>';
}
