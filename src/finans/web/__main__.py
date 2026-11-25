import sys

import uvicorn
from pydantic import ValidationError

from finans import bootstrap
from finans.settings import load_base_settings
from finans.web.app import WebSetupError, create_app


def main() -> None:
    """Yalnızca hazır Unix soketinde dinler; TCP portu açılmaz (K-101, K-123)."""
    try:
        # K-125: iki profil birlikte sunulur; FT_PROFILE yalnız açılış profilini seçer.
        settings = load_base_settings()
        app = create_app(settings)
    except (ValidationError, WebSetupError) as exc:
        message = str(exc) if isinstance(exc, WebSetupError) else "Ayarlar eksik ya da geçersiz."
        sys.stderr.write(f"finans-web başlamadı: {message}\n")
        raise SystemExit(2) from exc
    bootstrap.configure_logging(settings)
    listener = bootstrap.web_listener(settings)
    config = uvicorn.Config(
        app,
        proxy_headers=False,
        server_header=False,
        access_log=False,
        log_config=None,
        lifespan="off",
    )
    uvicorn.Server(config).run(sockets=[listener])


if __name__ == "__main__":
    main()
