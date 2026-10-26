import { Check, Download, ExternalLink, Eye, Heart, LayoutGrid, Loader2, RefreshCw, Search, ShoppingBag, ShoppingCart, Trash2, Undo2, X } from "lucide-react";
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  markShowcaseViewed,
  type ShowcasePatch,
  type ShowcaseStatKind,
  useShowcase,
  useShowcaseAction,
  useShowcaseAdd,
  useShowcaseItem,
  useShowcaseOrder,
  useShowcasePatch,
  useShowcaseStats,
} from "../api/hooks";
import type { Category, ShowcaseItem, ShowcaseSize } from "../api/types";
import { PageHead } from "../components/Layout";
import { Empty, ErrorState, Field, Loading, MoneyInput, errorText, useToast } from "../components/ui";
import { CATEGORY_LABEL, krw, moment, plural } from "../lib/format";
import { downloadFiles, overrideBack } from "../telegram";

// «Витрина» (the owner, 20.10.2026). Test mode: only the admin sees it; he
// walks the client's path himself (♥, size, cart, «Заказать») before it opens.

/** The client's Mini App shows the same pages (out of test mode, 20.10.2026)
 * without the admin's buttons; the server hides the shop fields anyway. */
const ClientMode = createContext(false);
export const ShowcaseClientMode = ClientMode.Provider;
const useClientMode = () => useContext(ClientMode);

/* ---------------------------------------------------------------- the cart */

type CartLine = { item_id: string; size: string | null; color?: string | null };
const CART_KEY = "crm-showcase-cart";

function readCart(): CartLine[] {
  try {
    const raw = JSON.parse(localStorage.getItem(CART_KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((l) => l && typeof l.item_id === "string") : [];
  } catch {
    return [];
  }
}

function writeCart(lines: CartLine[]): void {
  try {
    localStorage.setItem(CART_KEY, JSON.stringify(lines));
  } catch {
    /* storage unavailable */
  }
}

function useCart() {
  const [lines, setLines] = useState<CartLine[]>(readCart);
  const save = (next: CartLine[]) => {
    writeCart(next);
    setLines(next);
  };
  return {
    lines,
    add: (line: CartLine) => save([...lines, line]),
    remove: (index: number) => save(lines.filter((_, i) => i !== index)),
    clear: () => save([]),
  };
}

/* ----------------------------------------------------------------- pieces */

function Price({ item, big }: { item: ShowcaseItem; big?: boolean }) {
  const price = item.client_price_krw;
  // The official price is crossed out only when it is higher than ours.
  const was = item.official_price_krw && price && item.official_price_krw > price ? item.official_price_krw : null;
  return (
    <div className={`sc-price ${big ? "big" : ""}`}>
      <b>{price ? krw(price) : "цена —"}</b>
      {was ? <s>{krw(was)}</s> : null}
    </div>
  );
}

function SizeChips({
  sizes,
  selected,
  onSelect,
  counts,
}: {
  sizes: ShowcaseSize[];
  selected?: string | null;
  onSelect?: (name: string) => void;
  counts?: boolean;
}) {
  if (!sizes.length) return null;
  return (
    <div className={`sc-sizes ${onSelect ? "" : "small"}`}>
      {sizes.map((s) => {
        const low = s.available && s.stock !== null && s.stock <= 2;
        const cls = `sc-size ${s.available ? "" : "out"} ${low ? "low" : ""} ${selected === s.name ? "sel" : ""}`;
        const body = (
          <>
            {s.name}
            {counts && s.available && s.stock !== null ? <i>{s.stock}</i> : null}
          </>
        );
        return onSelect ? (
          <button key={s.name} type="button" className={cls} disabled={!s.available} onClick={() => onSelect(s.name)}>
            {body}
          </button>
        ) : (
          <span key={s.name} className={cls}>
            {body}
          </span>
        );
      })}
    </div>
  );
}

/** Colours of a colour → size product, each with its total stock. */
function colorsOf(sizes: ShowcaseSize[]): ShowcaseSize[] {
  const colors = new Map<string, ShowcaseSize>();
  for (const s of sizes) {
    if (!s.color) continue;
    const c = colors.get(s.color) ?? { name: s.color, stock: 0, available: false };
    c.stock = (c.stock ?? 0) + (s.stock ?? 0);
    c.available ||= s.available;
    colors.set(s.color, c);
  }
  return [...colors.values()];
}

/** On a tile: each size once (available in any colour). */
function sizesOnce(sizes: ShowcaseSize[]): ShowcaseSize[] {
  const once = new Map<string, ShowcaseSize>();
  for (const s of sizes) {
    const seen = once.get(s.name);
    once.set(s.name, seen ? { ...seen, available: seen.available || s.available } : { ...s, color: null });
  }
  return [...once.values()];
}

function LikeButton({ item, preview }: { item: ShowcaseItem; preview?: boolean }) {
  const toast = useToast();
  const action = useShowcaseAction(item.id);
  return (
    <button
      type="button"
      className={`sc-heart ${item.liked ? "on" : ""}`}
      aria-label={item.liked ? "Убрать из избранного" : "В избранное"}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (preview) return toast(PREVIEW_HINT);
        action.mutate("like", { onError: (err) => toast(errorText(err), "error") });
      }}
    >
      <Heart size={17} fill={item.liked ? "currentColor" : "none"} />
    </button>
  );
}

