# Changelog

Bu dosya [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) bicimini,
surumler [Semantic Versioning](https://semver.org/) kuralini izler.
`pyproject.toml` ve `src/prompt_template_manager/__init__.py` icindeki surum
buradaki en ust surumle ayni olmalidir; `yayinla.yml` etiketle
`pyproject.toml` uyusmazsa yayini durdurur.

## [0.1.0] - Yayimlanmadi

Ilk yayin. PyPI paket adi `ptm-cli`, komut `ptm`.

### Eklendi
- YAML sablon bicimi: `name`, `version`, `capability`, `params`, tipli
  `variables` (`string`, `integer`, `float`, `boolean`), `required` / `default`.
- Jinja2 `SandboxedEnvironment` + `StrictUndefined` ile `{{ var }}`, tipini
  koruyan `"${var}"` dogrudan yerine koyma.
- CLI: `ptm validate` (birden cok dosya, ozet satiri, CI icin cikis kodu),
  `ptm render` (`--var`, `--vars-file`, `--pretty`), `ptm info`,
  `ptm submit` (ai-job-gateway uyumlu submit/poll), `ptm --version`.
- `validate`: tanimsiz degisken hatasi, kullanilmayan degisken uyarisi,
  tipine donusmeyen `default` hatasi, bir string'in yalnizca parcasi olan
  `${var}` uyarisi.
- `ptm --help` ornek komut ve cikis kodlarini (0/1/2/130) gosteriyor.

### Guvenlik
- `capability` tek bir URL yol parcasi olmak zorunda; ucuncu parti bir
  sablon `../` ile `ptm submit` istegini gateway'in baska bir ucuna
  yonlendiremez.
- Sablonlar sandbox'ta render edilir (README, Security bolumu).
- `params` yalnizca duz JSON olabilir ve alias'lar acildiktan sonra en fazla
  10.000 deger / 32 seviye: alias bombasi ya da kendine donen alias
  yuklemede reddedilir (once `validate` askida kaliyor ya da
  RecursionError veriyordu).
- `{{ }}` icinde `**` ve `*` ile tekrar sinirli: `{{ 10 ** (10 ** 9) }}`
  sureci kilitliyor, `{{ 'a' * 3000000000 }}` bellegi bitiriyordu.
- Gateway'in dondurdugu `polling_url` yalniz ayni hosttaki bir yol olabilir;
  `"@baska.host/x"` poll istegini (ve `--gateway-url` icindeki parolayi)
  baska bir hosta goturuyordu.
- `--gateway-url` istekten once denetlenir (http/https, host, sorgu/parca
  yok); icindeki kullanici adi/parola hata mesajlarinda gosterilmez.

### Duzeltildi
- Dizin, okunamayan ya da UTF-8 olmayan dosya, ulasilamayan gateway, poll
  sirasinda HTTP hatasi ve JSON olmayan gateway yaniti artik ham traceback
  degil, `error:` satiri ve cikis kodu 1.
- `required: "false"` (tirnakli) degiskeni sessizce zorunlu yapiyordu;
  artik yalniz gercek `true`/`false` kabul ediliyor.
- Atanmamis istege bagli degisken metne `None` olarak basiliyordu.
- Tirnaksiz tarih (`2024-01-01`), `!!binary`, `.nan` iceren `params`:
  `validate` OK diyor, `render` traceback veriyor ya da gecersiz JSON
  (`NaN`) basiyordu. `--var x=nan` / `inf` de ayni.
- vars dosyasinda bos deger (`v:`) modele `"None"`, liste degeri
  `"['a', 'b']"` olarak gidiyordu; ikisi de artik hata.
- `{{ 1/0 }}`, `{{ 'a' + 1 }}`, sayi olan degisken adi, sayi olan
  `polling_url`, `--timeout nan` (sonsuz poll), Ctrl+C: traceback yerine
  `error:` satiri ve anlamli cikis kodu.

[0.1.0]: https://github.com/Furkiozknn/prompt-template-manager/releases/tag/v0.1.0
