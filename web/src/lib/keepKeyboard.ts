/**
 * The owner switches to another app (e.g. to look up a price) while typing in
 * the Mini App; on return the keyboard used to stay closed. Here the field that
 * had focus when the app went to the background gets focus back on return, so
 * the keyboard opens again (where the phone allows it — some WebViews only
 * open the keyboard after a tap).
 */

type Editable = HTMLInputElement | HTMLTextAreaElement;

const TEXT_TYPES = new Set(["text", "search", "tel", "number", "email", "url", "password", ""]);

function editable(el: Element | null): el is Editable {
  if (el instanceof HTMLTextAreaElement) return !el.readOnly && !el.disabled;
  if (el instanceof HTMLInputElement) return TEXT_TYPES.has(el.type) && !el.readOnly && !el.disabled;
  return false;
}

export function keepKeyboardOnReturn(): () => void {
  let last: Editable | null = null;
  let lostAt = 0;
  let pending: Editable | null = null;

  const onFocusIn = (e: FocusEvent) => {
    if (editable(e.target as Element)) last = e.target as Editable;
  };
  const onFocusOut = (e: FocusEvent) => {
    if (e.target === last) lostAt = Date.now();
  };
  const leave = () => {
    // The field may already have lost focus a moment before the app was hidden.
    const active = document.activeElement;
    if (editable(active)) pending = active;
    else if (last && Date.now() - lostAt < 1500) pending = last;
  };
  const back = () => {
    const field = pending;
    pending = null;
    if (!field || !field.isConnected || document.activeElement === field) return;
    window.setTimeout(() => {
      if (!field.isConnected) return;
      field.focus({ preventScroll: true });
      if (field.type !== "number") {
        const end = field.value.length;
        try {
          field.setSelectionRange(end, end);
        } catch {
          /* some input types do not support a caret */
        }
      }
    }, 200);
  };
  const onVisibility = () => (document.visibilityState === "hidden" ? leave() : back());

  document.addEventListener("focusin", onFocusIn);
  document.addEventListener("focusout", onFocusOut);
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("blur", leave);
  window.addEventListener("focus", back);
  return () => {
    document.removeEventListener("focusin", onFocusIn);
    document.removeEventListener("focusout", onFocusOut);
    document.removeEventListener("visibilitychange", onVisibility);
    window.removeEventListener("blur", leave);
    window.removeEventListener("focus", back);
  };
}