export function ShowcaseTile({ item, preview }: { item: ShowcaseItem; preview?: boolean }) {
  const body = (
    <>
      <div className="sc-photo">
        {item.thumbnail_url || item.photo_url ? <img src={item.thumbnail_url ?? item.photo_url ?? ""} alt="" /> : null}
        {item.shop && <span className="sc-shop">{item.shop}</span>}
        {!preview && <LikeButton item={item} />}
      </div>
      <div className="sc-body">
        <div className="sc-brand">{item.brand ?? item.shop ?? ""}</div>
        <div className="sc-model">{item.model ?? item.title_line}</div>
        <Price item={item} />
        {colorsOf(item.sizes).length > 1 && (
          <div className="tiny faint" style={{ marginBottom: 4 }}>
            {colorsOf(item.sizes).length} {plural(colorsOf(item.sizes).length, "цвет", "цвета", "цветов")}
          </div>
        )}
        <SizeChips sizes={sizesOnce(item.sizes)} />
      </div>
    </>
  );
  return preview ? (
    <div className="sc-tile">{body}</div>
  ) : (
    <Link to={`/showcase/${item.id}`} className="sc-tile">
      {body}
    </Link>
  );
}

function CartButton({ count }: { count: number }) {
  return (
    <Link to="/showcase/cart" className="btn small" aria-label="Корзина">
      <ShoppingCart size={16} />
      {count ? <span className="sc-count">{count}</span> : null}
    </Link>
  );
}

/* ------------------------------------------------------------ the showcase */

const FILTERS: { id: "all" | "liked" | Category; label: string }[] = [
  { id: "all", label: "Все" },
  { id: "liked", label: "♥ Избранное" },
  { id: "shoes", label: "Обувь" },
  { id: "clothes", label: "Одежда" },
  { id: "bag", label: "Сумки" },
  { id: "accessory", label: "Аксессуары" },
];

export function ShowcasePage() {
  const client = useClientMode();
  const { data, error, isLoading, refetch } = useShowcase("published");
  const cart = useCart();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["id"]>("all");
  const items = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data?.items ?? []).filter((item) => {
      if (filter === "liked" && !item.liked) return false;
      if (filter !== "all" && filter !== "liked" && item.category !== filter) return false;
      if (!needle) return true;
      return [item.brand, item.model, item.title, item.shop].some((v) => v?.toLowerCase().includes(needle));
    });
  }, [data, q, filter]);
  return (
    <>
      <PageHead
        title="Витрина"
        sub={client ? "Товары из Кореи — выберите размер и закажите" : undefined}
        action={<CartButton count={cart.lines.length} />}
      />
      <label className="search sc-search">
        <Search size={16} />
        <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск: бренд, модель" />
      </label>
      <div className="chips" style={{ margin: "10px 0 14px" }}>
        {FILTERS.map((f) => (
          <button key={f.id} className={`chip ${filter === f.id ? "active" : ""}`} onClick={() => setFilter(f.id)}>
            {f.label}
          </button>
        ))}
      </div>
      {isLoading ? (
        <Loading rows={4} height={180} />
      ) : error || !data ? (
        <ErrorState error={error} onRetry={refetch} />
      ) : !items.length ? (
        <Empty
          title={data.items.length ? "Ничего не найдено" : "На витрине пока пусто"}
          hint={
            data.items.length
              ? undefined
              : client
                ? "Скоро здесь появятся товары."
                : "Пришлите боту ссылку на товар, проверьте её в «Одобрении» и опубликуйте."
          }
          icon={<ShoppingBag size={22} />}
        />
      ) : (
        <div className="sc-grid">
          {items.map((item) => (
            <ShowcaseTile key={item.id} item={item} />
          ))}
        </div>
      )}
    </>
  );
}

/* ---------------------------------------------------------- one product */

