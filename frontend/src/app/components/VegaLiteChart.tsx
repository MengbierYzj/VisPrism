import { useEffect, useMemo, useRef, useState } from "react";
import embed, { type Result } from "vega-embed";

export type VegaViewHandle = Result["view"];

/**
 * 渲染真实 Vega-Lite spec（svg），并缩放适配容器宽度。
 * spec 保持后端返回的原样（含机构令牌直注的颜色/字号/尺寸），不在前端改写。
 */
export function VegaLiteChart({
  spec,
  maxHeight = 200,
  className = "",
  onViewReady,
}: {
  spec: object | null;
  /** Set to null when the chart should grow freely with its container. */
  maxHeight?: number | null;
  className?: string;
  onViewReady?: (view: VegaViewHandle | null) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const specKey = useMemo(() => (spec ? JSON.stringify(spec) : ""), [spec]);

  useEffect(() => {
    if (!ref.current || !spec) return;
    let cancelled = false;
    let result: Result | null = null;
    setError(null);

    embed(ref.current, spec as Record<string, unknown>, {
      actions: false,
      renderer: "svg",
      config: {},
    })
      .then((r) => {
        if (cancelled) {
          r.finalize();
          return;
        }
        result = r;
        onViewReady?.(r.view);
        const embedContainer = ref.current?.querySelector<HTMLElement>(".vega-embed");
        if (embedContainer) {
          // vega-embed creates an inline-sized wrapper. Make that wrapper track
          // the proposal card, otherwise the SVG can only grow inside its initial width.
          embedContainer.style.display = "block";
          embedContainer.style.width = "100%";
          embedContainer.style.maxWidth = "100%";
        }
        const svg = ref.current?.querySelector("svg");
        if (svg) {
          const w = parseFloat(svg.getAttribute("width") ?? "0");
          const h = parseFloat(svg.getAttribute("height") ?? "0");
          if (w && h) {
            svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
            svg.removeAttribute("width");
            svg.removeAttribute("height");
            svg.style.width = "100%";
            svg.style.maxWidth = "100%";
            svg.style.height = "auto";
            svg.style.maxHeight = maxHeight === null ? "none" : `${maxHeight}px`;
            svg.style.display = "block";
          }
        }
      })
      .catch((e: Error) => {
        if (!cancelled) {
          setError(e.message);
          onViewReady?.(null);
        }
      });

    return () => {
      cancelled = true;
      onViewReady?.(null);
      result?.finalize();
    };
  }, [specKey, maxHeight, onViewReady]);

  if (!spec) {
    return (
      <div className={`flex items-center justify-center text-[10px] text-muted-foreground bg-secondary/40 rounded-md ${className}`} style={{ minHeight: 72 }}>
        Paste a valid Vega-Lite spec
      </div>
    );
  }
  if (error) {
    return (
      <div className={`flex items-center justify-center text-[10px] text-red-500 bg-red-50 rounded-md px-2 text-center ${className}`} style={{ minHeight: 72 }}>
        Render error: {error.slice(0, 120)}
      </div>
    );
  }
  return <div ref={ref} className={className} style={{ overflow: "hidden", width: "100%", fontFamily: "Arial, Helvetica, sans-serif" }} />;
}
