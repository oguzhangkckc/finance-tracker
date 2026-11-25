// finans-takip: isteğe bağlı kolaylıklar (K-129). Betik yokken her akış aynen çalışır;
// satır içi betik ve olay işleyici yoktur (CSP: script-src 'self').
(function () {
  "use strict";

  // Sunucudaki arama gibi gevşek: İ, I, ı ve i aynı sayılır.
  function fold(text) {
    return text.replace(/[İIı]/g, "i").toLowerCase();
  }

  // Anında süzme yalnız bu sayfadaki satırlara bakar; ipucu ve boş sonuç bunu açıkça söyler,
  // Enter tüm kayıtlarda sunucu araması yapar.
  function filterRows(input) {
    var table = document.getElementById(input.getAttribute("data-suz"));
    var hint = document.getElementById(input.id + "-ipucu");
    var empty = document.getElementById(input.id + "-bos");
    if (!table) {
      return;
    }
    var rows = table.querySelectorAll("tbody tr[data-ara]");
    if (hint) {
      hint.hidden = false;
    }
    input.addEventListener("input", function () {
      var needle = fold(input.value.trim());
      var shown = 0;
      Array.prototype.forEach.call(rows, function (row) {
        var match = needle === "" || fold(row.getAttribute("data-ara")).indexOf(needle) !== -1;
        row.hidden = !match;
        if (match) {
          shown += 1;
        }
      });
      if (empty) {
        empty.hidden = shown !== 0;
      }
    });
  }

  // Yalnız masaüstünde ve yalnız sıralama kutusu kendiliğinden gönderilir; telefondaki
  // filtre bölümünde birkaç seçim yapılıp "Uygula" ile tek seferde gönderilir.
  var desktop = window.matchMedia("(min-width: 60rem)");

  function autoSubmit(select) {
    select.addEventListener("change", function () {
      var form = select.form;
      if (!desktop.matches || !form) {
        return;
      }
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
      } else {
        form.submit();
      }
    });
  }

  // Gönderilen POST formunun düğmeleri kapanır; çift kaydı asıl engelleyen sunucudaki
  // nonce'tur (K-126). Düğmeler form verisi toplandıktan sonra kapanır ve sayfa geri/ileri
  // önbelleğinden dönünce yeniden açılır, yoksa kullanıcı kapalı bir formla kalırdı.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (event.defaultPrevented || !(form instanceof HTMLFormElement)) {
      return;
    }
    if (form.method.toLowerCase() !== "post") {
      return;
    }
    window.setTimeout(function () {
      Array.prototype.forEach.call(form.querySelectorAll("button"), function (button) {
        if (!button.disabled) {
          button.disabled = true;
          button.setAttribute("data-kapatildi", "");
        }
      });
    }, 0);
  });

  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) {
      return;
    }
    Array.prototype.forEach.call(
      document.querySelectorAll("button[data-kapatildi]"),
      function (button) {
        button.disabled = false;
        button.removeAttribute("data-kapatildi");
      }
    );
  });

  Array.prototype.forEach.call(document.querySelectorAll("input[data-suz]"), filterRows);
  Array.prototype.forEach.call(document.querySelectorAll("select[data-otomatik]"), autoSubmit);
})();
