# Proje kuralları

docs/DESIGN.md tek doğruluk kaynağıdır; alınmış kararlar oradaki "Karar kaydı" bölümündedir (K-xx). Milestone'lar ve kapıları docs/ROADMAP.md'dedir.

## Çalışma şekli

- Tasarımdan sapma gerekiyorsa önce DESIGN.md'yi (gerekirse karar kaydını) güncelle, sonra kodu.
- Her milestone ayrı branch ve ayrı PR. Önce plan (dosyalar, arayüzler, test listesi) sunulur; kod onaydan sonra yazılır.
- Commit ve push yalnızca kullanıcı istediğinde.
- Yeni bağımlılık eklemeden önce sor.
- Bitti tanımı: `make check` yeşil (ruff, mypy --strict, import-linter, pytest).
- Kontrol komutlarının (`make check`, pytest, ruff, mypy, lint-imports) çıktısı pipe'lanmaz. Çıktı gerekiyorsa dosyaya yazılır; çıkış kodu doğrudan kontrol edilir ve commit ya da push yalnızca 0 ise yapılır. `cmd | grep … && git commit` biçimi grep'in çıkış koduna baktığı için yasak.
- Push öncesinde pre-commit'in pre-push aşaması `make check`'i çalıştırır (`uv run pre-commit install` iki hook'u da kurar).
- Commit e-postası bu repoda GitHub noreply adresidir (`git config --local user.email`); genel (`--global`) Git ayarına dokunulmaz. Kişisel e-posta adresi hiçbir dosyaya yazılmaz.
- pre-push aşaması `make check`'ten önce `scripts/check_push_emails.py`'yi çalıştırır: uzakta olmayan her commit'in yazar ve committer e-postası noreply kalıbında değilse push durur ve düzeltme komutu gösterilir. Bu kontrol `--no-verify` ile atlanmaz.

## Kod kuralları

- Katman sırası: cli → bootstrap → settings → application | adapters → ports → contracts → domain. Kurallar pyproject.toml'daki import-linter kurallarıyla ve tests/arch ile zorlanır.
- domain yalnızca standart kütüphaneyi kullanır. Somut sınıflar yalnızca bootstrap.py'de bağlanır.
- Para, fiyat ve adet her yerde Decimal. `float` kaynak kodun hiçbir yerinde kullanılmaz.
- domain'deki public (alt çizgisiz) üst düzey fonksiyonlar `@in_domain_context` ile sarılır (28 basamak, FloatOperation trap'i); tests/arch bunu denetler.
- Duvar saatine yalnızca `adapters/clock.py` erişir; geri kalan her yer Clock port'unu kullanır. Mantıksal tarih (logical_date) dışarıdan verilir.
- Ağ ve SQLite erişimi yalnızca adapters altında. Testlerde gerçek ağ kapalıdır; gerçek ağa çıkan test `@pytest.mark.live` ile işaretlenir.
- adapters altına yeni bir modül ya da alt paket eklenince pyproject.toml'daki bağımsızlık kuralına da ekle; tests/arch bunu denetler.
- SQL içinde Decimal TEXT kolonlarla hesap, sıralama ya da sayısal karşılaştırma yapılmaz.
- Migration'lar `src/finans/adapters/sqlite/migrations/NNNN_ad.sql` biçimindedir. Yalnızca yeni dosya eklenir, uygulanmış dosya değiştirilmez. Migration dosyası BEGIN/COMMIT içermez; transaction'ı çalıştırıcı yönetir.
- Sırlar log'a, hata metnine, job_run.detail'e ve LLM bağlamına yazılmaz.
- Domain kodu test-önce yazılır; referans değerler testte açıkça yazılır.
