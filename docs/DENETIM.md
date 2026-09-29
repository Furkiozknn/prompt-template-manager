# Denetim: prompt-template-manager (30 Eylül 2026)

Yenilemeden önce `main` (0.1.0, `c505b51`) üzerinde, bu makinede (Windows 11, Python 3.12, uv 0.12.5, Git Bash) ölçüldü. Ölçülmeyen bir şey yazılmadı. Ham çıktılar depo dışında: `kanit/prompt-template-manager/{once,sonra}/komutlar.txt` (aynı 17 komut, iki sürüme karşı: `olc.py`).

## Temiz ortamda kurulum ve ilk sonuç

| Yol | Süre | Sonuç |
|---|---|---|
| `uvx --from git+https://github.com/Furkiozknn/prompt-template-manager ptm --version` (boş uv önbelleği) | 12,7 s ve 11,4 s (iki ayrı koşu; GitHub'dan çekip derliyor) | `ptm 0.1.0` |
| aynısı, önbellek sıcak | 3,5 s ve 3,1 s | aynı |
| `python -m venv` + `pip install git+https://...` | 15,6 s | çalıştı |
| `uv tool install git+https://...` (önbellek sıcak) | 2,4 s | `ptm` kuruldu |
| `ptm validate` / `ptm render` (kurulu) | 0,75-0,87 s (çoğu Python + Jinja içe aktarma) | |

"Tek komut, bir dakikada ilk sonuç" tutuyor: `uvx` ile kurulum + `validate` + `render` en kötü ölçümle 12,7 + 0,9 + 0,8 ≈ 15 s. `pipx` bu makinede kurulu değil, ölçülmedi. PyPI'de `ptm-cli` yok (README bunu zaten söylüyor).

## README komutları

| Komut | Sonuç |
|---|---|
| `uvx --from git+... ptm --help`, `uv tool install git+...` | çalıştı |
| `hello.yaml` örneği (`validate`, `render --pretty`) | çalıştı; çıktı README'deki gibi (`steps` tamsayı) |
| üç bilinçli hata (`render` eksik değişken, `--var subjcet=x`, `steps=many`) | üçü de tek satır `error:` ve çıkış 1 |
| `uv run ptm validate/render/info examples/product-photo.yaml` | çalıştı |
| `ptm submit ... --gateway-url http://127.0.0.1:1` | `error: could not reach gateway ...`, çıkış 1 (Türkçe Windows'ta `[WinError 10061]` metni Türkçe geliyor; kod değil işletim sistemi) |
| `python arac/vendor-dogrula.py` | `ayni` (gateway_poll.py kanonik kopyayla aynı) |
| `uv run python arac/terminal-svg.py` | çalıştı; Windows'ta yol ayracı `\` çıkıyor, CI (Linux) `/` üretiyor: SVG olduğu gibi bırakıldı |
| `uv sync --group dev` + `uv run pytest` | 150 geçti, 2,3 s (yenilemeden sonra 156) |

Sayılar: "150 tests" → koşudan 150 (uyuştu). Başka ölçülmüş sayı iddiası yok. README'nin güvenlik bölümündeki davranışlar (`{{ 10 ** (10 ** 9) }}`, takma ad bombası) `tests/test_untrusted_input.py` içinde sınanıyor.

## Hata mesajları ve `--help`

Çıkış kodları hep doğruydu (kullanım hatası 2, şablon/ağ hatası 1, Ctrl+C 130). Sorun sözlerdeydi:

| Girdi | Önce | Sorun |
|---|---|---|
| `ptm validate <klasör>` / `ptm render <klasör>` | `cannot read file klasor: Permission denied` | Windows'ta klasör açmak "izin yok" diyor; asıl sorun (klasör verilmiş) söylenmiyor |
| bozuk YAML | 5 satır: `while parsing a flow node`, `in "<unicode string>", line 2, column 1:` + boş kaynak satırı ve `^` | `<unicode string>` şablon dosyası değil; kaynak satırı boş görünüyor |
| boş dosya | `must be a YAML mapping at the top level` | "boş" denmiyor |
| `ptm info`/`validate` cp1254 konsolunda, açıklamada `→` | **`UnicodeEncodeError` izi**, çıkış 1 | **Hata.** Türkçe Windows'ta şablon adı/açıklaması cp1254 dışı bir karakter içerince komut düşüyor (`render` etkilenmiyor: JSON ASCII) |
| `ptm` (komutsuz), `ptm renderr x`, `ptm render` | usage + hata | `--help`'e yönlendirme yok |
| `--help` | açıklama, bir örnek, çıkış kodları | alt komutların örneği yok; `render` `template` argümanının yardımı yok; `--var VAR` ne beklediğini söylemiyor |

Önce/sonra metinleri: `kanit/prompt-template-manager/once/`, `sonra/komutlar.txt`.

## README bulguları

- İlk ekran reel GIF'iydi (15 sn, sesli MP4); üreticisi depoda yok. `assets/demo.gif` (`validate` + `info`) de üreticisiz. İkisi README'den çıkarıldı (dosyalar diskte duruyor, üreticisiz oldukları için bağlanmadı); yerine gerçek çıktıdan üretilen `docs/demo/` konuldu.
- Kurulum ilk ekranın altındaydı, tanım iki paragrafın ardındaydı. Yeni sıra: tek cümle, tek komut, demo, ölçülmüş süre, "ne zaman kullanılır / kullanılmaz".
- Ekosistem denetimi (#19) bu depo için yalnız meta-source ayrışması bulgularını listeliyor (`project-meta.json` 150 test, `meta-source.json` 61; özet ve description ayrışması). Onlara dokunulmadı.

## Bulunan ve düzeltilen hatalar

1. cp1254 konsolunda `UnicodeEncodeError` (yukarıda): `main()` başında stdout/stderr `errors="replace"` (test: `test_unencodable_description_does_not_crash_on_a_cp1254_console`).
2. Klasörün "Permission denied" olarak bildirilmesi.
3. Bozuk YAML'ın çok satırlı, yanıltıcı dökümü.
4. Yardım metinleri ve kullanım hatasında yönlendirme yokluğu.

Çıkış kodları, çıktı sözleşmesi ve mevcut testler değişmedi (150 test aynen geçiyor; 6 test eklendi).
