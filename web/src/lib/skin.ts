/** The look («Оформление» in «Настройки»), chosen by each person for
 * themselves and remembered on their phone only. */

export type Skin = "standard" | "minimal" | "sport";

export const SKINS: { id: Skin; label: string; hint: string; swatch: string[] }[] = [
  { id: "standard", label: "Обычная", hint: "как раньше", swatch: ["#f4f3ef", "#263140", "#ffffff"] },
  { id: "minimal", label: "Минимал", hint: "белый и чёрный, крупные заголовки", swatch: ["#ffffff", "#0a0a0a", "#ffffff"] },
  { id: "sport", label: "Спорт", hint: "серый, чёрный и салатовый", swatch: ["#ececec", "#111111", "#d7ff3a"] },
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
