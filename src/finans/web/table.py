"""Tablo sorgusu (K-129): sıralama, filtre ve sayfalama adres parametreleriyle yapılır ve
satırlar Python'da süzülür; Decimal SQL'de değil burada karşılaştırılır. Anlaşılmayan bir
parametre hata vermez: yok sayılır ve sayfada adıyla gösterilir."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final
from urllib.parse import urlencode

from finans.application.inputs import InputError, parse_day

PAGE_SIZE: Final = 25
SEARCH_MAX: Final = 64
_ECHO_MAX: Final = 40
SORT: Final = "sirala"
DIRECTION: Final = "yon"
PAGE: Final = "sayfa"
FROM: Final = "bas"
TO: Final = "bit"
SEARCH: Final = "ara"
# Telefondaki tek seçim kutusu "sütun.yön" gönderir; bağlantılar sirala ve yon taşır.
SORT_SELECT: Final = "siralama"
_DESCENDING: Final = {"artan": False, "azalan": True}


@dataclass(frozen=True, slots=True)
class Column[R]:
    key: str
    label: str
    # Sıralama anahtarı; Decimal, date, int ya da str döner.
    value: Callable[[R], Any]
    directions: tuple[str, str] = ("artan", "azalan")


@dataclass(frozen=True, slots=True)
class Choice[R]:
    key: str
    label: str
    options: Callable[[Sequence[R]], list[tuple[str, str]]]
    match: Callable[[R, str], bool]
    # Varsayılan seçenek uygulanır ama etkin filtre sayılmaz (ör. iptal=goster).
    default: str | None = None


@dataclass(frozen=True, slots=True)
class TableSpec[R]:
    columns: tuple[Column[R], ...]
    default_sort: str
    default_descending: bool
    tiebreak: Callable[[R], int]
    choices: tuple[Choice[R], ...] = ()
    day: Callable[[R], date] | None = None
    search: Callable[[R], str] | None = None
    page_size: int = PAGE_SIZE


@dataclass(frozen=True, slots=True)
class Chip:
    name: str
    value: str
    remove: str
    day: bool = False


@dataclass(frozen=True, slots=True)
class TableView[R]:
    rows: list[R]
    total: int
    page: int
    pages: int
    sort: str
    descending: bool
    params: dict[str, str]
    active: list[Chip]
    misunderstood: str
    options: dict[str, list[tuple[str, str]]]
    spec: TableSpec[R]

    @property
    def sort_choices(self) -> list[tuple[str, str, bool]]:
        """Seçim kutusu için (değer, etiket, seçili) üçlüleri."""
        return [
            (
                f"{column.key}.{direction}",
                f"{column.label}: {column.directions[descending]}",
                column.key == self.sort and descending == self.descending,
            )
            for column in self.spec.columns
            for descending, direction in ((False, "artan"), (True, "azalan"))
        ]

    def url(self, **changes: str | None) -> str:
        """Geçerli filtrelerle bağlantı; sayfa yalnız açıkça verilirse taşınır."""
        params = dict(self.params)
        for key, value in changes.items():
            if value is None:
                params.pop(key, None)
            else:
                params[key] = value
        return f"?{urlencode(params)}"

    def sort_url(self, key: str) -> str:
        if key == self.sort:
            descending = not self.descending
        else:
            descending = key == self.spec.default_sort and self.spec.default_descending
        return self.url(**{SORT: key, DIRECTION: "azalan" if descending else "artan", PAGE: None})

    def aria_sort(self, key: str) -> str:
        if key != self.sort:
            return "none"
        return "descending" if self.descending else "ascending"

    def value(self, key: str) -> str:
        return self.params.get(key, "")


def _fold(text: str) -> str:
    """Arama gevşek: İ, I, ı ve i aynı sayılır; büyük-küçük harf fark etmez."""
    return text.replace("İ", "i").replace("I", "i").replace("ı", "i").lower()


def _echo(key: str, value: str) -> str:
    return f"{key}={value[:_ECHO_MAX]}"


def table[R](
    rows: Sequence[R],
    params: Mapping[str, str],
    spec: TableSpec[R],
    *,
    passthrough: Sequence[str] = (),
) -> TableView[R]:
    params = {key: value for key, value in params.items() if value != ""}
    known = {SORT, DIRECTION, PAGE, FROM, TO, SEARCH, SORT_SELECT, *(c.key for c in spec.choices)}
    misunderstood = [
        _echo(key, value)
        for key, value in params.items()
        if key not in known and key not in passthrough
    ]
    understood: dict[str, str] = {}
    chips: list[tuple[str, str, str, bool]] = []
    columns = {column.key: column for column in spec.columns}

    if SORT_SELECT in params:
        column, _, chosen = params[SORT_SELECT].partition(".")
        if column in {c.key for c in spec.columns} and chosen in _DESCENDING:
            params = {**params, SORT: column, DIRECTION: chosen}
        else:
            misunderstood.append(_echo(SORT_SELECT, params[SORT_SELECT]))
    sort = params.get(SORT, spec.default_sort)
    if sort not in columns:
        misunderstood.append(_echo(SORT, sort))
        sort = spec.default_sort
    elif SORT in params:
        understood[SORT] = sort
    direction = params.get(DIRECTION)
    descending = spec.default_descending if sort == spec.default_sort else False
    if direction is not None:
        if direction in _DESCENDING:
            descending = _DESCENDING[direction]
            understood[DIRECTION] = direction
        else:
            misunderstood.append(_echo(DIRECTION, direction))

    options = {choice.key: choice.options(rows) for choice in spec.choices}
    selected: list[tuple[Choice[R], str]] = []
    for choice in spec.choices:
        given = params.get(choice.key)
        labels = dict(options[choice.key])
        if given is not None and given not in labels:
            misunderstood.append(_echo(choice.key, given))
            given = None
        value = given if given is not None else choice.default
        if value is not None:
            selected.append((choice, value))
        if given is not None and given != choice.default:
            understood[choice.key] = given
            chips.append((choice.key, choice.label, labels[given], False))

    search = params.get(SEARCH, "").strip()[:SEARCH_MAX] if spec.search else ""
    if search:
        understood[SEARCH] = search
        chips.append((SEARCH, "Arama", search, False))

    start, end = _day_range(params, misunderstood) if spec.day else (None, None)
    for key, name, day in ((FROM, "Başlangıç", start), (TO, "Bitiş", end)):
        if day is not None:
            understood[key] = day.isoformat()
            chips.append((key, name, day.isoformat(), True))

    kept = [
        row
        for row in rows
        if all(choice.match(row, value) for choice, value in selected)
        and (not search or spec.search is None or _fold(search) in _fold(spec.search(row)))
        and _within(spec.day, row, start, end)
    ]
    # Önce eşitlik bozucu, sonra asıl sütun: sıralama kararlı olduğu için eşitlikte numara sırası.
    kept.sort(key=spec.tiebreak, reverse=descending)
    kept.sort(key=columns[sort].value, reverse=descending)

    pages = max(1, -(-len(kept) // spec.page_size))
    page = 1
    if PAGE in params:
        raw = params[PAGE]
        if raw.isascii() and raw.isdigit() and int(raw) >= 1:
            page = min(int(raw), pages)
        else:
            misunderstood.append(_echo(PAGE, raw))
    first = (page - 1) * spec.page_size

    view = TableView(
        rows=kept[first : first + spec.page_size],
        total=len(kept),
        page=page,
        pages=pages,
        sort=sort,
        descending=descending,
        params=understood,
        active=[],
        misunderstood=", ".join(misunderstood),
        options=options,
        spec=spec,
    )
    view.active.extend(
        Chip(name, value, view.url(**{key: None, PAGE: None}), day)
        for key, name, value, day in chips
    )
    return view


def _day_range(
    params: Mapping[str, str], misunderstood: list[str]
) -> tuple[date | None, date | None]:
    days: dict[str, date | None] = {}
    for key in (FROM, TO):
        raw = params.get(key)
        days[key] = None
        if raw is None or not raw:
            continue
        try:
            days[key] = parse_day(raw)
        except InputError:
            misunderstood.append(_echo(key, raw))
    start, end = days[FROM], days[TO]
    if start is not None and end is not None and start > end:
        misunderstood.append(f"{_echo(FROM, params[FROM])}, {_echo(TO, params[TO])}")
        return None, None
    return start, end


def _within[R](
    day: Callable[[R], date] | None, row: R, start: date | None, end: date | None
) -> bool:
    if day is None:
        return True
    value = day(row)
    return (start is None or value >= start) and (end is None or value <= end)
