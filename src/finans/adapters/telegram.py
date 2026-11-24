from finans.adapters._http import HttpClient
from finans.ports.notifier import NotifyError
from finans.ports.sources import SourceError

LIMIT = 4096


def split_message(text: str, limit: int = LIMIT) -> list[str]:
    """Telegram'ın karakter sınırı: önce bölüm, sonra satır sınırından, en son uzunluktan böler."""
    pieces = [piece for section in text.split("\n\n") for piece in _fit_lines(section, limit)]
    return _pack(pieces, "\n\n", limit)


def _fit_lines(block: str, limit: int) -> list[str]:
    if len(block) <= limit:
        return [block]
    chunks = [
        line[start : start + limit]
        for line in block.split("\n")
        for start in range(0, max(len(line), 1), limit)
    ]
    return _pack(chunks, "\n", limit)


def _pack(pieces: list[str], separator: str, limit: int) -> list[str]:
    parts: list[str] = []
    current: str | None = None
    for piece in pieces:
        if current is None:
            current = piece
        elif len(current) + len(separator) + len(piece) <= limit:
            current = f"{current}{separator}{piece}"
        else:
            parts.append(current)
            current = piece
    if current is not None:
        parts.append(current)
    return parts


class TelegramNotifier:
    """Rapor botu yalnızca gönderir (getUpdates yok) ve yalnızca kendi sohbetine yazar (K-22)."""

    def __init__(
        self,
        http: HttpClient,
        *,
        token: str,
        chat_id: str,
        base_url: str,
        prefix: str | None = None,
    ) -> None:
        self._http = http
        self._prefix = prefix
        self._url = f"{base_url.rstrip('/')}/bot{token}/sendMessage"
        self._chat_id = chat_id

    def send(self, text: str, *, silent: bool) -> None:
        if self._prefix is not None:
            text = f"{self._prefix}\n\n{text}"
        for part in split_message(text):
            payload = {
                "chat_id": self._chat_id,
                "text": part,
                "parse_mode": "HTML",
                "disable_notification": silent,
                "link_preview_options": {"is_disabled": True},
            }
            try:
                response = self._http.post_json(self._url, payload)
            except SourceError as exc:
                raise NotifyError(f"Telegram mesajı gönderilemedi: {exc}") from exc
            data = response.data
            if not isinstance(data, dict) or data.get("ok") is not True:
                reason = data.get("description") if isinstance(data, dict) else None
                raise NotifyError(f"Telegram mesajı reddetti: {reason or 'beklenmeyen yanıt'}")
