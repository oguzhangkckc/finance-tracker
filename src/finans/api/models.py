"""API'ye özgü modeller (K-138): alan adları İngilizce, Decimal kanonik metin."""

from decimal import Decimal
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, WithJsonSchema

from finans.domain.numeric import canonical_text
from finans.sunum.profiles import ProfileSlug

# K-52: üstel gösterim, sondaki sıfır ve -0 yok.
CANONICAL_DECIMAL: Final = r"^(0|-?(0\.[0-9]*[1-9]|[1-9][0-9]*(\.[0-9]*[1-9])?))$"
DecimalStr = Annotated[
    Decimal,
    PlainSerializer(canonical_text, return_type=str),
    WithJsonSchema({"type": "string", "pattern": CANONICAL_DECIMAL}),
]


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ErrorBody(Model):
    error: str
    fields: dict[str, str] = Field(default_factory=dict)


class Health(Model):
    status: Literal["ok"]


class ProfileLink(Model):
    slug: ProfileSlug
    label: str


class Session(Model):
    email: str
    profiles: list[ProfileLink]
    default_profile: ProfileSlug


ERROR_RESPONSES: Final[dict[int | str, dict[str, object]]] = {
    403: {"model": ErrorBody, "description": "Erişim reddedildi"},
    422: {"model": ErrorBody, "description": "Girdi geçersiz"},
}