export function ShowcaseItemPage() {
  const { id = "" } = useParams();
  const { data, error, isLoading, refetch } = useShowcaseItem(id);
  useEffect(() => {
    if (id) markShowcaseViewed(id);
  }, [id]);
  if (isLoading) return <Loading rows={3} height={140} />;
  if (error || !data) return <ErrorState error={error} onRetry={refetch} />;
  return <ShowcaseItemView item={data.item} />;
}

const PREVIEW_HINT = "Это предпросмотр: заказать можно после одобрения";

/** The product card as the client opens it. `preview` (from «Одобрение»,
 * the owner 20.10.2026): the same card with unsaved prices; ♥, cart and
 * «Заказать» only explain, nothing is counted or ordered. */
function ShowcaseItemView({ item, preview }: { item: ShowcaseItem; preview?: boolean }) {
  const client = useClientMode();
  const toast = useToast();
  const navigate = useNavigate();
  const action = useShowcaseAction(item.id);
  const order = useShowcaseOrder();
  const cart = useCart();
  const [size, setSize] = useState<string | null>(null);
  const colors = colorsOf(item.sizes);
  const [color, setColor] = useState<string | null>(null);
  const sizes = colors.length ? item.sizes.filter((s) => s.color === color) : item.sizes;
  const needsSize = item.sizes.length > 0;
  const ready = (!colors.length || Boolean(color)) && (!needsSize || Boolean(size));
  const choice = [color, size].filter(Boolean).join(" · ");
  return (
    <>
      <div className="sc-detail">
        {/* The owner (20.10.2026): a published card goes back to «Одобрение»
            to fix the price; hidden from the showcase until approved again.
            Admin-only, like the whole showcase while it is in test mode. */}
        {!preview && !client && item.status === "published" && (
          <button
            className="btn small sc-back-to-prep"
            disabled={action.isPending}
            onClick={() =>
              action.mutate("status/draft", {
                onSuccess: () => {
                  toast("Карточка снята с витрины и вернулась на одобрение");
                  navigate(`/prep/${item.id}`);
                },
                onError: (e) => toast(errorText(e), "error"),
              })
            }
          >
            <Undo2 size={15} /> Вернуть на одобрение
          </button>
        )}
        <ShowcasePhotos item={item} preview={preview} />
        <div className="sc-brand" style={{ marginTop: 14 }}>
          {item.brand}
          {item.category ? ` · ${CATEGORY_LABEL[item.category]}` : ""}
        </div>
        <h2 className="sc-title">{item.model ?? item.title_line}</h2>
        <Price item={item} big />
        {item.photos.length > 0 && (
          <button
            className="btn sc-download"
            onClick={() => {
              const base = `${item.brand ?? "photo"}_${item.model ?? item.id}`.replace(/\W+/g, "_");
              void downloadFiles(
                item.photos.map((p, i) => ({ url: p.photo_url, name: `${base}_${i + 1}.jpg` })),
              );
            }}
          >
            <Download size={18} /> {item.photos.length > 1 ? `Скачать все фото · ${item.photos.length}` : "Скачать фото"}
          </button>
        )}
        <div className="row between" style={{ margin: "16px 0 8px" }}>
          <span className="small muted">{colors.length ? "Цвет" : "Размер"}</span>
          <button
            className="btn small"
            disabled={action.isPending}
            onClick={() =>
              action.mutate("refresh", {
                onSuccess: () => toast(client ? "Наличие проверено" : "Наличие обновлено"),
                onError: (e) => toast(errorText(e), "error"),
              })
            }
          >
            {action.isPending ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />} Обновить
            {item.refreshed_at ? ` · ${ago(item.refreshed_at)}` : ""}
          </button>
        </div>
        {colors.length > 0 && (
          <>
            <SizeChips
              sizes={colors}
              selected={color}
              onSelect={(c) => {
                setColor(c);
                setSize(null);
              }}
              counts
            />
            <div className="small muted" style={{ margin: "16px 0 8px" }}>
              Размер
            </div>
          </>
        )}
        {colors.length > 0 && !color ? (
          <div className="small muted">Сначала выберите цвет.</div>
        ) : needsSize ? (
          <SizeChips sizes={sizes} selected={size} onSelect={setSize} counts />
        ) : (
          <div className="small muted">Размеры магазин не показал — укажите в комментарии к заказу.</div>
        )}
      </div>
      <div className="sc-cta">
        <button
          className="btn"
          disabled={!ready}
          onClick={() => {
            if (preview) return toast(PREVIEW_HINT);
            cart.add({ item_id: item.id, size, color });
            toast(`В корзине: ${cart.lines.length + 1}`);
          }}
        >
          <ShoppingCart size={16} /> В корзину
        </button>
        <button
          className="btn primary"
          disabled={!ready || order.isPending}
          onClick={() =>
            preview
              ? toast(PREVIEW_HINT)
              : order.mutate([{ item_id: item.id, size, color }], {
              onSuccess: (r) => {
                toast(
                  client
                    ? `Заказ ${r.items[0].id} отправлен байеру`
                    : `Заказ ${r.items.map((o) => o.id).join(", ")} создан — в «Новых»`,
                );
                navigate(`/orders/${r.items[0].id}`);
              },
              onError: (e) => toast(errorText(e), "error"),
            })
          }
        >
          {order.isPending
            ? "Подождите…"
            : colors.length && !color
              ? "Выберите цвет"
              : needsSize && !size
                ? "Выберите размер"
                : choice
                  ? `Заказать · ${choice}`
                  : "Заказать"}
        </button>
      </div>
    </>
  );
}

