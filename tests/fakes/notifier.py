from dataclasses import dataclass, field

from finans.ports.notifier import NotifyError


@dataclass
class FakeNotifier:
    fail: bool = False
    sent: list[tuple[str, bool]] = field(default_factory=list)

    def send(self, text: str, *, silent: bool) -> None:
        if self.fail:
            raise NotifyError("Telegram mesajı gönderilemedi: deneme hatası")
        self.sent.append((text, silent))
