"""Deploy kullanıcısının zorunlu komutu (K-133). finans paketini import etmez; CI'da Pi'nin sistem
Python'u olan 3.12 ile de çalışır (`--confcutdir=tests/deploy_ci`)."""

import fcntl
import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

import istek

SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def paths(tmp_path: Path) -> istek.Yollar:
    (tmp_path / "istek").mkdir()
    (tmp_path / "sonuc").mkdir()
    return istek.Yollar(
        istek=tmp_path / "istek" / "deploy.request",
        sonuc=tmp_path / "sonuc",
        kilit=tmp_path / "sonuc" / "kur.lock",
    )


def _result(paths: istek.Yollar, ident: str, code: int, message: str) -> None:
    data = {"kod": code, "mesaj": message}
    (paths.sonuc / f"{ident}.json").write_text(json.dumps(data), encoding="utf-8")


def test_only_deploy_and_a_full_lowercase_sha_is_accepted() -> None:
    assert istek.requested_sha(f"deploy {SHA}") == SHA


@pytest.mark.parametrize(
    "command",
    [
        None,
        "",
        "deploy",
        f"deploy {SHA.upper()}",
        f"deploy {SHA[:-1]}",
        f"deploy {SHA}0",
        f"deploy {SHA}\n",
        f" deploy {SHA}",
        f"deploy  {SHA}",
        f"deploy {SHA} --force",
        f"deploy {SHA};id",
        f"deploy $(id){SHA[5:]}",
        f"DEPLOY {SHA}",
        "deploy " + "\u0660" * 40,
        "ls",
    ],
)
def test_anything_else_is_refused_and_no_request_is_left(
    paths: istek.Yollar, command: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    environ = {} if command is None else {"SSH_ORIGINAL_COMMAND": command}

    code = istek.main(environ, paths, lambda _p, _i: (istek.Kod.TAMAM, "beklenmedi"))

    assert code == istek.Kod.RET
    assert capsys.readouterr().out == istek.REFUSED + "\n"
    assert list(paths.istek.parent.iterdir()) == []


def test_a_request_is_left_atomically_with_its_own_id_and_the_result_is_returned(
    paths: istek.Yollar, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[str] = []

    def runner(given: istek.Yollar, ident: str) -> tuple[istek.Kod, str]:
        seen.append(given.istek.read_text(encoding="ascii"))
        mode = stat.S_IMODE(os.stat(given.istek).st_mode)
        assert mode == istek.REQUEST_MODE
        assert [p.name for p in given.istek.parent.iterdir()] == ["deploy.request"]
        return istek.Kod.ELLE_KURULUM, f"⚠ Elle kurulum gerekiyor ({ident[:4]})"

    code = istek.main({"SSH_ORIGINAL_COMMAND": f"deploy {SHA}"}, paths, runner)

    sha, ident = seen[0].splitlines()
    assert (code, sha, len(ident)) == (istek.Kod.ELLE_KURULUM, SHA, 32)
    assert capsys.readouterr().out == f"⚠ Elle kurulum gerekiyor ({ident[:4]})\n"


def test_a_waiting_request_makes_the_next_one_busy(
    paths: istek.Yollar, capsys: pytest.CaptureFixture[str]
) -> None:
    paths.istek.write_text(f"{SHA}\n{'a' * 32}\n", encoding="ascii")

    code = istek.main({"SSH_ORIGINAL_COMMAND": f"deploy {SHA}"}, paths)

    assert code == istek.Kod.MESGUL
    assert capsys.readouterr().out == istek.BUSY + "\n"
    assert paths.istek.read_text(encoding="ascii") == f"{SHA}\n{'a' * 32}\n"


@pytest.fixture
def running(paths: istek.Yollar) -> Iterator[None]:
    """Çalıştırıcı çalışırken kilidi özel olarak tutar."""
    fd = os.open(paths.kilit, os.O_RDWR | os.O_CREAT, 0o640)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        yield
    finally:
        os.close(fd)


@pytest.mark.usefixtures("running")
def test_a_running_deploy_makes_a_new_request_busy(paths: istek.Yollar) -> None:
    code = istek.main({"SSH_ORIGINAL_COMMAND": f"deploy {SHA}"}, paths)

    assert code == istek.Kod.MESGUL
    assert not paths.istek.exists()


def test_a_free_lock_file_does_not_make_it_busy(paths: istek.Yollar) -> None:
    paths.kilit.write_bytes(b"")

    assert not istek.busy(paths)


def test_two_requests_at_once_leave_one_and_the_second_is_refused(paths: istek.Yollar) -> None:
    istek.leave_request(paths, SHA, "a" * 32)

    with pytest.raises(FileExistsError):
        istek.leave_request(paths, SHA, "b" * 32)

    assert paths.istek.read_text(encoding="ascii") == f"{SHA}\n{'a' * 32}\n"
    assert [p.name for p in paths.istek.parent.iterdir()] == ["deploy.request"]


def test_only_this_requests_result_is_read_not_an_older_one(paths: istek.Yollar) -> None:
    _result(paths, "e" * 32, 0, "eski çalışmanın sonucu")
    ticks = iter(range(100))
    waited: list[float] = []

    def sleep(seconds: float) -> None:
        waited.append(seconds)
        if len(waited) == 3:
            _result(paths, "f" * 32, 1, "❌ başarısız; geri dönüldü")

    result = istek.wait_result(
        paths, "f" * 32, timeout=60, poll=2, sleep=sleep, now=lambda: float(next(ticks))
    )

    assert result == (istek.Kod.BASARISIZ, "❌ başarısız; geri dönüldü")
    assert waited == [2, 2, 2]


def test_no_result_within_the_time_limit_is_reported_as_unknown(paths: istek.Yollar) -> None:
    clock = iter([0.0, 0.0, 600.0, 1200.0])

    code, message = istek.wait_result(
        paths, "f" * 32, sleep=lambda _s: None, now=lambda: next(clock)
    )

    assert code == istek.Kod.BASARISIZ
    assert message.startswith("Sonuç 20 dakikada gelmedi; durum bilinmiyor.")


@pytest.mark.parametrize(
    "content", ["{bozuk", '{"kod": 9, "mesaj": "x"}', '{"mesaj": "kod yok"}', "[]"]
)
def test_an_unreadable_result_is_a_failure(paths: istek.Yollar, content: str) -> None:
    (paths.sonuc / f"{'f' * 32}.json").write_text(content, encoding="utf-8")

    assert istek.wait_result(paths, "f" * 32, sleep=lambda _s: None) == (
        istek.Kod.BASARISIZ,
        istek.UNREADABLE,
    )


def test_a_request_appearing_at_the_same_moment_makes_this_one_busy(
    paths: istek.Yollar, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def racing(_paths: istek.Yollar, _sha: str, _ident: str) -> None:
        raise FileExistsError

    monkeypatch.setattr(istek, "leave_request", racing)

    code = istek.main({"SSH_ORIGINAL_COMMAND": f"deploy {SHA}"}, paths)

    assert code == istek.Kod.MESGUL
    assert capsys.readouterr().out == istek.BUSY + "\n"
