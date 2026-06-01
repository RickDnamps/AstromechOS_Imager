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
// HYBRID typography (operator decision, 2026-06): Orbitron keeps the
// R2-D2 / Sci-Fi brand on the PROMINENT, SHORT elements — big step
// titles, button captions and field labels (all `fontTitle`) — while
// the SMALLER running text (descriptive subtitles + body / helper copy)
// uses Segoe UI, the native Windows UI font, because Orbitron's wide
// geometric letterforms are tiring to read at small sizes / long
// sentences. This supersedes the earlier "Orbitron everywhere" rule.
// Orbitron is still bundled (resources/fonts, app.py _load_fonts);
// Segoe UI ships with Windows so needs no bundling. fontMono stays
// Consolas for hash digests / drive paths (functional monospacing).
var fontTitle    = "Orbitron"     // big titles, buttons, short caps labels
var fontSubtitle = "Segoe UI"     // descriptive subtitle lines
var fontBody     = "Segoe UI"     // body + helper copy (long, small text)
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
