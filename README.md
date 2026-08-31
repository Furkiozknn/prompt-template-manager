# prompt-template-manager

Versioned, **git-diffable** prompt/pipeline templates for generative AI requests, with a strict renderer and a small CLI (`ptm`).

The idea: a generation request's *pipeline* — the prompt, the params, which capability it targets — should be a first-class, reviewable artifact, not a string buried in application code or a row in an opaque database. A template here is just a YAML file. Change a prompt, `git diff` shows exactly what changed, the same way it would for code. This is the same lesson ComfyUI's workflow-as-JSON teaches for node graphs, applied to the simpler case of parameterized prompts.

This is one piece of a small ecosystem of focused repos for an AI creative platform. `ptm render` outputs exactly the params shape [`ai-job-gateway`](https://github.com/Furkiozknn/ai-job-gateway) expects for `POST /v1/{capability}` — the two are decoupled (no Python import between them, only the documented HTTP contract), but `ptm submit` closes the loop directly.

## A template

```yaml
name: product-photo-on-solid-background
version: "1"
capability: mock-generate
description: A studio product photo on a solid background.

variables:
  product_name:
    type: string
    required: true
    description: What the photo is of, e.g. "a red sneaker"
  background_color:
    type: string
    default: white
  width:
    type: integer
    default: 1024

params:
  prompt: "professional studio product photo of {{ product_name }}, on a seamless {{ background_color }} background, soft even lighting"
  width: "${width}"
```

Two substitution forms, both deliberate:

- **`{{ variable }}`** — ordinary [Jinja2](https://jinja.palletsprojects.com/) string interpolation, for building up prose like a prompt. Strict by design: a typo'd variable name fails the render immediately instead of silently rendering as an empty string.
- **`"${variable}"`** (a param value that is *exactly* this, nothing else) — direct substitution of the variable's typed value. Use this for non-string params (`width`, `seed`, a boolean flag) so an integer variable stays an integer instead of getting stringified by Jinja.

Everything else — a plain number, a plain string with no template syntax, a boolean — passes through as a literal, untouched.

## The CLI

```bash
uv sync
uv run ptm validate examples/product-photo.yaml
# OK: product-photo-on-solid-background v1 (examples/product-photo.yaml)

uv run ptm render examples/product-photo.yaml --var product_name="a red sneaker" --pretty
# {
#   "prompt": "professional studio product photo of a red sneaker, on a seamless white background, soft even lighting, high detail, centered composition",
#   "width": 1024,
#   "height": 1024,
#   "seed": 0
# }

uv run ptm render examples/product-photo.yaml --var product_name="a red sneaker" --var background_color=black --var width=512

uv run ptm info examples/product-photo.yaml
# product-photo-on-solid-background  (v1)
#   A studio product photo on a solid background. `product_name` is required; ...
#   capability: mock-generate
#   variables:
#     product_name: string, required - What the photo is of, e.g. "a red sneaker"
#     background_color: string, default='white' - Backdrop color
#     ...

# Render + submit to a running ai-job-gateway-compatible server, wait for the result:
uv run ptm submit examples/product-photo.yaml --gateway-url http://127.0.0.1:8000 --var product_name="a red sneaker"
```

### `validate`

Checks a template without rendering it against any specific variable values:

- **Hard error** if `params` references a variable (via either `{{ }}` or `${}`) that isn't declared in `variables`. This is a real bug — the render would fail the moment someone actually calls it.
- **Warning** for a variable that's declared but never referenced anywhere in `params` — almost certainly dead, worth a second look, but not broken.

### `render`

Resolves variables (CLI `--var` overrides, falling back to declared defaults, erroring on any missing `required` variable or any `--var` for a name the template never declared) and prints the fully rendered `params` object as JSON — exactly the body you'd `POST` to a gateway's `/v1/{capability}` endpoint.

### `info`

A quick human-readable summary of a template's variables, types, and defaults — useful before filling in `--var` flags by hand.

### `submit`

`render` + `POST` to `{gateway-url}/v1/{capability}` + poll until ready, using the [same submit/poll contract `ai-job-gateway` implements](https://github.com/Furkiozknn/ai-job-gateway) (works against any server implementing that contract, not only that specific repo).

## Using it as a library

```python
from prompt_template_manager import load_template_file, render_template, validate_template

template = load_template_file("examples/product-photo.yaml")
validate_template(template)  # raises TemplateError on a real problem
params = render_template(template, {"product_name": "a red sneaker"})
# params == {"prompt": "...", "width": 1024, "height": 1024, "seed": 0}
```

## Variable types

`string`, `integer`, `float`, `boolean`. A CLI `--var` value always arrives as a string (that's just how CLI args work) and gets coerced to the declared type — `--var width=512` becomes the integer `512`, `--var shout=true` becomes the boolean `True` (accepts `true`/`false`/`1`/`0`/`yes`/`no`, case-insensitive). A value that can't be coerced (`--var width=not-a-number`) is a render-time error naming exactly which variable and value failed.

A `required: true` variable and a `default:` are mutually exclusive at the model level — a required variable has no default by definition, and declaring both is rejected as a template error rather than silently picking one.

## Development

```bash
uv sync --group dev
uv run pytest
```

The suite covers the model/loader/renderer layers directly and the CLI end-to-end (`capsys`-captured stdout/stderr, no subprocess spawning); the gateway-submission path is tested against `httpx.MockTransport`, no real server needed.

## License

MIT — see [LICENSE](LICENSE).
