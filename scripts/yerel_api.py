"""Yerel geliştirmede API ve Access jetonu (K-139).

Kimlik doğrulaması burada da kapatılmaz: API her isteğin jetonunu doğrular, ama yalnız bu
betiğin o çalıştırmada ürettiği anahtara güvenir. Jeton git dışındaki frontend/.env.local'a
yazılır; Vite'ın vekili onu isteklere ekler ve kökeni API'nin beklediğine çevirir.

Kullanım (depo kökünden): make yerel; ardından frontend/ içinde npm run dev.
"""

import argparse
import json
import os
import secrets
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pydantic import SecretStr

from finans import bootstrap
from finans.api.app import create_app
from finans.settings import ApiSettings, load_base_settings

ROOT: Final = Path(__file__).resolve().parents[1]
ENV_FILE: Final = ROOT / "frontend" / ".env.local"
DIST: Final = ROOT / "frontend" / "dist"
HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8765
TEAM: Final = "yerel.cloudflareaccess.com"
AUDIENCE: Final = "yerel-gelistirme"
EMAIL: Final = "yerel@example.invalid"
ORIGIN: Final = "https://yerel.invalid"
KID: Final = "yerel"
LIFETIME: Final = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class LocalKeys:
    """Yalnız bu süreçte üretilen anahtarın açık yarısı; ağa çıkılmaz."""

    jwk: Mapping[str, object]

    def fetch(self) -> tuple[Mapping[str, object], ...]:
        return (self.jwk,)


@dataclass(frozen=True, slots=True)
class Launch:
    settings: ApiSettings
    keys: LocalKeys
    token: str


def prepare(port: int, now: datetime) -> Launch:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = {
        **json.loads(RSAAlgorithm.to_jwk(key.public_key())),
        "kid": KID,
        "alg": "RS256",
        "use": "sig",
    }
    settings = ApiSettings(
        host=HOST,
        port=port,
        team_domain=TEAM,
        audience=AUDIENCE,
        allowed_email=EMAIL,
        origin=ORIGIN,
        confirm_key=SecretStr(secrets.token_urlsafe(48)),
        dist=DIST,
    )
    issued = int(now.timestamp())
    claims = {
        "aud": AUDIENCE,
        "iss": settings.issuer,
        "email": EMAIL,
        "iat": issued,
        "nbf": issued,
        "exp": issued + int(LIFETIME.total_seconds()),
    }
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": KID})
    return Launch(settings, LocalKeys(jwk), token)


def write_env(launch: Launch, path: Path) -> None:
    """Jeton git dışında ve yalnız sahibine okunur; süresi bitince betik yeniden çalıştırılır."""
    text = (
        "# scripts/yerel_api.py yazar; git dışıdır ve 24 saat geçerlidir (K-139).\n"
        f"FT_YEREL_API=http://{HOST}:{launch.settings.port}\n"
        f"FT_YEREL_KOKEN={ORIGIN}\n"
        f"FT_YEREL_JETON={launch.token}\n"
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    # Dosya önceden varsa os.open izinleri değiştirmez.
    path.chmod(0o600)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Yerel geliştirmede finans-api (K-139).")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    settings = load_base_settings()
    launch = prepare(args.port, bootstrap.system_clock().now())
    write_env(launch, ENV_FILE)
    sys.stdout.write(
        f"API http://{HOST}:{args.port} adresinde; jeton {ENV_FILE} dosyasında.\n"
        "Arayüz için frontend/ içinde: npm run dev (derlenmiş paket için: npm run preview)\n"
    )
    config = uvicorn.Config(
        create_app(settings, launch.settings, keys=launch.keys),
        host=HOST,
        port=args.port,
        proxy_headers=False,
        server_header=False,
        lifespan="on",
    )
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
