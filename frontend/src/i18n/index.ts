import type { EventInfo } from "../protocol/types";
import { type Dict, en } from "./en";
import { ru } from "./ru";

export type { Dict } from "./en";
export type Lang = "en" | "ru";

export const DICTS: Record<Lang, Dict> = { en, ru };
export const LANGS: readonly Lang[] = ["en", "ru"];

const STORAGE_KEY = "eos.lang";

/** The saved choice, else the browser's language, else English. */
export function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "ru") return saved;
  } catch {
    // storage blocked: fall back to the browser's language
  }
  return typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru") ? "ru" : "en";
}

export function rememberLang(lang: Lang): void {
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // storage blocked: the choice lasts until the page reloads
  }
  document.documentElement.lang = lang;
}

/** An event in the viewer's language; the server's English line when there is no phrase. */
export function eventText(event: EventInfo, t: Dict): string {
  const phrase = t.events.phrases[event.code];
  return phrase ? phrase(event.params) : event.text;
}
