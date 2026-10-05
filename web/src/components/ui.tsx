import { AlertCircle, Check, Inbox, RefreshCw, X } from "lucide-react";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { formatAmountInput, parseAmount } from "../lib/format";
import { haptic } from "../telegram";

// --- states -----------------------------------------------------------------

export function Loading({ rows = 3, height = 72 }: { rows?: number; height?: number }) {
  return (
    <div className="stack" aria-busy="true" aria-label="Загрузка">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ height }} />
      ))}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "Не удалось загрузить данные.";
  return (
    <div className="state" role="alert">
      <div className="icon">
        <AlertCircle size={22} />
      </div>
      <div>{message}</div>
      {onRetry && (
        <button className="btn small" onClick={onRetry}>
          <RefreshCw size={14} /> Повторить
        </button>
      )}
    </div>
  );
}

export function Empty({ title, hint, icon }: { title: string; hint?: string; icon?: ReactNode }) {
  return (
    <div className="state">
      <div className="icon">{icon ?? <Inbox size={22} />}</div>
      <div>{title}</div>
      {hint && <div className="small faint">{hint}</div>}
    </div>
  );
}

// --- sheet (bottom sheet on phones, dialog on desktop) ------------------------

export function Sheet({
  title,
  onClose,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label={title}>
        <div className="sheet-head">
          <h2>{title}</h2>
          <button className="btn icon-only ghost small" onClick={onClose} aria-label="Закрыть">
            <X size={16} />
          </button>
        </div>
        {children}
        {footer && <div className="actions">{footer}</div>}
      </div>
    </div>
  );
}

// --- toasts -------------------------------------------------------------------

interface Toast {
  id: number;
  text: string;
  kind: "ok" | "error";
}

const ToastContext = createContext<(text: string, kind?: "ok" | "error") => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: "ok" | "error" = "ok") => {
    const id = Date.now() + Math.random();
    haptic(kind === "ok" ? "success" : "error");
    setToasts((list) => [...list, { id, text, kind }]);
    window.setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), 4200);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toast-stack" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind === "error" ? "error" : ""}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Что-то пошло не так.";
}

// --- confirm ------------------------------------------------------------------

export function Confirm({
  title,
  children,
  confirmLabel,
  danger,
  busy,
  onConfirm,
  onClose,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Sheet
      title={title}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button className={`btn ${danger ? "danger" : "primary"}`} onClick={onConfirm} disabled={busy}>
            {busy ? "Подождите…" : confirmLabel}
          </button>
        </>
      }
    >
      {children}
    </Sheet>
  );
}

// --- inputs -------------------------------------------------------------------

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <div className="hint">{hint}</div>}
    </label>
  );
}

/** Money input that shows thousands separators and reports a number (or null). */
export function MoneyInput({
  value,
  onChange,
  allowNegative,
  placeholder,
  autoFocus,
}: {
  value: number | null;
  onChange: (value: number | null) => void;
  allowNegative?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState(value === null ? "" : formatAmountInput(String(value), allowNegative));
  useEffect(() => {
    if (parseAmount(text) !== value) setText(value === null ? "" : formatAmountInput(String(value), allowNegative));
  }, [value]);
  return (
    <input
      className="input num"
      inputMode={allowNegative ? "text" : "numeric"}
      placeholder={placeholder ?? "₩"}
      value={text}
      autoFocus={autoFocus}
      onChange={(e) => {
        const next = formatAmountInput(e.target.value, allowNegative);
        setText(next);
        onChange(parseAmount(next));
      }}
    />
  );
}

export function Checkbox({ checked, onChange, label }: { checked: boolean; onChange: () => void; label: string }) {
  return (
    <button
      type="button"
      className={`checkbox ${checked ? "on" : ""}`}
      aria-pressed={checked}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation();
        haptic("select");
        onChange();
      }}
    >
      {checked && <Check size={14} strokeWidth={3} />}
    </button>
  );
}

export function Switch({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <div
      className={`switch ${checked ? "on" : ""}`}
      role="switch"
      aria-checked={checked}
      tabIndex={0}
      onClick={() => onChange(!checked)}
      onKeyDown={(e) => (e.key === " " || e.key === "Enter") && onChange(!checked)}
    >
      <div>
        <div>{label}</div>
        {hint && <div className="small faint">{hint}</div>}
      </div>
      <div className="track" />
    </div>
  );
}

export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

const LONG_PRESS_MS = 500;
const MOVE_TOLERANCE_PX = 10;

/**
 * Tap vs. press-and-hold on the same element (like selecting in a phone's
 * gallery). Moving the finger (scrolling) cancels the hold; the click that
 * follows a hold is swallowed, so a hold never also opens the item.
 */
export function useLongPress(onLongPress: () => void, onTap: () => void) {
  const timer = useRef<number | null>(null);
  const start = useRef<{ x: number; y: number } | null>(null);
  const fired = useRef(false);
  const cancel = () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
    start.current = null;
  };
  return {
    onPointerDown: (e: React.PointerEvent) => {
      if (e.button !== 0) return;
      fired.current = false;
      start.current = { x: e.clientX, y: e.clientY };
      timer.current = window.setTimeout(() => {
        fired.current = true;
        timer.current = null;
        haptic("select");
        onLongPress();
      }, LONG_PRESS_MS);
    },
    onPointerMove: (e: React.PointerEvent) => {
      if (!start.current) return;
      if (Math.hypot(e.clientX - start.current.x, e.clientY - start.current.y) > MOVE_TOLERANCE_PX) cancel();
    },
    onPointerUp: cancel,
    onPointerCancel: cancel,
    onPointerLeave: cancel,
    // Long-press on a phone would otherwise open the image / text menu.
    onContextMenu: (e: React.MouseEvent) => e.preventDefault(),
    onClick: () => {
      if (fired.current) {
        fired.current = false;
        return;
      }
      onTap();
    },
  };
}

export function useSelection() {
  const [selected, setSelected] = useState<string[]>([]);
  return useMemo(
    () => ({
      selected,
      has: (id: string) => selected.includes(id),
      toggle: (id: string) =>
        setSelected((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id])),
      set: setSelected,
      clear: () => setSelected([]),
    }),
    [selected],
  );
}
