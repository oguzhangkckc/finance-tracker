"""app.js yalnız kolaylıktır (K-129); davranışı başsız Chrome'da, uygulamanın ürettiği gerçek
sayfalar üzerinde denetlenir. Chrome yoksa atlanır; JavaScript kapalıyken akışları öbür web
testleri zaten denetler (test istemcisi betik çalıştırmaz)."""

import html
import json
import os
import re
import shutil
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.domain.models import Side, Transaction
from finans.domain.settings import SettingVersion
from tests.support.web_writes import NOW, REAL_BUY, Site, post_preview, start_settings

STATIC = Path(__file__).parents[2] / "src" / "finans" / "web" / "static"
_CANDIDATES = (
    os.environ.get("CHROME", ""),
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


def _chrome() -> str | None:
    for candidate in _CANDIDATES:
        found = shutil.which(candidate) if candidate else None
        if found or (candidate and Path(candidate).is_file()):
            return found or candidate
    return None


def missing_chrome(ci: str | None) -> Literal["skip", "fail"]:
    """Yerelde atlanır; CI'da Chrome yoksa test başarısız olur, kurulum sorunu testleri
    sessizce devre dışı bırakamaz."""
    return "fail" if ci else "skip"


CHROME = _chrome()
DESKTOP, PHONE = 1280, 390


@pytest.fixture
def chrome() -> str:
    if CHROME is None:
        if missing_chrome(os.environ.get("CI")) == "fail":
            pytest.fail("CI'da Chrome bulunamadı; app.js testleri atlanamaz")
        pytest.skip("Chrome yok; app.js yerelde denetlenemedi")
    return CHROME


# Yalnız teste ait ölçüm betiği; uygulamaya girmez. Sonuç JSON olarak sayfaya yazılır.
HARNESS = r"""
window.addEventListener("load", function () {
  var out = {};
  var shown = function (el) {
    return !!el && !el.hidden && getComputedStyle(el).display !== "none";
  };
  var input = document.getElementById("ara");
  if (input && input.hasAttribute("data-suz")) {
    var rows = Array.prototype.slice.call(document.querySelectorAll("#tablo tbody tr"));
    var visible = function () { return rows.filter(shown).length; };
    var type = function (text) {
      input.value = text;
      input.dispatchEvent(new Event("input", {bubbles: true}));
    };
    out.hint = shown(document.getElementById("ara-ipucu"));
    out.rows = visible();
    type("xh");
    out.xh = visible();
    out.emptyAfterXh = shown(document.getElementById("ara-bos"));
    type("ZZZ");
    out.zzz = visible();
    out.emptyAfterZzz = shown(document.getElementById("ara-bos"));
    type("");
    out.cleared = visible();
  }
  var total = document.getElementById("hedef-toplam");
  if (total) {
    var targets = Array.prototype.slice.call(document.querySelectorAll("input[data-hedef]"));
    var preview = document.getElementById("onizle");
    var fill = function (values) {
      values.forEach(function (value, i) {
        targets[i].value = value;
        targets[i].dispatchEvent(new Event("input", {bubbles: true}));
      });
      return [total.textContent, preview.disabled];
    };
    out.totals = [[total.textContent, preview.disabled]];
    out.totals.push(fill(["60", "37,5"]));
    out.totals.push(fill(["62,5", "37,5"]));
    out.totals.push(fill(["70", "40,25"]));
    out.totals.push(fill(["6.5", "40"]));
    out.totals.push(fill(["0,1", "99,9"]));
  }
  var sort = document.getElementById("siralama");
  if (sort) {
    var sent = 0;
    sort.form.requestSubmit = function () { sent += 1; };
    sort.form.submit = function () { sent += 1; };
    sort.selectedIndex = 1;
    sort.dispatchEvent(new Event("change", {bubbles: true}));
    out.sortSubmits = sent;
    var other = document.getElementById("f-tur");
    other.selectedIndex = 1;
    other.dispatchEvent(new Event("change", {bubbles: true}));
    out.filterSubmits = sent - out.sortSubmits;
  }
  var post = document.querySelector('form[method="post"]');
  var get = document.querySelector('form[method="get"]');
  var buttons = function (form) {
    return Array.prototype.slice.call(form.querySelectorAll("button"));
  };
  if (post) {
    post.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}));
    if (get) { get.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true})); }
    setTimeout(function () {
      out.postDisabled = buttons(post).every(function (b) { return b.disabled; });
      out.getEnabled = !get || buttons(get).every(function (b) { return !b.disabled; });
      window.dispatchEvent(new PageTransitionEvent("pageshow", {persisted: false}));
      out.stillDisabledOnFreshLoad = buttons(post).every(function (b) { return b.disabled; });
      window.dispatchEvent(new PageTransitionEvent("pageshow", {persisted: true}));
      out.enabledFromCache = buttons(post).every(function (b) { return !b.disabled; });
      document.getElementById("sonuc").textContent = JSON.stringify(out);
    }, 50);
    return;
  }
  document.getElementById("sonuc").textContent = JSON.stringify(out);
});
"""


# Yalnız teste ait: masaüstü tablosunda dar sütunlardaki her kelime tek satırda mı. Ekran okuyucu
# metni (`.sr`, 1 piksel) ve uzun serbest metin sütunları (`.wrap`) sayılmaz.
WORDS = r"""
window.addEventListener("load", function () {
  var broken = [];
  var cells = document.querySelectorAll("table.cards th, table.cards td:not(.wrap)");
  Array.prototype.forEach.call(cells, function (cell) {
    var walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
    var node;
    while ((node = walker.nextNode())) {
      if (node.parentElement.closest(".sr")) { continue; }
      var words = /\S+/g;
      var match;
      while ((match = words.exec(node.data))) {
        var range = document.createRange();
        range.setStart(node, match.index);
        range.setEnd(node, match.index + match[0].length);
        var lines = {};
        Array.prototype.forEach.call(range.getClientRects(), function (rect) {
          if (rect.width > 0) { lines[Math.round(rect.top)] = true; }
        });
        if (Object.keys(lines).length > 1) { broken.push(match[0]); }
      }
    }
  });
  var overflow = document.documentElement.scrollWidth > window.innerWidth;
  var out = {broken: broken, overflow: overflow};
  document.getElementById("sonuc").textContent = JSON.stringify(out);
});
"""


def _run(
    chrome: str, page: str, tmp_path: Path, width: int, harness: str = HARNESS
) -> dict[str, object]:
    script = re.compile(r'<script src="/static/app\.[0-9a-f]{12}\.js" defer></script>')
    assert script.search(page), "sayfa app.js'i yüklemiyor"
    style = re.compile(r'<link rel="stylesheet" href="/static/site\.[0-9a-f]{12}\.css">')
    assert style.search(page), "sayfa site.css'i yüklemiyor"
    local = script.sub('<script src="app.js" defer></script>', page)
    local = style.sub('<link rel="stylesheet" href="site.css">', local)
    local = local.replace(
        "</body>", '<pre id="sonuc"></pre><script src="harness.js" defer></script></body>'
    )
    shutil.copy(STATIC / "app.js", tmp_path / "app.js")
    shutil.copy(STATIC / "site.css", tmp_path / "site.css")
    (tmp_path / "harness.js").write_text(harness, encoding="utf-8")
    (tmp_path / "page.html").write_text(local, encoding="utf-8")
    command = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        f"--user-data-dir={tmp_path / 'profil'}",
        f"--window-size={width},900",
        "--virtual-time-budget=5000",
        "--dump-dom",
        (tmp_path / "page.html").as_uri(),
    ]
    # CI çalıştırıcısında (Ubuntu 24.04, AppArmor) Chrome'un kum havuzu açılmayabilir; açılan
    # yalnız bu testin yerel dosyasıdır.
    if os.environ.get("CI") or (hasattr(os, "geteuid") and os.geteuid() == 0):
        command.insert(1, "--no-sandbox")
    result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)  # noqa: S603 - sabit argümanlarla yerel Chrome
    found = re.search(r'<pre id="sonuc">(.*?)</pre>', result.stdout, re.S)
    assert found is not None, result.stderr[-2000:]
    assert found.group(1), result.stderr[-2000:]
    return dict(json.loads(html.unescape(found.group(1))))


