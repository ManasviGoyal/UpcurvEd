import type { Message } from "@/types";

const LEGACY_MATCH_WINDOW_MS = 30_000;
let lastIdentityMs = 0;
let identityCounter = 0;

const finiteNumber = (value: unknown): number | undefined => {
  const number = Number(value);
  return Number.isFinite(number) ? number : undefined;
};

export const messageDisplayTimestamp = (message: Message): number =>
  finiteNumber(message.clientCreatedAt)
  ?? finiteNumber(message.createdAt)
  ?? 0;

const messageSequence = (message: Message): number =>
  finiteNumber(message.sequence) ?? 0;

const messageId = (message: Message): string =>
  String(message.messageId || "");

export const compareMessages = (left: Message, right: Message): number => {
  const timeDiff = messageDisplayTimestamp(left) - messageDisplayTimestamp(right);
  if (timeDiff !== 0) return timeDiff;

  const sequenceDiff = messageSequence(left) - messageSequence(right);
  if (sequenceDiff !== 0) return sequenceDiff;

  return messageId(left).localeCompare(messageId(right));
};

export const createMessageIdentity = (now = Date.now()) => {
  const safeNow = Math.max(0, Math.floor(now));
  if (safeNow === lastIdentityMs) {
    identityCounter = (identityCounter + 1) % 1000;
  } else {
    lastIdentityMs = safeNow;
    identityCounter = 0;
  }

  const sequence = safeNow * 1000 + identityCounter;
  const randomPart =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2, 14);

  return {
    messageId: `m_${sequence}_${randomPart}`,
    createdAt: safeNow,
    clientCreatedAt: safeNow,
    sequence,
  };
};

const normalizedContent = (message: Message): string =>
  String(message.content || "").trim().toLowerCase().replace(/\s+/g, " ");

const legacySignature = (message: Message): string => {
  const artifact = message.media?.artifactId || message.media?.url || "";
  const quiz = (message as Message & { quizAnchor?: boolean; quizTitle?: string }).quizAnchor
    ? (message as Message & { quizTitle?: string }).quizTitle || "untitled"
    : "";
  return `${message.role}|${normalizedContent(message)}|${artifact}|${quiz}`;
};

const isLegacyLocalId = (value: string): boolean => value.startsWith("local-");

const mergeMessageRecord = (existing: Message, incoming: Message): Message => ({
  ...existing,
  ...incoming,
  media: incoming.media ?? existing.media,
  quizAnchor: incoming.quizAnchor ?? existing.quizAnchor,
  quizTitle: incoming.quizTitle ?? existing.quizTitle,
  quizData: incoming.quizData ?? existing.quizData,
  createdAt: finiteNumber(incoming.createdAt) ?? finiteNumber(existing.createdAt),
  clientCreatedAt:
    finiteNumber(existing.clientCreatedAt)
    ?? finiteNumber(incoming.clientCreatedAt)
    ?? finiteNumber(existing.createdAt)
    ?? finiteNumber(incoming.createdAt),
  sequence: finiteNumber(existing.sequence) ?? finiteNumber(incoming.sequence),
  messageId: incoming.messageId || existing.messageId,
});

const legacyLocalMatch = (
  incoming: Message,
  messagesById: Map<string, Message>,
): string | undefined => {
  const incomingId = messageId(incoming);
  if (!incomingId || isLegacyLocalId(incomingId)) return undefined;

  const signature = legacySignature(incoming);
  const incomingTime = messageDisplayTimestamp(incoming);
  for (const [candidateId, candidate] of messagesById.entries()) {
    if (!isLegacyLocalId(candidateId)) continue;
    if (legacySignature(candidate) !== signature) continue;
    const candidateTime = messageDisplayTimestamp(candidate);
    if (
      incomingTime > 0
      && candidateTime > 0
      && Math.abs(incomingTime - candidateTime) > LEGACY_MATCH_WINDOW_MS
    ) {
      continue;
    }
    return candidateId;
  }
  return undefined;
};

/**
 * Merge message snapshots using permanent message IDs as the primary identity.
 * Content matching is restricted to one legacy local/server migration case so
 * repeated identical prompts and status messages remain distinct.
 */
export const mergeMessages = (
  existingMessages: readonly Message[] = [],
  incomingMessages: readonly Message[] = [],
): Message[] => {
  const messagesById = new Map<string, Message>();
  const anonymous: Message[] = [];

  for (const message of existingMessages) {
    const id = messageId(message);
    if (id) {
      messagesById.set(id, message);
    } else {
      anonymous.push(message);
    }
  }

  for (const incoming of incomingMessages) {
    const id = messageId(incoming);
    if (!id) {
      anonymous.push(incoming);
      continue;
    }

    const exact = messagesById.get(id);
    if (exact) {
      messagesById.set(id, mergeMessageRecord(exact, incoming));
      continue;
    }

    const legacyId = legacyLocalMatch(incoming, messagesById);
    if (legacyId) {
      const legacy = messagesById.get(legacyId)!;
      messagesById.delete(legacyId);
      messagesById.set(id, mergeMessageRecord(legacy, incoming));
      continue;
    }

    messagesById.set(id, incoming);
  }

  return [...messagesById.values(), ...anonymous].sort(compareMessages);
};
