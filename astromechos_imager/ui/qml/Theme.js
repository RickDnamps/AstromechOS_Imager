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
// startup (app.py _load_fonts). Used EVERYWHERE in the UI — titles,
// subtitles, buttons, body copy, field labels. Brand identity is
// non-negotiable: AstromechOS Imager ships an authentic R2-D2 /
// Sci-Fi look. Reverts audit High #23, which had downgraded body
// copy to "Segoe UI" for readability; readability is now handled by
// tuning size / weight / colour contrast rather than the typeface.
// fontMono stays Consolas because monospaced character-cell predict-
// ability is functional (hash digests, drive paths), not stylistic.
var fontTitle    = "Orbitron"
var fontSubtitle = "Orbitron"
var fontBody     = "Orbitron"
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
