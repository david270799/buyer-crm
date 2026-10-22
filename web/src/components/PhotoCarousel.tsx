import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export interface CarouselPhoto {
  photo_url: string;
  thumbnail_url: string | null;
}

/** A row of medium photos that scrolls sideways; a tap opens the photo full screen. */
export function PhotoCarousel({ photos, alt }: { photos: CarouselPhoto[]; alt: string }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!photos.length) return null;
  return (
    <>
      <div className="carousel" role="list">
        {photos.map((photo, index) => (
          <button
            key={`${photo.photo_url}-${index}`}
            type="button"
            className="carousel-slide"
            role="listitem"
            onClick={() => setOpen(index)}
            aria-label={`${alt}: фото ${index + 1} из ${photos.length}`}
          >
            <img src={photo.thumbnail_url ?? photo.photo_url} alt="" loading="lazy" />
          </button>
        ))}
      </div>
      {photos.length > 1 && <div className="tiny faint">{photos.length} фото · листайте в сторону</div>}
      {open !== null && <Lightbox photos={photos} start={open} onClose={() => setOpen(null)} />}
    </>
  );
}

export function Lightbox({ photos, start, onClose }: { photos: CarouselPhoto[]; start: number; onClose: () => void }) {
  const strip = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState(start);
  const [zoomed, setZoomed] = useState(false);
  useEffect(() => {
    const el = strip.current;
    if (el) el.scrollLeft = start * el.clientWidth;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [start, onClose]);
  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label="Фото">
      <div
        className="lightbox-strip"
        ref={strip}
        style={zoomed ? { overflowX: "hidden" } : undefined}
        onScroll={(e) => {
          const el = e.currentTarget;
          setIndex(Math.round(el.scrollLeft / Math.max(1, el.clientWidth)));
        }}
      >
        {photos.map((photo, i) => (
          <div key={`${photo.photo_url}-${i}`} className="lightbox-slide" onClick={zoomed ? undefined : onClose}>
            <ZoomableImage src={photo.photo_url} onZoom={setZoomed} />
          </div>
        ))}
      </div>
      <div className="lightbox-bar">
        <span>
          {photos.length > 1 ? `${index + 1} / ${photos.length}` : ""}
          {!zoomed && <span className="lightbox-hint"> Разведите пальцы или нажмите дважды — увеличить</span>}
        </span>
        <button type="button" className="btn icon-only small" onClick={onClose} aria-label="Закрыть">
          <X size={18} />
        </button>
      </div>
    </div>
  );
}

const MAX_SCALE = 5;

/** Pinch with two fingers (or double tap / mouse wheel) to zoom; drag to move a
 * zoomed photo. At normal size the gallery still swipes sideways. */
function ZoomableImage({ src, onZoom }: { src: string; onZoom: (zoomed: boolean) => void }) {
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 });
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const gesture = useRef<{ dist: number; scale: number; x: number; y: number; px: number; py: number } | null>(null);
  const lastTap = useRef(0);

  const apply = (scale: number, x: number, y: number) => {
    const s = Math.min(MAX_SCALE, Math.max(1, scale));
    const next = s === 1 ? { scale: 1, x: 0, y: 0 } : { scale: s, x, y };
    setView(next);
    onZoom(next.scale > 1);
  };

  const points = () => [...pointers.current.values()];
  const onPointerDown = (e: React.PointerEvent) => {
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (view.scale > 1 || pointers.current.size === 2) e.currentTarget.setPointerCapture(e.pointerId);
    const [a, b] = points();
    gesture.current = {
      dist: b ? Math.hypot(a.x - b.x, a.y - b.y) : 0,
      scale: view.scale,
      x: view.x,
      y: view.y,
      px: b ? (a.x + b.x) / 2 : a.x,
      py: b ? (a.y + b.y) / 2 : a.y,
    };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!pointers.current.has(e.pointerId) || !gesture.current) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const [a, b] = points();
    const g = gesture.current;
    if (b && g.dist > 0) {
      const scale = g.scale * (Math.hypot(a.x - b.x, a.y - b.y) / g.dist);
      const mx = (a.x + b.x) / 2;
      const my = (a.y + b.y) / 2;
      apply(scale, g.x + (mx - g.px), g.y + (my - g.py));
    } else if (view.scale > 1) {
      apply(view.scale, g.x + (a.x - g.px), g.y + (a.y - g.py));
    }
  };
  const onPointerUp = (e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId);
    gesture.current = null;
    if (pointers.current.size === 1) {
      // One finger left after a pinch: continue as a drag from here.
      const [a] = points();
      gesture.current = { dist: 0, scale: view.scale, x: view.x, y: view.y, px: a.x, py: a.y };
    }
  };
  const onClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    const now = Date.now();
    if (now - lastTap.current < 300) {
      if (view.scale > 1) apply(1, 0, 0);
      else apply(2.5, 0, 0);
      lastTap.current = 0;
    } else {
      lastTap.current = now;
    }
  };
  const onWheel = (e: React.WheelEvent) => {
    apply(view.scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15), view.x, view.y);
  };

  return (
    <img
      src={src}
      alt=""
      draggable={false}
      className="zoomable"
      style={{
        transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
        touchAction: view.scale > 1 ? "none" : "pan-x",
        cursor: view.scale > 1 ? "grab" : "zoom-in",
      }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onClick={onClick}
      onWheel={onWheel}
    />
  );
}
