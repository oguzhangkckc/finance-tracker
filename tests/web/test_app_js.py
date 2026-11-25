"""app.js yalnız kolaylıktır (K-129); davranışı başsız Chrome'da, uygulamanın ürettiği gerçek
sayfalar üzerinde denetlenir. Chrome yoksa atlanır; JavaScript kapalıyken akışları öbür web
testleri zaten denetler (test istemcisi betik çalıştırmaz)."""

import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.support.web_writes import REAL_BUY, Site, post_preview

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


CHROME = _chrome()
pytestmark = pytest.mark.skipif(CHROME is None, reason="Chrome yok; app.js denetlenemedi")
DESKTOP, PHONE = 1280, 390

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


def _run(page: str, tmp_path: Path, width: int) -> dict[str, object]:
    script = re.compile(r'<script src="/static/app\.[0-9a-f]{12}\.js" defer></script>')
    assert script.search(page), "sayfa app.js'i yüklemiyor"
    local = script.sub('<script src="app.js" defer></script>', page)
    local = local.replace(
        "</body>", '<pre id="sonuc"></pre><script src="harness.js" defer></script></body>'
    )
    shutil.copy(STATIC / "app.js", tmp_path / "app.js")
    (tmp_path / "harness.js").write_text(HARNESS, encoding="utf-8")
    (tmp_path / "page.html").write_text(local, encoding="utf-8")
    command = [
        str(CHROME),
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


def test_the_search_box_filters_this_page_and_says_so(site: Site, tmp_path: Path) -> None:
    page = site.browser().get("/gercek/islemler").text

    out = _run(page, tmp_path, DESKTOP)

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


def test_only_the_sort_box_on_a_desktop_submits_by_itself(site: Site, tmp_path: Path) -> None:
    page = site.browser().get("/gercek/islemler").text

    out = _run(page, tmp_path, PHONE)

    assert (out["sortSubmits"], out["filterSubmits"]) == (0, 0)


def test_a_disabled_button_comes_back_when_the_page_returns_from_the_cache(
    site: Site, tmp_path: Path
) -> None:
    me = site.browser()
    preview = post_preview(me, "real", "alis", REAL_BUY).text

    out = _run(preview, tmp_path, DESKTOP)

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
