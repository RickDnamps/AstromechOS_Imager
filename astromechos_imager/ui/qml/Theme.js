// AstromechOS Imager — theme-independent design tokens.
//
// Import as:   import "Theme.js" as Theme
// Reference:   Theme.fontTitle, Theme.radiusCard, Theme.durBase, etc.
//
// Color tokens have moved to the Python `theme.colors.X` context property
// because they need to swap at runtime when the operator toggles
// dark/light via the sun/moon button in the header. Everything else
// stays here (fonts, durations, geometry) — those don't vary with mode.

.pragma library

// ── Fonts ────────────────────────────────────────────────────────────
// Orbitron is bundled in resources/fonts as OTF and registered at
// startup (app.py _load_fonts). Segoe UI is the safe Windows fallback.
//
// Audit High #23: Orbitron is a *display* face, not a body face — at
// 11–12 px it slows reading and breaks the title/body hierarchy. Body
// copy now falls back to the system humanist sans (Segoe UI on Win10+).
// Titles, subtitles, button captions, badges keep Orbitron for identity.
var fontTitle    = "Orbitron"
var fontSubtitle = "Orbitron"
var fontBody     = "Segoe UI"
var fontMono     = "Consolas"

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
