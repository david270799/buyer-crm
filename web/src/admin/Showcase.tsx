import { Check, Download, Heart, Loader2, RefreshCw, Search, ShoppingBag, ShoppingCart, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  markShowcaseViewed,
  type ShowcasePatch,
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
import { CATEGORY_LABEL, krw, plural } from "../lib/format";
import { downloadFile } from "../telegram";

// «Витрина» (the owner, 20.10.2026). Test mode: only the admin sees it; he
// walks the client's path himself (♥, size, cart, «Заказать») before it opens.

/* ---------------------------------------------------------------- the cart */

type CartLine = { item_id: string; size: string | null };
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

function LikeButton({ item }: { item: ShowcaseItem }) {
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
        <SizeChips sizes={item.sizes} />
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
        sub={<span className="sc-test">тест · видите только вы</span>}
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
          hint={data.items.length ? undefined : "Пришлите боту ссылку на товар, проверьте её в «Подготовке» и опубликуйте."}
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
  const toast = useToast();
  const navigate = useNavigate();
  const { data, error, isLoading, refetch } = useShowcaseItem(id);
  const action = useShowcaseAction(id);
  const order = useShowcaseOrder();
  const cart = useCart();
  const [size, setSize] = useState<string | null>(null);
  useEffect(() => {
    if (id) markShowcaseViewed(id);
  }, [id]);
  if (isLoading) return <Loading rows={3} height={140} />;
  if (error || !data) return <ErrorState error={error} onRetry={refetch} />;
  const item = data.item;
  const needsSize = item.sizes.length > 0;
  const ready = !needsSize || Boolean(size);
  return (
    <>
      <div className="sc-detail">
        <div className="sc-photo big">
          {item.photo_url ? <img src={item.photo_url} alt="" /> : null}
          {item.shop && <span className="sc-shop">{item.shop}</span>}
          <LikeButton item={item} />
        </div>
        <div className="sc-brand" style={{ marginTop: 14 }}>
          {item.brand}
          {item.category ? ` · ${CATEGORY_LABEL[item.category]}` : ""}
        </div>
        <h2 className="sc-title">{item.model ?? item.title_line}</h2>
        <Price item={item} big />
        {item.photo_url && (
          <button
            className="btn sc-download"
            onClick={() => {
              const name = `${(item.brand ?? "photo").replace(/\W+/g, "_")}_${(item.model ?? item.id).replace(/\W+/g, "_")}.jpg`;
              downloadFile(item.photo_url!, name);
              toast("Фото сохраняется в галерею");
            }}
          >
            <Download size={18} /> Скачать фото
          </button>
        )}
        <div className="row between" style={{ margin: "16px 0 8px" }}>
          <span className="small muted">Размер</span>
          <button
            className="btn small"
            disabled={action.isPending}
            onClick={() =>
              action.mutate("refresh", {
                onSuccess: () => toast("Наличие обновлено"),
                onError: (e) => toast(errorText(e), "error"),
              })
            }
          >
            {action.isPending ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />} Обновить
            {item.refreshed_at ? ` · ${ago(item.refreshed_at)}` : ""}
          </button>
        </div>
        {needsSize ? (
          <SizeChips sizes={item.sizes} selected={size} onSelect={setSize} counts />
        ) : (
          <div className="small muted">Размеры магазин не показал — укажите в комментарии к заказу.</div>
        )}
      </div>
      <div className="sc-cta">
        <button
          className="btn"
          disabled={!ready}
          onClick={() => {
            cart.add({ item_id: item.id, size });
            toast(`В корзине: ${cart.lines.length + 1}`);
          }}
        >
          <ShoppingCart size={16} /> В корзину
        </button>
        <button
          className="btn primary"
          disabled={!ready || order.isPending}
          onClick={() =>
            order.mutate([{ item_id: item.id, size }], {
              onSuccess: (r) => {
                toast(`Заказ ${r.items.map((o) => o.id).join(", ")} создан — в «Новых»`);
                navigate(`/orders/${r.items[0].id}`);
              },
              onError: (e) => toast(errorText(e), "error"),
            })
          }
        >
          {order.isPending ? "Подождите…" : needsSize ? (size ? `Заказать · ${size}` : "Выберите размер") : "Заказать"}
        </button>
      </div>
    </>
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
              Деньги сейчас не списываются. Заказы появятся в «Новых» с пометкой «Из витрины».
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
                    toast(`Создано: ${r.items.map((o) => o.id).join(", ")}`);
                    navigate("/orders?status=new");
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
      <PageHead title="Подготовка" sub="Витрина · только вы" />
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
              <MoneyInput value={form.markup_value} onChange={(v) => set("markup_value", v)} placeholder="0" />
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
      <div className="sc-preview">
        <ShowcaseTile item={preview} preview />
      </div>
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

/* ------------------------------------------------- statistics («Настройки») */

export function ShowcaseStatsCard() {
  const { data } = useShowcaseStats();
  const viewers = data?.viewers ?? [];
  return (
    <div className="card pad stack">
      <h3>Статистика витрины</h3>
      {!viewers.length ? (
        <div className="small muted">Пока никто не открывал карточки.</div>
      ) : (
        viewers.map((v) => (
          <div key={v.viewer} className="stack" style={{ gap: 8 }}>
            <div className="row between">
              <b>{v.label}</b>
              <span className="tiny faint">{v.last_at ? `был ${new Date(v.last_at).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : ""}</span>
            </div>
            <div className="sc-stats">
              <div>
                <b>{v.cards_opened}</b>
                <span>карточек открыл</span>
              </div>
              <div>
                <b>{v.opens}</b>
                <span>просмотров</span>
              </div>
              <div>
                <b>{v.likes}</b>
                <span>♥ лайков</span>
              </div>
              <div>
                <b>{v.orders}</b>
                <span>заказов</span>
              </div>
            </div>
            {v.top.length > 0 && (
              <div className="small">
                <div className="tiny faint" style={{ marginBottom: 4 }}>Чаще всего смотрел</div>
                {v.top.map((t) => (
                  <Link key={t.id} to={`/showcase/${t.id}`} className="row between sc-stat-row">
                    <span>
                      {t.liked ? "♥ " : ""}
                      {t.title}
                    </span>
                    <span className="num faint">{t.opens}×</span>
                  </Link>
                ))}
              </div>
            )}
            {v.liked.length > 0 && (
              <div className="small">
                <div className="tiny faint" style={{ marginBottom: 4 }}>Лайкнул</div>
                {v.liked.map((t) => (
                  <Link key={t.id} to={`/showcase/${t.id}`} className="row between sc-stat-row">
                    <span>♥ {t.title}</span>
                    <span className="num faint">{t.opens}×</span>
                  </Link>
                ))}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}
