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

### Guvenlik
- `capability` tek bir URL yol parcasi olmak zorunda; ucuncu parti bir
  sablon `../` ile `ptm submit` istegini gateway'in baska bir ucuna
  yonlendiremez.
- Sablonlar sandbox'ta render edilir (README, Security bolumu).

### Duzeltildi
- Dizin, okunamayan ya da UTF-8 olmayan dosya, ulasilamayan gateway, poll
  sirasinda HTTP hatasi ve JSON olmayan gateway yaniti artik ham traceback
  degil, `error:` satiri ve cikis kodu 1.
- `required: "false"` (tirnakli) degiskeni sessizce zorunlu yapiyordu;
  artik yalniz gercek `true`/`false` kabul ediliyor.
- Atanmamis istege bagli degisken metne `None` olarak basiliyordu.

[0.1.0]: https://github.com/Furkiozknn/prompt-template-manager/releases/tag/v0.1.0
