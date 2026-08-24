// Registers global keyboard shortcuts for the lifetime of a component.
//
// Deliberately narrow: one listener, platform-correct modifier, and typing
// targets are skipped unless a binding opts in. Anything more elaborate belongs
// in a real shortcut library, not here.
import { useEffect, useRef } from "react";

import { hasPlatformModifier, isTypingTarget } from "@/lib/hotkeys";

export type Hotkey = {
  /** Matched case-insensitively against `event.key`, e.g. "k", "/", "Enter". */
  key: string;
  /** Require Cmd on macOS / Ctrl elsewhere. Defaults to true. */
  withModifier?: boolean;
  /** Also fire while the user is typing in a field. Defaults to false. */
  allowWhileTyping?: boolean;
  handler: () => void;
};

export function useHotkeys(hotkeys: Hotkey[], enabled = true) {
  // Held in a ref so a new array identity each render does not re-subscribe, and
  // so handlers always see current state without listing them as dependencies.
  const latest = useRef(hotkeys);
  latest.current = hotkeys;

  useEffect(() => {
    if (!enabled) return;

    const onKeyDown = (event: KeyboardEvent) => {
      // Let the browser's own composition and IME handling win. Without this,
      // a shortcut can fire mid-composition when typing Japanese or Chinese.
      if (event.isComposing) return;

      for (const hotkey of latest.current) {
        const needsModifier = hotkey.withModifier !== false;
        if (needsModifier && !hasPlatformModifier(event)) continue;
        // A bare-key binding must not swallow the modified form.
        if (!needsModifier && (event.metaKey || event.ctrlKey || event.altKey)) continue;
        if (event.key.toLowerCase() !== hotkey.key.toLowerCase()) continue;
        if (!hotkey.allowWhileTyping && isTypingTarget(event.target)) continue;

        event.preventDefault();
        hotkey.handler();
        return;
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled]);
}
