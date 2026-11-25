"""Satır içi SVG simgeler; dış dosya yok, renk `currentColor`'dan gelir (K-128)."""

from typing import Final

from markupsafe import Markup

_STROKE: Final = (
    'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
    'stroke-linejoin="round"'
)


def _icon(paths: str, *, filled: bool = False) -> Markup:
    style = 'fill="currentColor"' if filled else _STROKE
    return Markup(f'<svg viewBox="0 0 24 24" {style} aria-hidden="true">{paths}</svg>')  # noqa: S704 - sabit metin


ICONS: Final = {
    "ozet": _icon('<path d="M4 12a8 8 0 1 0 8-8v8z"/><path d="M15 3.5a8 8 0 0 1 5.5 5.5H15z"/>'),
    "varliklar": _icon('<path d="M12 3 3 8l9 5 9-5z"/><path d="m3 13 9 5 9-5"/>'),
    "islemler": _icon('<path d="M7 4v14M4 15l3 3 3-3M17 20V6M14 9l3-3 3 3"/>'),
    "dagilim": _icon('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>'),
    "getiri": _icon('<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>'),
    "raporlar": _icon('<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/>'),
    "alarmlar": _icon('<path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>'),
    "sistem": _icon('<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>'),
    "ayarlar": _icon(
        '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/>'
        '<circle cx="10" cy="17" r="2"/>'
    ),
    "daha": _icon(
        '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/>'
        '<circle cx="19" cy="12" r="1.6"/>',
        filled=True,
    ),
    "uyari": _icon('<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>'),
    "bilgi": _icon('<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>'),
    "tamam": _icon('<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>'),
    "hata": _icon('<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16h.01"/>'),
    "bos": _icon('<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 9h8M8 13h5"/>'),
    "hedef": _icon('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/>'),
    "kilit": _icon(
        '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>'
    ),
    "kilit_acik": _icon(
        '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.5-2"/>'
    ),
}


def icon(name: str) -> Markup:
    return ICONS[name]