/** «Открыть как клиент» on «Одобрение»: the whole card over the page, with
 * the prices being edited; «Закрыть» or Telegram's «назад» returns. */
function FullPreview({ item, onClose }: { item: ShowcaseItem; onClose: () => void }) {
  useEffect(() => overrideBack(onClose), [onClose]);
  useEffect(() => {
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = overflow;
    };
  }, []);
  return (
    <div className="sc-full" role="dialog" aria-modal="true" aria-label="Предпросмотр карточки">
      <div className="sc-full-bar">
        <span>
          <Eye size={16} /> Так увидит клиент
        </span>
        <button className="btn small" onClick={onClose}>
          <X size={16} /> Закрыть
        </button>
      </div>
      <ShowcaseItemView item={item} preview />
    </div>
  );
}

/** Big photo; several photos swipe sideways with dots below. */
function ShowcasePhotos({ item, preview }: { item: ShowcaseItem; preview?: boolean }) {
  const [index, setIndex] = useState(0);
  const photos = item.photos;
  return (
    <div>
      <div className="sc-photo big">
        <div
          className="sc-swipe"
          onScroll={(e) => setIndex(Math.round(e.currentTarget.scrollLeft / Math.max(1, e.currentTarget.clientWidth)))}
        >
          {photos.map((p, i) => (
            <img key={`${i}-${p.photo_url}`} src={p.photo_url} alt="" loading={i ? "lazy" : "eager"} />
          ))}
        </div>
        {item.shop && <span className="sc-shop">{item.shop}</span>}
        <LikeButton item={item} preview={preview} />
      </div>
      {photos.length > 1 && (
        <div className="photo-dots" aria-hidden>
          {photos.map((p, i) => (
            <i key={`${i}-${p.photo_url}`} className={i === index ? "active" : ""} />
          ))}
        </div>
      )}
    </div>
  );
}

