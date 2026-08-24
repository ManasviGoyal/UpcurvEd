// Keyboard shortcuts, on both macOS and Windows/Linux.
//
// Two things this file exists to get right:
//   1. The modifier differs by platform — Cmd on a Mac, Ctrl everywhere else —
//      and so does how it must be *displayed*. Showing "⌘K" to a Windows user is
//      a common and confusing bug, so the label comes from the same source as the
//      binding rather than being written out by hand at each call site.
//   2. A global handler must not fire while someone is typing. Without that
//      guard, a shortcut silently eats keystrokes inside the prompt box.

/**
 * True on macOS, where the platform modifier is Cmd rather than Ctrl.
 *
 * In the packaged desktop builds this is exact: the preload bridge hands over
 * Electron's own `process.platform`, so the macOS DMG, the Windows installer and
 * the Linux AppImage each report themselves correctly with no guessing. The user
 * agent is only consulted in the browser, where nothing better exists.
 */
export function isMacPlatform(): boolean {
  if (typeof window !== "undefined") {
    const platform = window.desktop?.platform;
    if (platform) return platform === "darwin";
  }

  if (typeof navigator === "undefined") return false;

  const uaData = (navigator as Navigator & { userAgentData?: { platform?: string } })
    .userAgentData;
  const agent = `${uaData?.platform || ""} ${navigator.platform || ""} ${
    navigator.userAgent || ""
  }`.toLowerCase();

  // iPadOS reports as a Mac and also uses Cmd on an attached keyboard.
  return agent.includes("mac") || agent.includes("iphone") || agent.includes("ipad");
}

/** How to render the platform modifier: "⌘" on macOS, "Ctrl" elsewhere. */
export function modifierLabel(): string {
  return isMacPlatform() ? "⌘" : "Ctrl";
}

/**
 * A shortcut as text for the UI, e.g. "⌘K" or "Ctrl+K".
 * macOS convention omits the separator; Windows and Linux use a plus.
 */
export function shortcutLabel(key: string): string {
  return isMacPlatform() ? `⌘${key}` : `Ctrl+${key}`;
}

/** Whether the platform modifier is held: Cmd on macOS, Ctrl elsewhere. */
export function hasPlatformModifier(event: KeyboardEvent | React.KeyboardEvent): boolean {
  return isMacPlatform() ? event.metaKey : event.ctrlKey;
}

/**
 * Whether the event came from somewhere the user is typing.
 *
 * Global shortcuts must ignore these, otherwise they steal keystrokes from the
 * prompt box. Callers that deliberately want a shortcut to work *while* typing
 * (⌘Enter to send, say) bind it on the field itself instead of globally.
 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;

  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}
