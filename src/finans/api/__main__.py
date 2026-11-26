import sys

import uvicorn
from pydantic import ValidationError

from finans import bootstrap
from finans.api.app import create_app
from finans.settings import ApiSettingsError, api_settings, load_base_settings


def main() -> None:
    """Yalnız loopback adresinde dinler; önünde Cloudflare tüneli ve Access vardır (K-136)."""
    try:
        # K-125: iki profil birlikte sunulur; FT_PROFILE yalnız açılış profilini seçer.
        settings = load_base_settings()
        api = api_settings(settings)
    except (ValidationError, ApiSettingsError) as exc:
        message = str(exc) if isinstance(exc, ApiSettingsError) else "Ayarlar eksik ya da geçersiz."
        sys.stderr.write(f"finans-api başlamadı: {message}\n")
        raise SystemExit(2) from exc
    bootstrap.configure_logging(settings)
    config = uvicorn.Config(
        create_app(settings, api),
        host=api.host,
        port=api.port,
        proxy_headers=False,
        server_header=False,
        access_log=False,
        log_config=None,
        lifespan="on",
    )
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
