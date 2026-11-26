"""Tablo yanıtı (K-129): sıralama, filtre ve sayfa sunucuda; kurallar `sunum.table`'dadır.

Sorgu parametreleri doğrulanmaz, çünkü anlaşılmayan parametre hata değildir: yok sayılır ve
`ignored`'da bildirilir. Şemadaki parametre listesi yalnız istemcinin tipleri içindir."""

from collections.abc import Callable
from typing import Any

from finans.api.models import Model
from finans.sunum.table import (
    DIRECTION,
    FROM,
    PAGE,
    SEARCH,
    SORT,
    SORT_SELECT,
    TO,
    TableSpec,
    TableView,
)


class TableColumn(Model):
    key: str
    label: str
    directions: list[str]


class TableOption(Model):
    value: str
    label: str


class TableChoice(Model):
    key: str
    label: str
    options: list[TableOption]
    default: str | None


class TableChip(Model):
    key: str
    name: str
    value: str
    day: bool


class Table[R](Model):
    rows: list[R]
    total: int
    page: int
    pages: int
    page_size: int
    sort: str
    descending: bool
    # İstemci sütun bağlantısını web'deki gibi kurar: varsayılan sütuna dönüş varsayılan yönle.
    default_sort: str
    default_descending: bool
    params: dict[str, str]
    active: list[TableChip]
    ignored: str
    columns: list[TableColumn]
    choices: list[TableChoice]
    day_filter: bool
    search: bool


def table_data[R, I](view: TableView[R], item: Callable[[R], I]) -> Table[I]:
    spec = view.spec
    return Table[I](
        rows=[item(row) for row in view.rows],
        total=view.total,
        page=view.page,
        pages=view.pages,
        page_size=spec.page_size,
        sort=view.sort,
        descending=view.descending,
        default_sort=spec.default_sort,
        default_descending=spec.default_descending,
        params=view.params,
        active=[TableChip(key=c.key, name=c.name, value=c.value, day=c.day) for c in view.active],
        ignored=view.misunderstood,
        columns=[
            TableColumn(key=c.key, label=c.label, directions=list(c.directions))
            for c in spec.columns
        ],
        choices=[
            TableChoice(
                key=choice.key,
                label=choice.label,
                options=[TableOption(value=v, label=t) for v, t in view.options[choice.key]],
                default=choice.default,
            )
            for choice in spec.choices
        ],
        day_filter=spec.day is not None,
        search=spec.search is not None,
    )


def _parameter(name: str, description: str, **schema: Any) -> dict[str, Any]:
    return {
        "name": name,
        "in": "query",
        "required": False,
        "description": description,
        "schema": {"type": "string", **schema},
    }


def table_parameters[R](spec: TableSpec[R]) -> dict[str, Any]:
    """`openapi_extra` için; yalnız şemaya girer."""
    columns = [column.key for column in spec.columns]
    parameters = [
        _parameter(SORT, "Sıralama sütunu", enum=columns),
        _parameter(DIRECTION, "Sıralama yönü", enum=["artan", "azalan"]),
        _parameter(
            SORT_SELECT,
            "Sütun ve yön birlikte",
            enum=[f"{key}.{d}" for key in columns for d in ("artan", "azalan")],
        ),
        _parameter(PAGE, "Sayfa (1'den başlar)", pattern="^[1-9][0-9]*$"),
    ]
    if spec.search is not None:
        parameters.append(_parameter(SEARCH, "Arama (İ, I, ı ve i aynı sayılır)"))
    if spec.day is not None:
        parameters.append(_parameter(FROM, "Başlangıç günü", format="date"))
        parameters.append(_parameter(TO, "Bitiş günü", format="date"))
    parameters.extend(_parameter(choice.key, choice.label) for choice in spec.choices)
    return {"parameters": parameters}
