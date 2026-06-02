// Inline-SVG runtime injection for VitePress theme
// ────────────────────────────────────────────────────
// VitePress renders `features.icon: { src }` as <img class="VPImage">
// and inline `.md-icon` Markdown images as <img> too. With <img>, CSS
// doesn't cascade into the SVG DOM — `stroke="currentColor"` falls
// through to raw black, and we can't do two-tone coloring.
//
// This module replaces every icon <img> with its inline <svg> source
// fetched from /public. Class attributes are preserved so CSS in
// style.css can target `.VPFeature svg.VPImage` and `svg.md-icon`
// directly — setting `stroke: var(--icon-stroke)` actually works.
//
// After swap, all <path> elements beyond the first are tagged with
// class="accent". Main shape follows --icon-stroke; decorative
// paths (sparkle twinkles, bolt flash, etc) follow --icon-accent.
// Each of the 4 preset styles (+ light/dark) defines its own pair.

const cache = new Map<string, Promise<string>>()

async function fetchSvg(src: string): Promise<string> {
  if (!cache.has(src)) cache.set(src, fetch(src).then(r => r.text()))
  return cache.get(src)!
}

function decorate(svg: SVGSVGElement, keepClass: string, width: string | null, height: string | null): void {
  svg.setAttribute('class', keepClass)
  if (width)  svg.setAttribute('width',  width)
  if (height) svg.setAttribute('height', height)
  // Lucide convention: first <path> is the primary shape; remaining
  // paths are decorative accents (twinkles, secondary strokes).
  const paths = svg.querySelectorAll('path, circle, line, polyline, rect')
  paths.forEach((p, i) => { if (i > 0) p.classList.add('accent') })
}

async function swapOne(img: HTMLImageElement): Promise<void> {
  if (img.dataset.inlined) return
  img.dataset.inlined = '1'
  const src = img.getAttribute('src')
  if (!src || !src.endsWith('.svg')) return

  try {
    const raw = await fetchSvg(src)
    const doc = new DOMParser().parseFromString(raw, 'image/svg+xml')
    const svg = doc.documentElement as unknown as SVGSVGElement
    if (svg.nodeName.toLowerCase() !== 'svg') return
    decorate(svg, img.className, img.getAttribute('width'), img.getAttribute('height'))
    img.replaceWith(svg)
  } catch {
    // Network error or invalid SVG — leave the <img> as a fallback
  }
}

export function inlineIcons(root: ParentNode = document): void {
  const imgs = root.querySelectorAll<HTMLImageElement>(
    '.VPFeature img.VPImage, img.md-icon'
  )
  imgs.forEach(img => { void swapOne(img) })
}

// Watch route + layout changes — VitePress SPA-navigates between pages,
// so we re-run on every DOM mutation that adds candidate <img> elements.
let observer: MutationObserver | null = null
export function startInlineIconsWatcher(): void {
  if (typeof window === 'undefined' || observer) return
  inlineIcons()
  observer = new MutationObserver(mutations => {
    for (const m of mutations) {
      for (const n of m.addedNodes) {
        if (n.nodeType === 1) inlineIcons(n as Element)
      }
    }
  })
  observer.observe(document.body, { childList: true, subtree: true })
}
