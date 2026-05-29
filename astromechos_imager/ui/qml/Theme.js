// AstromechOS Imager — design tokens.
//
// Import as:   import "Theme.js" as Theme
// Reference:   Theme.colorAccent, Theme.fontTitle, etc.
//
// Single source of truth for the R2-D2 control dark palette: matches the
// piloting UI (see ui/resources/images/R2-D2_Ligth_Theme_*.png) so both
// surfaces share the same identity. Editing colors here propagates
// across every QML file.

.pragma library

// ── Surfaces (deep dark, slight blue undertone) ──────────────────────
var colorBg            = "#101418"   // window background
var colorSurface       = "#1a1f24"   // card / panel idle
var colorSurface2      = "#262b30"   // card hover / row-2
var colorSurfaceAccent = "#1c3550"   // card selected — saturated blue tint
var colorHeader        = "#0e1217"   // header / footer chrome
var colorDivider       = "#2a2f34"   // hairline borders

// ── Borders ──────────────────────────────────────────────────────────
var colorBorderIdle   = "#2c333a"
var colorBorderHover  = "#3e5366"
var colorBorderAccent = "#5e9bd6"   // selected — LED cyan-blue (R2 piloting accent)
var colorBorderWarn   = "#e8a93d"
var colorBorderError  = "#c0433a"   // matches the "EMERGENCY STOP" red

// ── Text ─────────────────────────────────────────────────────────────
var colorTextPrimary   = "#e6e8ea"
var colorTextSecondary = "#8b96a3"
var colorTextTertiary  = "#5c6671"
var colorTextMuted     = "#3a4048"
var colorTextAccent    = "#7eb8e8"   // hue-shifted variant of accent for body text
var colorTextOnAccent  = "#0c1014"

// ── Accents (LED-like cyan-blue, matching R2 piloting surface) ──────
var colorAccent       = "#5e9bd6"   // primary accent
var colorAccentBright = "#7eb8e8"   // hover variant
var colorAccentDim    = "#3d6e9e"   // disabled / dim
var colorAccentGlow   = "#5e9bd6"   // for shadow/glow; use with alpha

// ── Fonts ────────────────────────────────────────────────────────────
// Orbitron is bundled in resources/fonts as OTF and registered at
// startup (see app.py _load_fonts). Segoe UI is the safe Windows
// fallback when the family is unavailable (dev mode without OTFs etc.).
var fontTitle    = "Orbitron"
var fontSubtitle = "Orbitron"
var fontBody     = "Orbitron"     // R2 piloting UI uses Orbitron everywhere
var fontMono     = "Consolas"     // for paths and byte counts

// ── Geometry ─────────────────────────────────────────────────────────
var radiusCard   = 8
var radiusButton = 5
var radiusPip    = 5
var paddingCard  = 16
var spacingCard  = 14

// ── Motion ───────────────────────────────────────────────────────────
var durFast = 120
var durBase = 180
var durSlow = 280
