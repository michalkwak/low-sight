import { useEffect, useRef } from "react";
import type { Alert } from "./types";

/** The phone is the main audio path (its speech plays through the glasses speakers).
 * The HUD only speaks an alert that no phone reported speaking within this window. */
export const PHONE_GRACE_MS = 2500;

/** speechSynthesis is supported on Meta Ray-Ban Display web apps (one en-US voice).
 * Pre-generated clips in audio/ are only a fallback for browsers without it. */
export function speakHere(alert: Alert): void {
  if (!alert.speak) return;
  if ("speechSynthesis" in window && "SpeechSynthesisUtterance" in window) {
    window.speechSynthesis.cancel(); // a newer alert replaces anything still being said
    const u = new SpeechSynthesisUtterance(alert.speak);
    u.lang = "en-US";
    window.speechSynthesis.speak(u);
    return;
  }
  new Audio(`${import.meta.env.BASE_URL}audio/${alert.level.toLowerCase()}.mp3`).play().catch(() => {});
}

/** Speak each new alert id once, unless it is silent (already said this episode) or a
 * phone/stage audio reported speaking it before the grace period ran out. */
export function useAlertAudio(alert: Alert | undefined, speak: (a: Alert) => void = speakHere): void {
  const latest = useRef(alert);
  latest.current = alert;
  const id = alert && alert.level !== "NONE" ? alert.id : "";

  useEffect(() => {
    const a = latest.current;
    if (!id || !a || !a.speak || a.spoken) return;
    const timer = setTimeout(() => {
      const cur = latest.current;
      if (cur && cur.id === id && cur.speak && !cur.spoken) speak(cur);
    }, PHONE_GRACE_MS);
    return () => clearTimeout(timer); // a newer alert supersedes this one
  }, [id, speak]);
}