def test_the_search_box_filters_this_page_and_says_so(
    site: Site, tmp_path: Path, chrome: str
) -> None:
    page = site.browser().get("/gercek/islemler").text

    out = _run(chrome, page, tmp_path, DESKTOP)

    assert out == {
        "hint": True,
        "rows": 4,
        "xh": 2,
        "emptyAfterXh": False,
        "zzz": 0,
        "emptyAfterZzz": True,
        "cleared": 4,
        "sortSubmits": 1,
        "filterSubmits": 0,
    }


def test_only_the_sort_box_on_a_desktop_submits_by_itself(
    site: Site, tmp_path: Path, chrome: str
) -> None:
    page = site.browser().get("/gercek/islemler").text

    out = _run(chrome, page, tmp_path, PHONE)

    assert (out["sortSubmits"], out["filterSubmits"]) == (0, 0)


def test_a_disabled_button_comes_back_when_the_page_returns_from_the_cache(
    site: Site, tmp_path: Path, chrome: str
) -> None:
    me = site.browser()
    preview = post_preview(me, "real", "alis", REAL_BUY).text

    out = _run(chrome, preview, tmp_path, DESKTOP)

    assert out == {
        "postDisabled": True,
        "getEnabled": True,
        "stillDisabledOnFreshLoad": True,
        "enabledFromCache": True,
    }