function ago(value: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000));
  if (minutes < 1) return "только что";
  if (minutes < 60) return `${minutes} мин назад`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours} ч назад` : `${Math.round(hours / 24)} дн. назад`;
}

/* ------------------------------------------------------------------ cart */

export function ShowcaseCartPage() {
  const client = useClientMode();
  const toast = useToast();
  const navigate = useNavigate();
  const cart = useCart();
  const { data } = useShowcase("published");
  const order = useShowcaseOrder();
  const byId = new Map((data?.items ?? []).map((i) => [i.id, i]));
  const lines = cart.lines.map((line, index) => ({ line, index, item: byId.get(line.item_id) }));
  const total = lines.reduce((sum, l) => sum + (l.item?.client_price_krw ?? 0), 0);
  const valid = lines.filter((l) => l.item).map((l) => l.line);
  return (
    <>
      <PageHead
        title="Корзина"
        action={
          cart.lines.length ? (
            <button className="btn small ghost" onClick={cart.clear}>
              Очистить
            </button>
          ) : undefined
        }
      />
      {!lines.length ? (
        <Empty title="Корзина пуста" hint="Выберите размер на карточке товара и нажмите «В корзину»." icon={<ShoppingCart size={22} />} />
      ) : (
        <>
          <div className="card list">
            {lines.map(({ line, index, item }) => (
              <div key={index} className="list-item" style={{ cursor: "default" }}>
                <div className="thumb">{item?.thumbnail_url ? <img src={item.thumbnail_url} alt="" /> : null}</div>
                <div className="grow" style={{ minWidth: 0 }}>
                  <div className="title">{item ? item.title_line : "Товар снят с витрины"}</div>
                  <div className="small muted">
                    {line.color ? `${line.color} · ` : ""}
                    {line.size ? `Размер ${line.size} · ` : ""}
                    {item?.client_price_krw ? krw(item.client_price_krw) : "—"}
                  </div>
                </div>
                <button className="btn small icon-only ghost" aria-label="Убрать" onClick={() => cart.remove(index)}>
                  <X size={16} />
                </button>
              </div>
            ))}
          </div>
          <div className="card pad" style={{ marginTop: 12 }}>
            <div className="row between">
              <span className="muted">Итого примерно</span>
              <b className="num" style={{ fontSize: 20 }}>
                {krw(total)}
              </b>
            </div>
            <div className="tiny faint" style={{ marginTop: 8 }}>
              {client
                ? "Деньги сейчас не списываются — только когда байер выкупит товар."
                : "Деньги сейчас не списываются. Заказы появятся в «Новых» с пометкой «Из витрины»."}
            </div>
          </div>
          <div className="sc-cta">
            <button
              className="btn primary"
              disabled={!valid.length || order.isPending}
              onClick={() =>
                order.mutate(valid, {
                  onSuccess: (r) => {
                    cart.clear();
                    toast(`${client ? "Заказы отправлены байеру" : "Создано"}: ${r.items.map((o) => o.id).join(", ")}`);
                    navigate(client ? "/orders" : "/orders?status=new");
                  },
                  onError: (e) => toast(errorText(e), "error"),
                })
              }
            >
              {order.isPending ? "Подождите…" : `Оформить ${valid.length} ${plural(valid.length, "заказ", "заказа", "заказов")}`}
            </button>
          </div>
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------ «Подготовка» */

const TABS: { id: ShowcaseItem["status"]; label: string }[] = [
  { id: "draft", label: "На одобрении" },
  { id: "published", label: "Опубликовано" },
  { id: "hidden", label: "Скрыто" },
];

export function PrepPage() {
  const toast = useToast();
  const [tab, setTab] = useState<ShowcaseItem["status"]>("draft");
  const [url, setUrl] = useState("");
  const { data, error, isLoading, refetch } = useShowcase();
  const add = useShowcaseAdd();
  const all = data?.items ?? [];
  const items = all.filter((i) => i.status === tab);
  const submit = () =>
    add.mutate(url.trim(), {
      onSuccess: (r) => {
        setUrl("");
        setTab("draft");
        toast(r.item.note ? `Черновик создан: ${r.item.note}` : "Черновик создан");
      },
      onError: (e) => toast(errorText(e), "error"),
    });
  return (
    <>
      <PageHead title="Одобрение" sub="Черновики витрины · только вы" />
      <div className="row" style={{ gap: 8 }}>
        <input
          className="input"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="Вставьте ссылку на товар"
          onKeyDown={(e) => {
            if (e.key === "Enter" && url.trim()) submit();
          }}
        />
        <button className="btn primary" disabled={!url.trim() || add.isPending} onClick={submit} aria-label="Добавить">
          {add.isPending ? <Loader2 className="spin" size={16} /> : "＋"}
        </button>
      </div>
      <div className="tiny faint" style={{ margin: "6px 0 12px" }}>
        Или просто пришлите ссылку боту — черновик появится здесь.
      </div>
      <div className="chips" style={{ marginBottom: 12 }}>
        {TABS.map((t) => (
          <button key={t.id} className={`chip ${tab === t.id ? "active" : ""}`} onClick={() => setTab(t.id)}>
            {t.label} {all.filter((i) => i.status === t.id).length}
          </button>
        ))}
      </div>
      {isLoading ? (
        <Loading rows={3} height={84} />
      ) : error || !data ? (
        <ErrorState error={error} onRetry={refetch} />
      ) : !items.length ? (
        <Empty title={tab === "draft" ? "Черновиков нет" : "Пусто"} icon={<ShoppingBag size={22} />} />
      ) : (
        <div className="card list">
          {items.map((item) => (
            <Link key={item.id} to={`/prep/${item.id}`} className="list-item">
              <div className="thumb">{item.thumbnail_url ? <img src={item.thumbnail_url} alt="" /> : null}</div>
              <div className="grow" style={{ minWidth: 0 }}>
                <div className="title">{item.title_line}</div>
                <div className="small muted">
                  {item.shop} · {item.shop_price_krw ? krw(item.shop_price_krw) : "цена не найдена"}
                  {item.sizes.length ? ` · ${item.sizes.filter((s) => s.available).map((s) => s.name).join(" ")}` : ""}
                </div>
              </div>
              {item.status === "draft" && (
                <span className={`badge ${item.shop_price_krw || item.client_price_override ? "warn" : "sc-bad"}`}>
                  {item.shop_price_krw || item.client_price_override ? "Проверить" : "Нет цены"}
                </span>
              )}
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

export function PrepItemPage() {
  const { id = "" } = useParams();
  const toast = useToast();
  const navigate = useNavigate();
  const { data, error, isLoading, refetch } = useShowcaseItem(id);
  if (isLoading) return <Loading rows={3} height={120} />;
  if (error || !data) return <ErrorState error={error} onRetry={refetch} />;
  return <PrepEditor key={data.item.id} item={data.item} onDone={() => navigate("/prep")} toast={toast} />;
}

function PrepEditor({
  item,
  onDone,
  toast,
}: {
  item: ShowcaseItem;
  onDone: () => void;
  toast: ReturnType<typeof useToast>;
}) {
  const save = useShowcasePatch(item.id);
  const action = useShowcaseAction(item.id);
  const [full, setFull] = useState(false);
  const [form, setForm] = useState({
    brand: item.brand ?? "",
    model: item.model ?? "",
    shop_price_krw: item.shop_price_krw,
    official_price_krw: item.official_price_krw,
    markup_type: item.markup_type,
    markup_value: item.markup_value as number | null,
    client_price_override: item.client_price_override,
  });
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm((f) => ({ ...f, [key]: value }));
  const auto = (() => {
    if (!form.shop_price_krw) return null;
    const m = form.markup_value ?? 0;
    const raw = form.markup_type === "pct" ? (form.shop_price_krw * (100 + m)) / 100 : form.shop_price_krw + m;
    return Math.ceil(raw / 100) * 100;
  })();
  const clientPrice = form.client_price_override || auto;
  const profit = clientPrice && form.shop_price_krw ? clientPrice - form.shop_price_krw : null;
  const preview: ShowcaseItem = {
    ...item,
    brand: form.brand || null,
    model: form.model || null,
    official_price_krw: form.official_price_krw,
    client_price_krw: clientPrice ?? null,
  };
  const body = (): ShowcasePatch => ({
    brand: form.brand.trim() || null,
    model: form.model.trim() || null,
    shop_price_krw: form.shop_price_krw,
    official_price_krw: form.official_price_krw,
    markup_type: form.markup_type,
    markup_value: form.markup_value ?? 0,
    client_price_override: form.client_price_override,
  });
  const publish = () =>
    save.mutate(body(), {
      onSuccess: () =>
        action.mutate("status/published", {
          onSuccess: () => {
            toast("Опубликовано на витрине");
            onDone();
          },
          onError: (e) => toast(errorText(e), "error"),
        }),
      onError: (e) => toast(errorText(e), "error"),
    });
  return (
    <>
      <PageHead
        title="Проверка карточки"
        sub={<span className={`badge ${item.status === "published" ? "s-delivered" : "warn"}`}>{STATUS_LABEL[item.status]}</span>}
      />
      {item.note && <div className="banner info small" style={{ marginBottom: 12 }}>⚠️ Не удалось: {item.note}</div>}
      {/* The owner (20.10.2026): check the price on the shop page itself. */}
      <a className="btn sc-shop-link" href={item.url} target="_blank" rel="noopener noreferrer">
        <ExternalLink size={16} /> Открыть в магазине{item.shop ? ` · ${item.shop}` : ""}
      </a>
      <div className="card pad stack">
        <div className="form-grid two">
          <Field label="Бренд">
            <input className="input" value={form.brand} onChange={(e) => set("brand", e.target.value)} />
          </Field>
          <Field label="Модель">
            <input className="input" value={form.model} onChange={(e) => set("model", e.target.value)} />
          </Field>
          <Field label="Цена в магазине">
            <MoneyInput value={form.shop_price_krw} onChange={(v) => set("shop_price_krw", v)} />
          </Field>
          <Field
            label="Официальная цена"
            hint={item.official_url ? `Найдено: ${new URL(item.official_url).hostname}` : "Для зачёркивания, если выше вашей"}
          >
            <MoneyInput value={form.official_price_krw} onChange={(v) => set("official_price_krw", v)} placeholder="не указана" />
          </Field>
          <button
            type="button"
            className="btn small"
            style={{ alignSelf: "flex-start" }}
            disabled={action.isPending}
            onClick={() =>
              action.mutate("official", {
                onSuccess: (r) => {
                  const found = r.item?.official_price_krw;
                  if (found) set("official_price_krw", found);
                  toast(found ? `Официальная цена: ${krw(found)}` : "Официальная цена не найдена — впишите сами");
                },
                onError: (e) => toast(errorText(e), "error"),
              })
            }
          >
            <Search size={14} /> Найти официальную цену
          </button>
        </div>
        <div className="row" style={{ gap: 8, alignItems: "flex-end" }}>
          <div className="field" style={{ flex: 1 }}>
            <span>Ваша наценка</span>
            <div className="row" style={{ gap: 6 }}>
              <div className="chips" style={{ margin: 0, padding: 0, flex: "none", overflow: "visible" }}>
                {(["krw", "pct"] as const).map((t) => (
                  <button key={t} className={`chip ${form.markup_type === t ? "active" : ""}`} onClick={() => set("markup_type", t)}>
                    {t === "krw" ? "+ ₩" : "%"}
                  </button>
                ))}
              </div>
              <MoneyInput value={form.markup_value} onChange={(v) => set("markup_value", v)} placeholder="0" noUsd={form.markup_type === "pct"} />
            </div>
          </div>
        </div>
        <Field label="Цена для клиента" hint={form.client_price_override ? "Своя цена — наценка не учитывается" : "Магазин + наценка, вверх до ₩ 100"}>
          <MoneyInput value={form.client_price_override ?? auto} onChange={(v) => set("client_price_override", v && v !== auto ? v : null)} />
        </Field>
        {profit !== null && <div className={`small ${profit < 0 ? "negative" : "positive"}`}>Ваша прибыль: {krw(profit, true)}</div>}
      </div>
      <div className="row between" style={{ margin: "18px 0 8px" }}>
        <span className="small muted">Как увидит клиент</span>
        <button
          className="btn small"
          disabled={action.isPending}
          onClick={() => action.mutate("refresh", { onSuccess: () => toast("Наличие обновлено"), onError: (e) => toast(errorText(e), "error") })}
        >
          <RefreshCw size={14} /> Обновить наличие
        </button>
      </div>
      <button type="button" className="sc-preview" onClick={() => setFull(true)} aria-label="Открыть карточку как клиент">
        <ShowcaseTile item={preview} preview />
        <span className="sc-preview-open">
          <Eye size={14} /> Открыть как клиент
        </span>
      </button>
      {full && <FullPreview item={preview} onClose={() => setFull(false)} />}
      <div className="sc-cta">
        <button
          className="btn ghost danger"
          aria-label="Удалить"
          onClick={() =>
            action.mutate("delete", {
              onSuccess: () => {
                toast("Карточка удалена");
                onDone();
              },
            })
          }
        >
          <Trash2 size={16} />
        </button>
        {item.status === "published" ? (
          <>
            <button className="btn" onClick={() => save.mutate(body(), { onSuccess: () => toast("Сохранено"), onError: (e) => toast(errorText(e), "error") })}>
              Сохранить
            </button>
            <button className="btn" onClick={() => action.mutate("status/hidden", { onSuccess: () => toast("Скрыто с витрины") })}>
              Скрыть
            </button>
          </>
        ) : (
          <button className="btn primary" disabled={!clientPrice || save.isPending || action.isPending} onClick={publish}>
            <Check size={16} /> Одобрить и опубликовать
          </button>
        )}
      </div>
    </>
  );
}

const STATUS_LABEL: Record<ShowcaseItem["status"], string> = {
  draft: "Черновик",
  published: "Опубликовано",
  hidden: "Скрыто",
};

/* ------------------------------------------------------- «Статистика» */

type StatFilter = "cards" | "views" | "likes" | "orders";

const STAT_TILES: { key: StatFilter; label: string; title: string; icon: typeof Eye }[] = [
  { key: "cards", label: "карточек", title: "Открытые карточки", icon: LayoutGrid },
  { key: "views", label: "просмотров", title: "Просмотры", icon: Eye },
  { key: "likes", label: "лайков", title: "Лайки", icon: Heart },
  { key: "orders", label: "заказов", title: "Заказы", icon: ShoppingCart },
];

const KIND_TEXT: Record<ShowcaseStatKind, string> = {
  view: "Открыл",
  like: "♥ Лайкнул",
  unlike: "Убрал ♥",
  order: "Заказал",
};

/** The owner (20.10.2026): four totals on top that filter the list below; by
 * default the whole history; next to each row how often the card was opened. */
export function ShowcaseStatsPage() {
  const { data, error, isLoading, refetch } = useShowcaseStats();
  const [viewer, setViewer] = useState<string | null>(null);
  const [filter, setFilter] = useState<StatFilter | null>(null);
  const view = useMemo(() => {
    const mine = <T extends { viewer: string | null }>(rows: T[]) => rows.filter((r) => !viewer || r.viewer === viewer);
    const cards = mine(data?.cards ?? []);
    const history = mine(data?.history ?? []);
    const perItem = new Map<string, { views: number; liked: boolean; last_at: string | null }>();
    for (const c of cards) {
      const row = perItem.get(c.item_id) ?? { views: 0, liked: false, last_at: null };
      row.views += c.views;
      row.liked ||= c.liked;
      if (c.last_at && (!row.last_at || c.last_at > row.last_at)) row.last_at = c.last_at;
      perItem.set(c.item_id, row);
    }
    const lastLike = new Map<string, string>();
    for (const h of history) if (h.kind === "like" && h.item_id && h.at && !lastLike.has(h.item_id)) lastLike.set(h.item_id, h.at);
    const opened = [...perItem.entries()].filter(([, r]) => r.views > 0);
    const liked = [...perItem.entries()].filter(([, r]) => r.liked);
    const orders = history.filter((h) => h.kind === "order");
    return {
      perItem,
      lastLike,
      opened: opened.sort((a, b) => b[1].views - a[1].views),
      liked: liked.sort((a, b) => (lastLike.get(b[0]) ?? "").localeCompare(lastLike.get(a[0]) ?? "")),
      history,
      totals: {
        cards: opened.length,
        views: opened.reduce((sum, [, r]) => sum + r.views, 0),
        likes: liked.length,
        orders: orders.length,
      } as Record<StatFilter, number>,
    };
  }, [data, viewer]);

  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorState error={error} onRetry={() => void refetch()} />;
  const views = (id: string | null) => (id ? view.perItem.get(id)?.views ?? 0 : 0);
  const labels = new Map(data.viewers.map((v) => [v.viewer, v.label]));
  const who = (id: string | null) => (data.viewers.length > 1 && id ? `${labels.get(id) ?? ""} · ` : "");

  const row = (key: string, itemId: string | null, sub: string, to?: string) => {
    const item = itemId ? data.items[itemId] : undefined;
    return (
      <Link key={key} to={to ?? (itemId && item ? `/showcase/${itemId}` : "#")} className="list-item">
        <div className="thumb">{item?.thumbnail_url ? <img src={item.thumbnail_url} alt="" /> : null}</div>
        <div className="grow" style={{ minWidth: 0 }}>
          <div className="title">{item?.title ?? "Карточка удалена"}</div>
          <div className="small muted">{sub}</div>
        </div>
        <span className="sc-views" title="Сколько раз открыта">
          <Eye size={14} /> {views(itemId)}
        </span>
      </Link>
    );
  };

  let rows: JSX.Element[];
  if (filter === "cards") {
    rows = view.opened.map(([id, r]) => row(id, id, `${r.liked ? "♥ · " : ""}последний раз ${moment(r.last_at)}`));
  } else if (filter === "likes") {
    rows = view.liked.map(([id]) => row(id, id, view.lastLike.has(id) ? `♥ ${moment(view.lastLike.get(id))}` : "♥"));
  } else {
    const kinds: ShowcaseStatKind[] | null = filter === "views" ? ["view"] : filter === "orders" ? ["order"] : null;
    rows = view.history
      .filter((h) => !kinds || kinds.includes(h.kind))
      .map((h, i) => {
        const extra = h.kind === "order" ? `${h.size ? ` · ${h.size}` : ""}${h.order_id ? ` · ${h.order_id}` : ""}` : "";
        return row(
          `${i}-${h.at}`,
          h.item_id,
          `${who(h.viewer)}${KIND_TEXT[h.kind]}${extra} · ${moment(h.at)}`,
          h.kind === "order" && h.order_id ? `/orders/${h.order_id}` : undefined,
        );
      });
  }
  const title = filter ? STAT_TILES.find((t) => t.key === filter)!.title : "История";

  return (
    <>
      <PageHead title="Статистика" sub="Витрина" />
      {data.viewers.length > 1 && (
        <div className="chips" style={{ marginBottom: 10 }}>
          <button className={`chip ${viewer ? "" : "active"}`} onClick={() => setViewer(null)}>
            Все
          </button>
          {data.viewers.map((v) => (
            <button key={v.viewer} className={`chip ${viewer === v.viewer ? "active" : ""}`} onClick={() => setViewer(v.viewer)}>
              {v.label}
            </button>
          ))}
        </div>
      )}
      <div className="sc-stats">
        {STAT_TILES.map((t) => (
          <button
            key={t.key}
            className={filter === t.key ? "active" : ""}
            aria-pressed={filter === t.key}
            onClick={() => setFilter(filter === t.key ? null : t.key)}
          >
            <b>{view.totals[t.key]}</b>
            <span>
              <t.icon size={11} /> {t.label}
            </span>
          </button>
        ))}
      </div>
      <div className="row between" style={{ margin: "18px 0 8px" }}>
        <h3>{title}</h3>
        {filter && (
          <button className="btn small ghost" onClick={() => setFilter(null)}>
            <X size={14} /> Вся история
          </button>
        )}
      </div>
      {rows.length ? (
        <div className="card list">{rows}</div>
      ) : (
        <Empty title="Пока пусто" hint="Здесь появится, кто какие карточки открывал, лайкал и заказывал." />
      )}
    </>
  );
}
