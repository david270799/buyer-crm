import { Delete, Lock } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { ApiError, post, put } from "../api/client";
import { useSecurity } from "../api/hooks";
import { errorText, Sheet, useToast } from "../components/ui";
import { haptic } from "../telegram";

// Remembered while this Mini App stays open (Telegram drops it on close).
const UNLOCKED = "crm-unlocked";

function readUnlocked(): boolean {
  try {
    return sessionStorage.getItem(UNLOCKED) === "1";
  } catch {
    return false;
  }
}

function writeUnlocked(): void {
  try {
    sessionStorage.setItem(UNLOCKED, "1");
  } catch {
    /* private mode: the PIN is asked again next time */
  }
}

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "⌫"];

/** Round phone-style keypad with dots; no system keyboard. Calls `onComplete`
 * as soon as `length` digits are typed. */
function Keypad({
  length,
  onComplete,
  busy,
  error,
}: {
  length: number;
  onComplete: (pin: string) => Promise<boolean> | boolean;
  busy?: boolean;
  error?: string | null;
}) {
  const [digits, setDigits] = useState("");
  const [shake, setShake] = useState(false);
  const press = (key: string) => {
    if (busy) return;
    if (key === "⌫") {
      setDigits((d) => d.slice(0, -1));
      return;
    }
    if (!key || digits.length >= length) return;
    haptic("select");
    const next = digits + key;
    setDigits(next);
    if (next.length === length) {
      Promise.resolve(onComplete(next)).then((ok) => {
        if (!ok) {
          haptic("error");
          setShake(true);
          window.setTimeout(() => {
            setShake(false);
            setDigits("");
          }, 450);
        }
      });
    }
  };
  useEffect(() => {
    // A hardware keyboard works too (desktop panel).
    const onKey = (e: KeyboardEvent) => {
      if (/^\d$/.test(e.key)) press(e.key);
      else if (e.key === "Backspace") press("⌫");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  return (
    <div className="pin">
      <div className={`pin-dots ${shake ? "shake" : ""}`} aria-label={`Введено ${digits.length} из ${length}`}>
        {Array.from({ length }, (_, i) => (
          <span key={i} className={i < digits.length ? "on" : ""} />
        ))}
      </div>
      <div className="pin-error">{error ?? ""}</div>
      <div className="pin-pad">
        {KEYS.map((key, i) =>
          key ? (
            <button
              key={i}
              type="button"
              className={`pin-key ${key === "⌫" ? "erase" : ""}`}
              onClick={() => press(key)}
              aria-label={key === "⌫" ? "Стереть" : key}
            >
              {key === "⌫" ? <Delete size={22} /> : key}
            </button>
          ) : (
            <span key={i} />
          ),
        )}
      </div>
    </div>
  );
}

/** Shown before the admin app when a PIN is set. */
export function PinGate({ children }: { children: ReactNode }) {
  const security = useSecurity();
  const [unlocked, setUnlocked] = useState(readUnlocked);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const length = security.data?.pin_length ?? 0;
  const open = unlocked || (!security.isLoading && (!length || !!security.error));
  useEffect(() => {
    // Opened without a PIN: this session stays open when a PIN is set later on.
    if (open && !unlocked) {
      writeUnlocked();
      setUnlocked(true);
    }
  }, [open, unlocked]);
  if (open) return <>{children}</>;
  if (security.isLoading) return null;
  return (
    <div className="lock-screen">
      <Lock size={26} />
      <h2>Введите PIN</h2>
      <Keypad
        length={length}
        busy={busy}
        error={error}
        onComplete={async (pin) => {
          setBusy(true);
          try {
            await post("/api/security/unlock", { pin });
            writeUnlocked();
            setUnlocked(true);
            return true;
          } catch (e) {
            setError(e instanceof ApiError && e.status === 422 ? "Неверный PIN" : errorText(e));
            return false;
          } finally {
            setBusy(false);
          }
        }}
      />
    </div>
  );
}

/** Settings → "PIN-код": set (typed twice) or turn off. */
export function PinSettings() {
  const toast = useToast();
  const security = useSecurity();
  const [setting, setSetting] = useState(false);
  const isSet = (security.data?.pin_length ?? 0) > 0;
  const save = async (pin: string | null) => {
    try {
      if (pin) writeUnlocked();
      await put("/api/security/pin", { pin });
      await security.refetch();
      toast(pin ? "PIN-код установлен" : "PIN-код выключен");
    } catch (e) {
      toast(errorText(e), "error");
    }
  };
  return (
    <div className="card pad stack">
      <h3>PIN-код</h3>
      <div className="small muted">
        {isSet
          ? "Включён: при открытии CRM нужно ввести код. Клиент его не видит. Забыли — напишите боту /pin off."
          : "Не задан. С кодом CRM не откроет тот, у кого окажется ваш телефон."}
      </div>
      <div className="row" style={{ gap: 8 }}>
        <button className="btn primary" onClick={() => setSetting(true)}>
          {isSet ? "Сменить PIN" : "Задать PIN"}
        </button>
        {isSet && (
          <button className="btn ghost" onClick={() => save(null)}>
            Выключить
          </button>
        )}
      </div>
      {setting && <NewPinSheet onClose={() => setSetting(false)} onDone={(pin) => save(pin).then(() => setSetting(false))} />}
    </div>
  );
}

const NEW_PIN_LENGTH = 4;

function NewPinSheet({ onClose, onDone }: { onClose: () => void; onDone: (pin: string) => void }) {
  const [first, setFirst] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <Sheet title={first ? "Повторите PIN" : "Новый PIN (4 цифры)"} onClose={onClose}>
      <Keypad
        key={first ? "repeat" : "first"}
        length={NEW_PIN_LENGTH}
        error={error}
        onComplete={(pin) => {
          if (!first) {
            setFirst(pin);
            setError(null);
            return true;
          }
          if (pin !== first) {
            setError("Не совпало — введите заново");
            setFirst(null);
            return false;
          }
          onDone(pin);
          return true;
        }}
      />
    </Sheet>
  );
}
