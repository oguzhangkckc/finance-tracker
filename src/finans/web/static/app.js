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

  // Hedef toplamı canlı (K-127): yüzdeler virgüllü yazılır; toplam tam %100 değilse Önizle
  // kapanır ve fark yazılır. Hesap tam sayıyla yapılır, kayan nokta yuvarlaması karışmasın.
  // Asıl denetim sunucudadır; betik yokken form sunucunun hatasıyla döner.
  function percentParts(text) {
    var match = /^(\d+)(?:,(\d+))?$/.exec(text.trim());
    return match ? {whole: match[1], fraction: match[2] || ""} : null;
  }

  function percentText(value, places) {
    var digits = value.toString();
    while (digits.length <= places) {
      digits = "0" + digits;
    }
    var whole = places ? digits.slice(0, digits.length - places) : digits;
    var fraction = places ? digits.slice(digits.length - places).replace(/0+$/, "") : "";
    return fraction ? whole + "," + fraction : whole;
  }

  function targetTotal(inputs) {
    var output = document.getElementById("hedef-toplam");
    var button = document.getElementById("onizle");
    if (!output) {
      return;
    }
    function show(text, exact) {
      output.textContent = text;
      output.classList.toggle("off", !exact);
      if (button) {
        button.disabled = !exact;
      }
    }
    function update() {
      var parts = [];
      var places = 0;
      for (var i = 0; i < inputs.length; i += 1) {
        var part = percentParts(inputs[i].value);
        if (!part) {
          show("Toplam hesaplanamadı: her alan virgüllü bir sayı olmalı (ör. 17,5).", false);
          return;
        }
        parts.push(part);
        places = Math.max(places, part.fraction.length);
      }
      var scale = BigInt(1);
      for (var j = 0; j < places; j += 1) {
        scale *= BigInt(10);
      }
      var total = BigInt(0);
      parts.forEach(function (part) {
        var fraction = part.fraction;
        while (fraction.length < places) {
          fraction += "0";
        }
        total += BigInt(part.whole + fraction);
      });
      var hundred = BigInt(100) * scale;
      if (total === hundred) {
        show("Toplam %100", true);
        return;
      }
      var gap = total < hundred ? hundred - total : total - hundred;
      var word = total < hundred ? " eksik" : " fazla";
      show("Toplam %" + percentText(total, places) + " · %" + percentText(gap, places) + word, false);
    }
    Array.prototype.forEach.call(inputs, function (input) {
      input.addEventListener("input", update);
    });
    update();
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
  var targets = document.querySelectorAll("input[data-hedef]");
  if (targets.length) {
    targetTotal(targets);
  }
})();