def test_without_javascript_the_hint_and_empty_note_stay_hidden(site: Site) -> None:
    page = site.browser().get("/gercek/islemler").text

    assert '<p class="hint" id="ara-ipucu" hidden>' in page
    assert '<p class="note" id="ara-bos" role="status" hidden>' in page
    assert re.search(r"\son[a-z]+=", page) is None


@pytest.mark.parametrize(("ci", "action"), [(None, "skip"), ("", "skip"), ("true", "fail")])
def test_a_missing_chrome_fails_on_ci_and_is_skipped_only_locally(
    ci: str | None, action: str
) -> None:
    assert missing_chrome(ci) == action


def test_the_target_total_is_live_and_previewing_waits_for_exactly_one_hundred(
    site: Site, tmp_path: Path, chrome: str
) -> None:
    start_settings(site.settings)
    page = site.browser().get("/gercek/ayarlar/yeni").text

    out = _run(chrome, page, tmp_path, PHONE)

    assert out["totals"] == [
        ["Toplam %100", False],
        ["Toplam %97,5 · %2,5 eksik", True],
        ["Toplam %100", False],
        ["Toplam %110,25 · %10,25 fazla", True],
        ["Toplam hesaplanamadı: her alan virgüllü bir sayı olmalı (ör. 17,5).", True],
        ["Toplam %100", False],
    ]


@pytest.mark.parametrize("width", [800, 1024, 1470])
@pytest.mark.parametrize("page_path", ["/gercek/islemler", "/gercek/ayarlar"])
def test_desktop_tables_never_break_a_word_in_a_narrow_column(
    site: Site, tmp_path: Path, chrome: str, page_path: str, width: int
) -> None:
    """Uzun not ya da değişiklik metni yalnız kendi sütununda kırılır; iki haneli işlem numarası,
    "alış", "geçerli" ve "portfolio.toml" gibi kısa değerler harf harf bölünmez."""
    start_settings(site.settings)
    conf = site.conf("real")
    with SqliteUnitOfWork(conf.db_path) as uow:
        for day in range(16, 28):
            trade = Transaction(
                "XHT", date(2026, 11, day), Side.BUY, Decimal(732), Decimal("1.48181")
            )
            note = f"sanal-maas-gunu:2026-11-{day}:XHT"
            uow.transactions.add(trade, external_ref=None, note=note, created_at=NOW)
        targets = {"hisse": Decimal("0.7"), "dusuk_risk": Decimal("0.3")}
        planned = SettingVersion(date(2027, 1, 1), 20, Decimal(1500), targets)
        uow.settings.add(planned, source="web", at=NOW)
    page = site.browser().get(page_path).text

    out = _run(chrome, page, tmp_path, width, harness=WORDS)

    assert out == {"broken": [], "overflow": False}
