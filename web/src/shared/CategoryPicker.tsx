import type { Category } from "../api/types";
import { CATEGORY_LABEL } from "../lib/format";

/** «Категория»: Gemini fills it from the photo; tap to change, tap again to clear. */
export function CategoryPicker({ value, onChange }: { value: Category | null; onChange: (c: Category | null) => void }) {
  return (
    <div className="shop-chips">
      {(Object.keys(CATEGORY_LABEL) as Category[]).map((code) => (
        <button
          key={code}
          type="button"
          className={`chip ${value === code ? "active" : ""}`}
          onClick={() => onChange(value === code ? null : code)}
        >
          {CATEGORY_LABEL[code]}
        </button>
      ))}
    </div>
  );
}
