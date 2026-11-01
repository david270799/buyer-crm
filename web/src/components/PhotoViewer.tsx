import { X } from "lucide-react";
import { useEffect, useRef, useState, type TouchEvent } from "react";

import { overrideBack } from "../telegram";

/** Photos over the whole screen (the owner, 02.11.2026): swipe to the next one,
 * spread two fingers to zoom like in the phone's gallery; on release the photo
 * slides back to its place. «×» or Telegram's «назад» closes it. */
export function PhotoViewer({ photos, start, onClose }: { photos: string[]; start: number; onClose: () => void }) {
  const strip = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState(start);
  useEffect(() => overrideBack(onClose), [onClose]);
  useEffect(() => {
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const node = strip.current;
    if (node) node.scrollLeft = start * node.clientWidth;
    return () => {
      document.body.style.overflow = overflow;
    };
  }, [start]);
  return (
    <div className="pv" role="dialog" aria-modal="true" aria-label="Фото">
      <div
        ref={strip}
        className="pv-strip"
        onScroll={(e) => setIndex(Math.round(e.currentTarget.scrollLeft / Math.max(1, e.currentTarget.clientWidth)))}
      >
        {photos.map((url, i) => (
          <ZoomSlide key={`${i}-${url}`} url={url} />
        ))}
      </div>
      <div className="pv-bar">
        <span className="num">
          {photos.length > 1 ? `${index + 1} / ${photos.length}` : ""}
        </span>
        <button className="pv-close" onClick={onClose} aria-label="Закрыть">
          <X size={22} />
        </button>
      </div>
    </div>
  );
}

interface Pinch {
  distance: number;
  x: number;
  y: number;
}

function measure(e: TouchEvent): Pinch {
  const [a, b] = [e.touches[0], e.touches[1]];
  return {
    distance: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY),
    x: (a.clientX + b.clientX) / 2,
    y: (a.clientY + b.clientY) / 2,
  };
}

/** One photo: two fingers zoom and move it, letting go puts it back. */
function ZoomSlide({ url }: { url: string }) {
  const image = useRef<HTMLImageElement>(null);
  const from = useRef<Pinch | null>(null);
  const place = (transform: string, animate: boolean) => {
    if (!image.current) return;
    image.current.style.transition = animate ? "transform 0.25s ease" : "none";
    image.current.style.transform = transform;
  };
  return (
    <div
      className="pv-slide"
      onTouchStart={(e) => {
        if (e.touches.length !== 2 || !image.current) return;
        from.current = measure(e);
        // Zoom around the point between the fingers.
        const box = image.current.getBoundingClientRect();
        image.current.style.transformOrigin = `${from.current.x - box.left}px ${from.current.y - box.top}px`;
      }}
      onTouchMove={(e) => {
        if (e.touches.length !== 2 || !from.current) return;
        const now = measure(e);
        const scale = Math.min(4, Math.max(1, now.distance / from.current.distance));
        place(`translate(${now.x - from.current.x}px, ${now.y - from.current.y}px) scale(${scale})`, false);
      }}
      onTouchEnd={(e) => {
        if (e.touches.length < 2 && from.current) {
          from.current = null;
          place("none", true);
        }
      }}
    >
      <img ref={image} src={url} alt="" draggable={false} />
    </div>
  );
}
