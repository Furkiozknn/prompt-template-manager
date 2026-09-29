# Tasarım: ptm ilk kullanım ve README yenilemesi (30 Eylül 2026)

## Hedef

Videodan ya da profilden gelen biri ilk dakikada şunu yapabilmeli: aracın ne yaptığını tek cümlede anlamak, tek komutla çalıştırmak, gerçek bir şablonda `validate` ve `render` görmek; yanlış yazarsa hatanın ne olduğunu ve nereye bakacağını tek satırda okumak. Çekirdek davranış (şablon biçimi, sandbox, tip dönüşümü, çıkış kodları, `submit` sözleşmesi) değişmedi; sürüm numarası artmadı (0.1.0).

## Önce / sonra

| Konu | Önce | Sonra |
|---|---|---|
| README ilk ekranı | banner, 15 sn'lik sesli reel, slogan, iki cümlelik tanım, üreticisiz `demo.gif`; kurulum ve ilk şablon altta | banner, slogan, tek cümlelik tanım, tek komutlu `uvx`, 21 sn gerçek çıktılı demo, ölçülmüş süre, "ne zaman kullanılır / kullanılmaz" tablosu, sonra eski gövde |
| Demo | kaynağı depoda olmayan reel/GIF | `arac/demo-uret.py`: 5 komut gerçekten koşulur, `docs/demo/komutlar.txt` kayıttır, sayfa o kaydı yazma animasyonuyla oynatır; `arac/demo-kayit.js` mp4/gif alır |
| `--help` | açıklama, bir örnek, çıkış kodları | aynı + her alt komutta örnek, `--var KEY=VALUE`, `--vars-file FILE`, `template` yardımı |
| Kullanım hatası (çıkış 2) | usage + hata | aynı + `run 'ptm render --help' for examples` |
| Klasör verilirse | `Permission denied` (Windows) | `it is a directory, not a file` |
| Bozuk YAML | 5 satır PyYAML dökümü | `line 2, column 1: expected ...` |
| cp1254 konsolu | `→` içeren açıklamada iz + çıkış 1 | `?` ile yazılır, çıkış 0 |
| Test | 150 | 156 (+6: klasör, YAML satırı, boş dosya, kullanım yönlendirmesi, alt komut örneği, cp1254) |

## CLI akışı

```
çalıştır             uvx --from git+https://github.com/Furkiozknn/prompt-template-manager ptm --help
                     (ya da: uv tool install git+... ; PyPI'de henüz yok)
yaz                  templates/photo.yaml  (git'te, kodun yanında)
doğrula              ptm validate templates/*.yaml      çıkış 0, herhangi biri geçersizse 1
öğren                ptm info photo.yaml                hangi --var'lar var
üret                 ptm render photo.yaml --var subject=... [--vars-file f.yaml] [--pretty]
gönder               ptm submit photo.yaml --gateway-url http://127.0.0.1:8000 --var subject=...
yanlış komut         error: ... tek satır, çıkış 1; kullanım hatası çıkış 2 + --help yönlendirmesi
```

## Görsel dil (video sisteminden alınanlar)

Demo FRK-OS kimliğinde; `mcp-vet` yenilemesindeki terminal sahnesi (`arac/demo-uret.py`) uyarlandı, aynı palet.

| Ne | Nereden | Nerede |
|---|---|---|
| `zemin #0e0d0b`, panel `#14120e`, `yazi #f1ece2`, ilk vurgu `#ffc21a` | `sosyal/uret/tema.mjs` `klasik.akis` | terminal sahnesi zemini, panel, metin, sarı `$` isteği/sol çizgi |
| vurgu renkleri `#ff4d6d` (mercan), `#19d3e6` (camgöbeği) | `tema.mjs` klasik vurgular | `error:` ve diff'te `-` satırı mercan, `OK:` ve `+` satırı camgöbeği. Yalnızca boyama; metin değişmez |
| `doku: "izgara"` | `tema.mjs` klasik | gövdede çok soluk sabit ızgara (`rgba(241,236,226,.045)`, 48 px) |
| JetBrains Mono | `tema.mjs` `F.jb` | tüm terminal metni; SIL OFL 1.1, `assets/yazi/` (OFL metniyle) |
| `terminal: "koyu"` sahnesi, 30 ms/harf yazma, satır satır çıktı | `tema.mjs` `tercih.terminal`, `sahne.js` terminal tekniği | `arac/demo-uret.py` sayfası |

Kontrast (panel `#14120e` üstünde, WCAG göreli parlaklıktan hesaplandı; `mcp-vet` TASARIM.md'deki aynı renkler): krem 15,9:1, sönük metin `#b6ae9d` 8,5:1, sarı 11,6:1, mercan 5,8:1, camgöbeği 10,2:1; hepsi ≥ 4,5:1. Bilerek alınmayanlar: League Gothic başlık (README'de görsel başlık yok), geçişler (çıktının kendisi okunmalı).

## Kararlar ve sınırlar

- **Banner değişmedi** (`assets/banner.svg`, hesabın banner üreticisinden).
- **Reel ve eski `assets/demo.gif` README'den çıkarıldı**; üreticileri yok. Dosyalar depoda duruyor (silme işlemi yapılmadı); ayrıca git geçmişinde.
- Demo, aracın kendi örneğini (`examples/product-photo.yaml`) kullanır; son sahne `git diff --no-index` ile bir kelimelik prompt değişikliğinin tek satırlık diff olduğunu gösterir, çıkış kodu 1 kayıtta olduğu gibi durur (git bunu döndürür).
- Demo 1080x1920 kaydı depoya girmedi: `kanit/prompt-template-manager/demo-dikey.mp4` ve günlük video hattı için `sosyal/medya/projeler/prompt-template-manager/terminal.mp4`.
- `assets/fails-loudly.svg` yeniden üretilmedi: Windows'ta yol ayracı `\` çıkıyor (CI Linux'ta `/` üretip karşılaştırıyor); bu değişiklik SVG'deki hiçbir komutu etkilemiyor.
- `project-meta.json`: test sayısı 156, `gifs` yolu `docs/demo/demo.gif`; sürüm artırılmadı, `/meta` koşturulmadı. Sürüm, etiket, PyPI, dizin/awesome-list başvurusu, Pages ve GitHub description/homepage **yapılmadı** (onay kapısı).
