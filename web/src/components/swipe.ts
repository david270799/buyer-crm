import { type TouchEvent, useRef, useState } from "react";

/** One photo per swipe, however long or fast (the owner, 02.11.2026): the
 * browser's own scrolling flew past several photos on a strong swipe, so the
 * strip is moved by hand. A sideways swipe of 50 px (or a quick flick) goes
 * to the next or previous photo; an up/down move is left to the page. */
export function useSwipe(
  count: number,
  index: number,
  setIndex: (i: number) => void,
  onTap?: () => void,
) {
  const start = useRef<{ x: number; y: number; t: number } | null>(null);
  const lastTouch = useRef(0);
  const axis = useRef<"x" | "y" | null>(null);
  const [dx, setDx] = useState(0);

  const onTouchStart = (e: TouchEvent) => {
    if (e.touches.length !== 1) {
      start.current = null; // two fingers: the zoom's turn
      setDx(0);
      return;
    }
    start.current = { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() };
    axis.current = null;
  };
  const onTouchMove = (e: TouchEvent) => {
    if (!start.current || e.touches.length !== 1) return;
    const mx = e.touches[0].clientX - start.current.x;
    const my = e.touches[0].clientY - start.current.y;
    if (!axis.current) {
      if (Math.abs(mx) < 6 && Math.abs(my) < 6) return;
      axis.current = Math.abs(mx) > Math.abs(my) ? "x" : "y";
    }
    if (axis.current !== "x") return;
    const atEdge = (index === 0 && mx > 0) || (index === count - 1 && mx < 0);
    setDx(atEdge ? mx / 3 : mx);
  };
  const finish = (tap: boolean) => {
    if (!start.current) return;
    lastTouch.current = Date.now();
    // A tap is handled here, not by «click»: some webviews drop the click
    // right after a swipe.
    if (tap && !axis.current && Date.now() - start.current.t < 400) onTap?.();
    const speed = Math.abs(dx) / Math.max(1, Date.now() - start.current.t);
    if (axis.current === "x" && (Math.abs(dx) > 50 || speed > 0.4)) {
      setIndex(Math.min(count - 1, Math.max(0, index + (dx < 0 ? 1 : -1))));
    }
    start.current = null;
    setDx(0);
  };

  return {
    handlers: {
      onTouchStart,
      onTouchMove,
      onTouchEnd: () => finish(true),
      onTouchCancel: () => finish(false),
    },
    /** The strip's position: the current photo, plus the finger while dragging. */
    style: {
      transform: `translateX(calc(${-index * 100}% + ${dx}px))`,
      transition: dx ? "none" : "transform 0.3s ease",
    },
    /** For «click»: a mouse click on a computer, not the echo of a touch. */
    isMouseClick: () => Date.now() - lastTouch.current > 800,
  };
}
