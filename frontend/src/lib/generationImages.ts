import type { Translate } from "@/lib/i18n";

export const MAX_GENERATION_IMAGES = 3;
export const MAX_GENERATION_IMAGE_BYTES = 5 * 1024 * 1024;
export const MAX_GENERATION_IMAGE_DIMENSION = 2000;
const MAX_PREPARED_IMAGE_BYTES = 4 * 1024 * 1024;

export const SUPPORTED_GENERATION_IMAGE_TYPES = [
  "image/png",
  "image/jpeg",
  "image/webp",
] as const;

export type GenerationImageMimeType =
  (typeof SUPPORTED_GENERATION_IMAGE_TYPES)[number];

export type GenerationImagePayload = {
  dataUrl: string;
  mimeType: GenerationImageMimeType;
  name?: string;
};

export type GenerationImageValidation = {
  accepted: File[];
  rejected: { file: File; reason: string }[];
  limitReached: boolean;
};

const SUPPORTED_TYPE_SET = new Set<string>(SUPPORTED_GENERATION_IMAGE_TYPES);

export function isSupportedGenerationImage(file: File): boolean {
  return SUPPORTED_TYPE_SET.has(String(file.type || "").toLowerCase());
}

export function validateGenerationImageFiles(
  existing: readonly File[],
  incoming: readonly File[],
  t: Translate,
): GenerationImageValidation {
  const rejected: { file: File; reason: string }[] = [];
  const accepted: File[] = [];
  let slots = Math.max(0, MAX_GENERATION_IMAGES - existing.length);
  let limitReached = false;

  for (const file of incoming) {
    if (!isSupportedGenerationImage(file)) {
      rejected.push({
        file,
        reason: t("image.unsupportedType"),
      });
      continue;
    }
    if (file.size <= 0) {
      rejected.push({ file, reason: t("image.empty") });
      continue;
    }
    if (file.size > MAX_GENERATION_IMAGE_BYTES) {
      rejected.push({
        file,
        reason: t("image.tooLarge"),
      });
      continue;
    }
    if (slots <= 0) {
      limitReached = true;
      continue;
    }
    accepted.push(file);
    slots -= 1;
  }

  if (incoming.length > accepted.length + rejected.length) {
    limitReached = true;
  }

  return { accepted, rejected, limitReached };
}

function fileToDataUrl(file: Blob, t: Translate): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || t ? new Error(t("image.readFailed")) : new Error("Could not read image."));
    reader.onload = () => {
      if (typeof reader.result !== "string") {
        reject(new Error(t("image.encodeFailed")));
        return;
      }
      resolve(reader.result);
    };
    reader.readAsDataURL(file);
  });
}

async function decodeImage(file: File, t: Translate): Promise<{
  width: number;
  height: number;
  draw: (ctx: CanvasRenderingContext2D, width: number, height: number) => void;
  close: () => void;
}> {
  if (typeof createImageBitmap === "function") {
    const bitmap = await createImageBitmap(file);
    return {
      width: bitmap.width,
      height: bitmap.height,
      draw: (ctx, width, height) => ctx.drawImage(bitmap, 0, 0, width, height),
      close: () => bitmap.close(),
    };
  }

  const objectUrl = URL.createObjectURL(file);
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error(t("image.decodeFailed")));
      img.src = objectUrl;
    });
    return {
      width: image.naturalWidth || image.width,
      height: image.naturalHeight || image.height,
      draw: (ctx, width, height) => ctx.drawImage(image, 0, 0, width, height),
      close: () => URL.revokeObjectURL(objectUrl),
    };
  } catch (error) {
    URL.revokeObjectURL(objectUrl);
    throw error;
  }
}

function canvasToBlob(
  t: Translate,
  canvas: HTMLCanvasElement,
  mimeType: GenerationImageMimeType,
  quality?: number,
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          reject(new Error(t("image.compressFailed")));
          return;
        }
        resolve(blob);
      },
      mimeType,
      quality,
    );
  });
}

async function prepareOneImage(file: File, t: Translate): Promise<GenerationImagePayload> {
  const originalMime = String(file.type || "").toLowerCase() as GenerationImageMimeType;
  if (!SUPPORTED_TYPE_SET.has(originalMime)) {
    throw new Error(`Unsupported image type: ${file.type || "unknown"}`);
  }

  const decoded = await decodeImage(file, t);
  try {
    const maxSide = Math.max(decoded.width, decoded.height);
    const needsResize = maxSide > MAX_GENERATION_IMAGE_DIMENSION;
    // Keeping smaller screenshots lossless is useful for equations and small text.
    const canKeepOriginal = !needsResize && file.size <= 2.5 * 1024 * 1024;

    if (canKeepOriginal) {
      return {
        dataUrl: await fileToDataUrl(file, t),
        mimeType: originalMime,
        name: file.name || undefined,
      };
    }

    const scale = needsResize
      ? MAX_GENERATION_IMAGE_DIMENSION / maxSide
      : 1;
    const width = Math.max(1, Math.round(decoded.width * scale));
    const height = Math.max(1, Math.round(decoded.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error(t("image.canvasFailed"));
    decoded.draw(ctx, width, height);

    // Preserve PNG when practical for crisp screenshots. Larger non-PNG images use
    // high-quality WebP to keep request bodies comfortably below backend limits.
    const outputMime: GenerationImageMimeType =
      originalMime === "image/png" && file.size <= MAX_GENERATION_IMAGE_BYTES
        ? "image/png"
        : "image/webp";
    const blob = await canvasToBlob(
      t,
      canvas,
      outputMime,
      outputMime === "image/webp" ? 0.94 : undefined,
    );

    if (blob.size > MAX_PREPARED_IMAGE_BYTES) {
      // Keep prepared images at or below 4 MB so three attachments also stay within
      // the backend's 12 MB combined decoded-size limit.
      const fallback = await canvasToBlob(t, canvas, "image/webp", 0.9);
      if (fallback.size > MAX_PREPARED_IMAGE_BYTES) {
        throw new Error(t("image.stillTooLarge"));
      }
      return {
        dataUrl: await fileToDataUrl(fallback, t),
        mimeType: "image/webp",
        name: file.name || undefined,
      };
    }

    return {
      dataUrl: await fileToDataUrl(blob, t),
      mimeType: outputMime,
      name: file.name || undefined,
    };
  } finally {
    decoded.close();
  }
}

export async function prepareGenerationImages(
  files: readonly File[],
  t: Translate,
): Promise<GenerationImagePayload[]> {
  if (files.length > MAX_GENERATION_IMAGES) {
    throw new Error(`Up to ${MAX_GENERATION_IMAGES} images can be attached.`);
  }
  return Promise.all(files.map((file) => prepareOneImage(file, t)));
}
