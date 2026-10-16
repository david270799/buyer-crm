import { Check, Pencil, Plus, X } from "lucide-react";
import { useState } from "react";

import { useSetShops, useShops } from "../api/hooks";
import { errorText, useToast } from "../components/ui";

/** «Магазин»: bubbles to tap (tap again to clear), «+» to add one's own shop,
 * the pencil to remove shops from the list. Only the admin sees the shop. */
export function ShopPicker({ value, onChange }: { value: string | null; onChange: (shop: string | null) => void }) {
  const toast = useToast();
  const { data } = useShops();
  const save = useSetShops();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const names = data?.names ?? [];
  const shown = value && !names.some((n) => n.toLowerCase() === value.toLowerCase()) ? [value, ...names] : names;

  const add = () => {
    const name = draft.trim();
    if (!name) return;
    const exists = names.find((n) => n.toLowerCase() === name.toLowerCase());
    onChange(exists ?? name);
    setDraft("");
    setAdding(false);
    if (!exists) save.mutate([...names, name], { onError: (e) => toast(errorText(e), "error") });
  };

  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="shop-chips">
        {shown.map((name) => (
          <button
            key={name}
            type="button"
            className={`chip ${value === name ? "active" : ""}`}
            onClick={() => {
              if (editing) {
                if (value === name) onChange(null);
                save.mutate(
                  names.filter((n) => n !== name),
                  { onError: (e) => toast(errorText(e), "error") },
                );
              } else onChange(value === name ? null : name);
            }}
          >
            {name}
            {editing && <X size={12} style={{ marginLeft: 4 }} />}
          </button>
        ))}
        {!adding && (
          <button type="button" className="chip" aria-label="Добавить магазин" onClick={() => setAdding(true)}>
            <Plus size={14} />
          </button>
        )}
        <button
          type="button"
          className={`chip ${editing ? "active" : ""}`}
          aria-label={editing ? "Готово" : "Убрать магазины из списка"}
          onClick={() => setEditing(!editing)}
        >
          {editing ? <Check size={14} /> : <Pencil size={13} />}
        </button>
      </div>
      {adding && (
        <div className="row" style={{ gap: 6 }}>
          <input
            className="input"
            autoFocus
            value={draft}
            placeholder="Название магазина"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") add();
            }}
          />
          <button type="button" className="btn small primary" disabled={!draft.trim()} onClick={add}>
            Добавить
          </button>
          <button type="button" className="btn small ghost" onClick={() => setAdding(false)}>
            <X size={14} />
          </button>
        </div>
      )}
      {editing && <div className="tiny faint">Нажмите на магазин, чтобы убрать его из списка.</div>}
    </div>
  );
}
