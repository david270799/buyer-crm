import { useState } from "react";

import {
  saveMotion,
  savedMotion,
  saveSkin,
  savedSkin,
  savedThemeMode,
  saveThemeMode,
  type Skin,
  SKINS,
  type ThemeMode,
} from "../lib/skin";

/** «Оформление»: light/dark and the look. Each person picks for themselves —
 * stored on their phone only (localStorage), never synced. */
export function AppearanceSettings() {
  const [skin, setSkin] = useState<Skin>(savedSkin());
  const [mode, setMode] = useState<ThemeMode>(savedThemeMode());
  const [motion, setMotion] = useState(savedMotion());
  const modes: [ThemeMode, string][] = [
    ["auto", "Как в Telegram"],
    ["light", "Светлая"],
    ["dark", "Тёмная"],
  ];
  return (
    <div className="card pad stack">
      <h3>Оформление</h3>
      <div className="chips">
        {modes.map(([value, label]) => (
          <button
            key={value}
            className={`chip ${mode === value ? "active" : ""}`}
            onClick={() => {
              saveThemeMode(value);
              setMode(value);
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="skin-grid">
        {SKINS.map((s) => (
          <button
            key={s.id}
            type="button"
            className={`skin-option ${skin === s.id ? "active" : ""}`}
            onClick={() => {
              saveSkin(s.id);
              setSkin(s.id);
            }}
          >
            <span className="skin-swatch">
              {s.swatch.map((c, i) => (
                <i key={i} style={{ background: c }} />
              ))}
            </span>
            <b>{s.label}</b>
          </button>
        ))}
      </div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <b className="small">Анимации</b>
        <div className="chips">
          {([true, false] as const).map((on) => (
            <button
              key={String(on)}
              className={`chip ${motion === on ? "active" : ""}`}
              onClick={() => {
                saveMotion(on);
                setMotion(on);
              }}
            >
              {on ? "Вкл" : "Выкл"}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

