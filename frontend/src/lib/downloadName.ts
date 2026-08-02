// frontend/src/lib/downloadName.ts
// Builds human-readable, collision-free filenames for downloaded artifacts.
//
// Every artifact is written to disk as podcast.mp3 / video.mp4 inside its own
// job directory, so downloading several in a row used to produce video.mp4,
// video (1).mp4, video (2).mp4 with nothing to tell them apart. The generated
// title carries the prompt, so we lead with that and append the job id to keep
// distinct artifacts distinct while re-downloading the same one overwrites
// instead of piling up copies.

const MAX_SLUG_WORDS = 8;
const MAX_SLUG_LENGTH = 60;

const EXTENSION_BY_TYPE: Record<string, string> = {
  video: 'mp4',
  audio: 'mp3',
};

const FALLBACK_BASE_BY_TYPE: Record<string, string> = {
  video: 'upcurved-video',
  audio: 'upcurved-audio',
};

/** Lowercase ASCII slug. Returns '' for titles with no Latin characters. */
export function slugify(value: string): string {
  return (value || '')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .split('-')
    .filter(Boolean)
    .slice(0, MAX_SLUG_WORDS)
    .join('-')
    .slice(0, MAX_SLUG_LENGTH)
    .replace(/-+$/, '');
}

/** Extension from a URL path, ignoring query strings and signed-URL params. */
export function extensionFromUrl(url: string): string {
  const path = (url || '').split(/[?#]/)[0];
  const last = path.slice(path.lastIndexOf('/') + 1);
  const dot = last.lastIndexOf('.');
  if (dot > 0 && dot < last.length - 1) {
    const ext = last.slice(dot + 1).toLowerCase();
    if (/^[a-z0-9]{2,5}$/.test(ext)) return ext;
  }
  return '';
}

/** Job id from a /static/jobs/<id>/... URL, or '' when the shape differs. */
export function jobIdFromUrl(url: string): string {
  const match = (url || '').split(/[?#]/)[0].match(/\/jobs\/([A-Za-z0-9_-]+)\//);
  return match ? match[1] : '';
}

/** Stable short token for URLs with no job id (e.g. GCS object paths). */
function shortToken(value: string): string {
  let hash = 5381;
  for (let i = 0; i < value.length; i += 1) {
    hash = ((hash << 5) + hash + value.charCodeAt(i)) >>> 0;
  }
  return hash.toString(36).slice(0, 6);
}

export interface DownloadNameInput {
  title?: string;
  url: string;
  type: 'video' | 'audio';
  /** Preferred uniqueness token (artifact id). Falls back to the job id in the URL. */
  suffix?: string;
}

export function buildDownloadFilename({ title, url, type, suffix }: DownloadNameInput): string {
  const extension = extensionFromUrl(url) || EXTENSION_BY_TYPE[type] || 'bin';
  const base = slugify(title || '') || FALLBACK_BASE_BY_TYPE[type] || 'upcurved-artifact';
  const token = slugify(suffix || '') || jobIdFromUrl(url) || (url ? shortToken(url) : '');
  return token ? `${base}-${token}.${extension}` : `${base}.${extension}`;
}
