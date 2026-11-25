"""Türkçe sayı biçimi; raporu gösteren her kanal (metin, Telegram, web) aynısını kullanır."""

from collections.abc import Mapping
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, Literal

from finans.domain.models import YearMonth
from finans.domain.numeric import canonical_text

# str.upper "i"yi "I" yapar; Türkçede "İ" olmalı.
_TURKISH_UPPER = {"i": "İ", "ı": "I"}


def class_label(code: str, labels: Mapping[str, str]) -> str:
    """Sınıf adı `[sinif_adlari]`'dan; yoksa koddan türetilir (K-128)."""
    if code in labels:
        return labels[code]
    words = code.replace("_", " ")
    first = words[:1]
    return _TURKISH_UPPER.get(first, first.upper()) + words[1:]


def _digits(value: Decimal, places: int) -> tuple[str, str]:
    """Banker yuvarlaması; binlik ayırıcı nokta, ondalık ayırıcı virgül."""
    rounded = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN)
    integer, _, fraction = f"{abs(rounded):f}".partition(".")
    text = f"{int(integer):,}".replace(",", ".") + (f",{fraction}" if places else "")
    sign = "-" if rounded < 0 else ("+" if rounded > 0 else "")
    return sign, text


def money(value: Decimal) -> str:
    sign, text = _digits(value, 2)
    return f"{'-' if sign == '-' else ''}{text} TL"


def percent(rate: Decimal, *, places: int = 2, signed: bool = False) -> str:
    sign, text = _digits(rate * 100, places)
    return f"{sign if signed or sign == '-' else ''}%{text}"


def points(deviation: Decimal) -> str:
    sign, text = _digits(deviation * 100, 1)
    return f"{sign}{text} puan"


def exact(value: Decimal) -> str:
    """Fiyat ve adet yuvarlanmadan, ondalık ayırıcı virgülle (ör. 12,83827)."""
    return canonical_text(value).replace(".", ",")


MONTHS: Final = (
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)
# Yalın, ilgi (-ın: "Kasım'ın") ve bulunma (-da: "Kasım'da") hâli.
type Case = Literal["", "in", "de"]
_VOWELS: Final = "aıoueiöü"
_BACK_VOWELS: Final = "aıou"
_VOICELESS: Final = "fstkçşhp"
_GENITIVE_VOWEL: Final = {
    "a": "ı",
    "ı": "ı",
    "o": "u",
    "u": "u",
    "e": "i",
    "i": "i",
    "ö": "ü",
    "ü": "ü",
}
_ONES: Final = ("", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz")
_TENS: Final = ("", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan")


def _spoken_tail(number: int) -> str:
    """Sayının okunuşundaki son kelime; ek ona uyar (2026 → "altı", 2030 → "otuz")."""
    if number % 10:
        return _ONES[number % 10]
    if number % 100:
        return _TENS[number // 10 % 10]
    if number % 1000:
        return "yüz"
    return "bin"


def _suffix(word: str, case: Case) -> str:
    """Ünlü uyumu ve sert ünsüz benzeşmesiyle ek; özel ada kesme işaretiyle bağlanır."""
    if not case:
        return ""
    word = word.lower()
    vowel = next(letter for letter in reversed(word) if letter in _VOWELS)
    if case == "in":
        buffer = "n" if word[-1] in _VOWELS else ""
        return f"'{buffer}{_GENITIVE_VOWEL[vowel]}n"
    consonant = "t" if word[-1] in _VOICELESS else "d"
    return f"'{consonant}{'a' if vowel in _BACK_VOWELS else 'e'}"


def day_label(day: date, *, today: date, case: Case = "", year: bool | None = None) -> str:
    """Web'de gün: "25 Kasım"; yıl bugünkünden farklıysa ya da istenirse "25 Kasım 2026".
    Formlar ve adres parametreleri ISO kalır; CLI bu biçimi kullanmaz."""
    month = MONTHS[day.month - 1]
    if year if year is not None else day.year != today.year:
        return f"{day.day} {month} {day.year}{_suffix(_spoken_tail(day.year), case)}"
    return f"{day.day} {month}{_suffix(month, case)}"


def month_label(period: YearMonth | str, *, case: Case = "") -> str:
    """Rapor sözleşmesi dönemi "2026-10" metni olarak taşır; ikisi de kabul edilir."""
    if isinstance(period, str):
        period = YearMonth.parse(period)
    return f"{MONTHS[period.month - 1]} {period.year}{_suffix(_spoken_tail(period.year), case)}"


def same_places(*values: Decimal | None) -> tuple[str | None, ...]:
    """Karşılaştırılan fiyatlar aynı basamak sayısıyla, ikisinin büyüğüyle (11 → 11,000000)."""
    given = [value for value in values if value is not None]
    places = max((_places(value) for value in given), default=0)
    step = Decimal(1).scaleb(-places)
    return tuple(
        None if value is None else f"{value.quantize(step):f}".replace(".", ",") for value in values
    )


def _places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0
