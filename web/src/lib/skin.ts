/** The look («Оформление» in «Настройки»), chosen by each person for
 * themselves and remembered on their phone only. */

export type Skin = "standard" | "minimal" | "sport";

export const SKINS: { id: Skin; label: string; swatch: string[] }[] = [
  { id: "standard", label: "Обычная", swatch: ["#f4f3ef", "#263140", "#ffffff"] },
  { id: "minimal", label: "Минимал", swatch: ["#ffffff", "#0a0a0a", "#ffffff"] },
  { id: "sport", label: "Спорт", swatch: ["#ececec", "#111111", "#d7ff3a"] },
];

const KEY = "crm-skin";

export function savedSkin(): Skin {
  try {
    const value = localStorage.getItem(KEY);
    if (value === "minimal" || value === "sport") return value;
  } catch {
    /* storage unavailable */
  }
  return "standard";
}

export function applySkin(skin: Skin | null): void {
  if (skin && skin !== "standard") document.documentElement.dataset.skin = skin;
  else delete document.documentElement.dataset.skin;
}

export function saveSkin(skin: Skin): void {
  try {
    localStorage.setItem(KEY, skin);
  } catch {
    /* storage unavailable */
  }
  applySkin(skin);
}

/** Light / dark: follow Telegram (default) or fixed. Remembered on this phone. */
export type ThemeMode = "auto" | "light" | "dark";

const MODE_KEY = "crm-theme-mode";
export const THEME_EVENT = "crm-theme-mode";

export function savedThemeMode(): ThemeMode {
  try {
    const value = localStorage.getItem(MODE_KEY);
    if (value === "light" || value === "dark") return value;
  } catch {
    /* storage unavailable */
  }
  return "auto";
}

export function saveThemeMode(mode: ThemeMode): void {
  try {
    localStorage.setItem(MODE_KEY, mode);
  } catch {
    /* storage unavailable */
  }
  window.dispatchEvent(new Event(THEME_EVENT));
}

/** Animations on / off (on by default). Remembered on this phone. */
const MOTION_KEY = "crm-motion";

export function savedMotion(): boolean {
  try {
    return localStorage.getItem(MOTION_KEY) !== "off";
  } catch {
    return true;
  }
}

export function applyMotion(on: boolean): void {
  if (on) delete document.documentElement.dataset.motion;
  else document.documentElement.dataset.motion = "off";
}

export function saveMotion(on: boolean): void {
  try {
    localStorage.setItem(MOTION_KEY, on ? "on" : "off");
  } catch {
    /* storage unavailable */
  }
  applyMotion(on);
}

/** Whether to animate now: the setting, and the phone's «reduce motion». */
export function motionAllowed(): boolean {
  if (document.documentElement.dataset.motion === "off") return false;
  return !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}
