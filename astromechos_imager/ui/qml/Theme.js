// AstromechOS Imager — design tokens.
//
// Import as:   import "Theme.js" as Theme
// Reference:   Theme.colorAccent, Theme.fontTitle, etc.
//
// Single source of truth for the techno-droïde dark palette and font
// stack. Editing colors here propagates across every QML file.

.pragma library

// ── Surfaces ─────────────────────────────────────────────────────────
var colorBg        = "#0c1014"   // window background — near-black, deep blue undertone
var colorSurface   = "#161b21"   // card / panel idle
var colorSurface2  = "#1c232a"   // card hover
var colorSurfaceAccent = "#173746"  // card selected — dark teal tint
var colorHeader    = "#0e1318"   // header / footer chrome
var colorDivider   = "#22303a"   // hairline borders

// ── Borders ──────────────────────────────────────────────────────────
var colorBorderIdle    = "#22303a"
var colorBorderHover   = "#345566"
var colorBorderAccent  = "#3dd4c4"   // selected — cyan-teal LED-like
var colorBorderWarn    = "#e8a93d"
var colorBorderError   = "#e85a5a"

// ── Text ─────────────────────────────────────────────────────────────
var colorTextPrimary   = "#e6e8ea"
var colorTextSecondary = "#90979e"
var colorTextTertiary  = "#5a6068"
var colorTextMuted     = "#3a4048"
var colorTextAccent    = "#3dd4c4"
var colorTextOnAccent  = "#0c1014"

// ── Accents (LED-like) ───────────────────────────────────────────────
var colorAccent       = "#3dd4c4"  // primary techno cyan-teal
var colorAccentBright = "#5fe6d7"  // hover variant
var colorAccentDim    = "#2a8c80"  // disabled/dim variant
var colorAccentGlow   = "#3dd4c4"  // for shadow/glow; use with alpha

// ── Fonts ────────────────────────────────────────────────────────────
// Orbitron is bundled in resources/fonts and registered at startup
// (see app.py _load_fonts). When the family is missing — e.g. running
// without the TTF in dev — Qt falls back to "Segoe UI" automatically.
var fontTitle    = "Orbitron"     // Bold for big headlines
var fontSubtitle = "Orbitron"     // Medium for labels / step indicator
var fontBody     = "Segoe UI"     // readable prose
var fontMono     = "Consolas"     // paths, byte counts, code

// ── Geometry ─────────────────────────────────────────────────────────
var radiusCard   = 10
var radiusButton = 6
var radiusPip    = 5
var paddingCard  = 16
var spacingCard  = 14

// ── Motion ───────────────────────────────────────────────────────────
var durFast = 120
var durBase = 180
var durSlow = 280
