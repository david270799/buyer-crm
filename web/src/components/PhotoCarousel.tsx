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

function Lightbox({ photos, start, onClose }: { photos: CarouselPhoto[]; start: number; onClose: () => void }) {
  const strip = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState(start);
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
        onScroll={(e) => {
          const el = e.currentTarget;
          setIndex(Math.round(el.scrollLeft / Math.max(1, el.clientWidth)));
        }}
      >
        {photos.map((photo, i) => (
          <div key={`${photo.photo_url}-${i}`} className="lightbox-slide" onClick={onClose}>
            <img src={photo.photo_url} alt="" onClick={(e) => e.stopPropagation()} />
          </div>
        ))}
      </div>
      <div className="lightbox-bar">
        <span>{photos.length > 1 ? `${index + 1} / ${photos.length}` : ""}</span>
        <button type="button" className="btn icon-only small" onClick={onClose} aria-label="Закрыть">
          <X size={18} />
        </button>
      </div>
    </div>
  );
}
