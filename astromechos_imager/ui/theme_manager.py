"""Runtime-switchable theme palette exposed to QML as `theme`.

Each color token is reachable as `theme.colors.colorXxx` from QML — the
`colors` property returns a QVariantMap that swaps wholesale whenever the
operator toggles the mode via the sun/moon icon in the header. All QML
bindings that read `theme.colors.X` re-evaluate automatically on the
`paletteChanged` signal.

Font, duration and radius constants stay in qml/Theme.js (they don't vary
across modes), so QML files still `import "Theme.js" as Theme` for those.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal, Slot


# Tokens for elements that sit on the dark chrome (header + footer).
# The chrome bg is `#0e1217` in BOTH modes, so its foregrounds must stay
# constant too — otherwise the navy text-on-navy-bg vanishes in Light.
_ON_CHROME = {
    "colorTextOnChrome":     "#e6e8ea",   # primary chrome label (title)
    "colorTextOnChromeDim":  "#7a8086",   # secondary chrome label / icons
    "colorChromePipInactive": "#2a2f34",  # future-step pip on header
}


_DARK = {
    # Surfaces (deep dark, blue undertone) ────────────────────────────
    "colorBg":            "#101418",
    "colorSurface":       "#1a1f24",
    "colorSurface2":      "#262b30",
    "colorSurfaceAccent": "#1c3550",
    "colorHeader":        "#0e1217",
    "colorDivider":       "#2a2f34",
    # Borders ─────────────────────────────────────────────────────────
    "colorBorderIdle":    "#2c333a",
    "colorBorderHover":   "#3e5366",
    "colorBorderAccent":  "#5e9bd6",   # LED cyan-blue (R2 piloting accent)
    "colorBorderWarn":    "#e8a93d",
    "colorBorderError":   "#c0433a",
    # Text ────────────────────────────────────────────────────────────
    "colorTextPrimary":   "#e6e8ea",
    "colorTextSecondary": "#8b96a3",
    "colorTextTertiary":  "#5c6671",
    "colorTextMuted":     "#3a4048",
    "colorTextAccent":    "#7eb8e8",
    "colorTextOnAccent":  "#0c1014",
    # Accents ─────────────────────────────────────────────────────────
    "colorAccent":        "#5e9bd6",
    "colorAccentBright":  "#7eb8e8",
    "colorAccentDim":     "#3d6e9e",
    "colorAccentGlow":    "#5e9bd6",
    # Audit High #26: success / warn / error semantic colours, themed.
    # Light tones are still WCAG AA on dark surfaces; light-theme values
    # are darkened for AA on white cards. Replaces the hardcoded
    # #5ec07a green that failed contrast on light cards.
    "colorTextSuccess":   "#6cc987",
    "colorTextWarn":      "#e8a93d",
    **_ON_CHROME,
}


# Light theme derived from the R2 piloting captures (Captures/*.png):
# dark navy chrome + off-white content + cobalt blue accent. The header
# stays dark so the app keeps its identity continuity in both modes.
_LIGHT = {
    "colorBg":            "#eef2f8",
    "colorSurface":       "#ffffff",
    "colorSurface2":      "#e5edf9",
    "colorSurfaceAccent": "#cee0f5",
    "colorHeader":        "#0e1217",
    "colorDivider":       "#c8d3e2",
    "colorBorderIdle":    "#c8d3e2",
    "colorBorderHover":   "#8aa3c5",
    "colorBorderAccent":  "#1e5db8",   # cobalt (Light-mode LED)
    "colorBorderWarn":    "#d68a1e",
    "colorBorderError":   "#c0433a",
    "colorTextPrimary":   "#1a2840",
    "colorTextSecondary": "#56627a",
    "colorTextTertiary":  "#8a93a3",
    "colorTextMuted":     "#bcc4d0",
    "colorTextAccent":    "#1e5db8",
    "colorTextOnAccent":  "#ffffff",
    "colorAccent":        "#1e5db8",
    "colorAccentBright":  "#2c70d4",
    "colorAccentDim":     "#7099c6",
    "colorAccentGlow":    "#1e5db8",
    # Darker green satisfies WCAG AA on white (~4.7:1 vs the failing
    # 2.3:1 of #5ec07a). Amber kept slightly darker than dark theme.
    "colorTextSuccess":   "#2f8a4a",
    "colorTextWarn":      "#b27310",
    **_ON_CHROME,
}


class ThemeManager(QObject):
    """Exposes mode + palette to QML. Toggle via `theme.toggle()`."""

    modeChanged = Signal(str)
    paletteChanged = Signal()

    MODE_DARK = "dark"
    MODE_LIGHT = "light"

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mode = self.MODE_DARK

    @Property(str, notify=modeChanged)
    def mode(self) -> str:
        return self._mode

    @Property("QVariantMap", notify=paletteChanged)
    def colors(self) -> dict[str, str]:
        return _LIGHT if self._mode == self.MODE_LIGHT else _DARK

    @Slot()
    def toggle(self) -> None:
        self._mode = self.MODE_LIGHT if self._mode == self.MODE_DARK else self.MODE_DARK
        self.modeChanged.emit(self._mode)
        self.paletteChanged.emit()

    @Slot(str)
    def setMode(self, mode: str) -> None:
        """Useful for tests / scripted captures."""
        if mode in (self.MODE_DARK, self.MODE_LIGHT) and mode != self._mode:
            self._mode = mode
            self.modeChanged.emit(self._mode)
            self.paletteChanged.emit()
