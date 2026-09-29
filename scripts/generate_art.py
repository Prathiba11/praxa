"""Generate the background art for the home page, using your own OpenRouter key.

**Why this is a script and not something the application does.** The art is
decoration that changes roughly never. Generating it at request time would mean
every visitor pays for an image model call to look at a background, and would
make the home page depend on a network call it does not need. So this runs once,
by hand, and writes PNG files into `frontend/public/art/`. Vite serves anything
in `public/` as-is, and after that the home page is a static page again.

**Nothing here guesses a model id.** OpenRouter's `/models` endpoint says which
models can return an image, so the script asks rather than hard-coding a name
that may have been renamed or retired:

    python scripts/generate_art.py --list

prints every image-capable model your key can reach. Pick one and pass it with
`--model`, or let the script take the first Gemini image model it finds.

**If the response does not look the way this expects, nothing is silently
dropped.** The exact JSON is written to `data/art_raw_response.json` and the
script says so. That is deliberate: an image pipeline that fails by writing a
zero-byte PNG is worse than one that fails loudly.

Costs money - roughly a cent or two per image at current image-model rates, and
unlike the rest of this project it is not metered by the usage ledger, because
it is not part of a user's session.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import sys
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
ART_DIR = REPO / "frontend" / "public" / "art"
RAW_DUMP = REPO / "data" / "art_raw_response.json"

#: Abstract on purpose. A generated photograph of a person at a desk is a stock
#: photo with extra steps, and it would fight the drawn marks already in the
#: interface. These are textures: they sit behind content at low opacity, they
#: carry no subject to misread, and they survive being tinted by the theme.
#: name -> (prompt, build a themeable mask from it).
#:
#: The flag matters: a line drawing on a dark field is useless as an image in a
#: light theme and perfect as a mask, while a colour wash like the aurora is the
#: opposite - its colour *is* the content, so masking it would throw the piece
#: away and keep the outline.
PIECES: dict[str, tuple[str, bool]] = {
    "hero-bloom": (
        (
            "Abstract soft aurora gradient mesh, deep indigo and violet blooming into "
            "faint teal at the edges, very dark near-black background, smooth volumetric "
            "light, heavy gaussian blur, no subject, no objects, no people, no text, "
            "no letters, no logo, seamless wide banner composition, 16:9"
        ),
        False,
    ),
    "topo-lines": (
        (
            "Minimal topographic contour map lines, thin even single-weight strokes, "
            "concentric organic elevation rings, muted violet lines on a plain very dark "
            "background, large empty areas, technical drawing style, no shading, no fill, "
            "no text, no numbers, no labels, no compass, seamless wide banner, 16:9"
        ),
        True,
    ),
}

#: The house style every generated texture shares. Passed with --prompt so a new
#: piece joins the set instead of arriving as an unrelated picture: three
#: different illustrations would undo the thing that makes the current two read
#: as one design.
LINE_STYLE = (
    "thin even single-weight strokes, muted violet lines on a plain very dark "
    "background, large empty areas, technical drawing style, no shading, no fill, "
    "no text, no numbers, no labels, seamless wide banner, 16:9"
)


def _client(settings) -> httpx.Client:
    return httpx.Client(
        base_url=settings.openrouter_base_url,
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key.get_secret_value()}",
            "HTTP-Referer": "http://localhost:5173",
            "X-Title": "PRAXA art generation",
        },
        timeout=180.0,
    )


def image_models(client: httpx.Client) -> list[dict]:
    """Every model your key can reach that is documented as returning an image."""
    response = client.get("/models")
    response.raise_for_status()
    found = []
    for model in response.json().get("data", []):
        outputs = (model.get("architecture") or {}).get("output_modalities") or []
        if "image" in outputs:
            found.append(model)
    return sorted(found, key=lambda model: model["id"])


def _images_in(payload: dict) -> list[str]:
    """Pull image payloads out of the response without assuming one shape.

    OpenRouter returns generated images on the assistant message rather than in
    the text content, but the exact key has moved between `images`, entries in a
    content list, and provider-specific shapes. Rather than pin one and break
    quietly when it changes, this walks the response for anything that looks like
    a data URL or a base64 blob under an image-ish key.
    """
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, str):
            if node.startswith("data:image/"):
                found.append(node)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"b64_json", "data"} and isinstance(value, str) and len(value) > 512:
                    found.append(f"data:image/png;base64,{value}")
                else:
                    walk(value)

    walk(payload)
    # A response can repeat the same image in more than one place.
    return list(dict.fromkeys(found))


def _decode(data_url: str) -> Image.Image:
    match = re.match(r"data:image/[a-zA-Z]+;base64,(?P<body>.+)", data_url, re.S)
    if match is None:
        raise ValueError("not a base64 data URL")
    blob = base64.b64decode(match.group("body"))
    if len(blob) < 1024:
        raise ValueError(f"decoded image is only {len(blob)} bytes - treating as a failure")
    return Image.open(io.BytesIO(blob)).convert("RGB")


def _trim_letterbox(image: Image.Image) -> Image.Image:
    """Drop the black bars an image model pads a non-square request with.

    Asking for a 16:9 banner returns a square canvas with the banner centred in
    it, because these models generate at a fixed size. Shipping that as-is means
    a hero image that is two thirds black, so the flat black rows are measured
    and removed rather than trusted to a hard-coded crop.
    """
    rows = np.asarray(image.convert("L")).max(axis=1)
    lit = np.flatnonzero(rows > 10)
    if lit.size == 0 or lit.size == rows.size:
        return image
    return image.crop((0, int(lit[0]), image.width, int(lit[-1]) + 1))


def _write(data_url: str, path: Path) -> tuple[Path, int]:
    """Save as WebP, which is what makes these usable as page backgrounds.

    The raw PNG of a smooth gradient came back at half a megabyte and the
    contour texture at 1.1 MB. As WebP the same two images are 6 KB and 57 KB -
    a background nobody is meant to notice should not be the largest download on
    the page.
    """
    image = _trim_letterbox(_decode(data_url))
    path = path.with_suffix(".webp")
    image.save(path, "WEBP", quality=82, method=6)
    return path, path.stat().st_size


def write_mask(source: Path, target: Path) -> int:
    """Turn a dark-field line drawing into a themeable alpha mask.

    The generated contour texture is violet lines on near-black. Used directly
    it is correct in dark mode and a black rectangle in light mode. Painting the
    lines white on a transparent field instead lets the page use it as a CSS
    mask over whatever fill it likes, so one asset serves both themes and
    follows the accent colour if that changes.

    The threshold is measured from the image: the median luminance is the flat
    field, the 99.7th percentile is the brightest stroke, and everything between
    becomes alpha.
    """
    image = Image.open(source).convert("RGB").resize((768, 768), Image.LANCZOS)
    pixels = np.asarray(image).astype(np.float32)
    luminance = pixels[..., 0] * 0.2126 + pixels[..., 1] * 0.7152 + pixels[..., 2] * 0.0722
    floor = float(np.median(luminance))
    ceiling = float(np.percentile(luminance, 99.7))
    alpha = np.clip((luminance - floor) / max(ceiling - floor, 1.0), 0.0, 1.0)

    rgba = np.dstack([np.full(pixels.shape, 255, np.uint8), (alpha * 255).astype(np.uint8)])
    # The colour channel is a flat white, so file size is almost entirely the
    # alpha channel - `alpha_quality` is the dial that matters, not `quality`.
    Image.fromarray(rgba, "RGBA").save(target, "WEBP", quality=60, method=6, alpha_quality=25)
    return target.stat().st_size


def generate(client: httpx.Client, model: str, name: str, prompt: str, *, mask: bool) -> None:
    body = {
        "model": model,
        "modalities": ["image", "text"],
        "messages": [{"role": "user", "content": prompt}],
    }
    response = client.post("/chat/completions", json=body)
    if response.status_code >= 400:
        print(f"  {name}: HTTP {response.status_code} - {response.text[:300]}")
        return

    payload = response.json()
    images = _images_in(payload)
    if not images:
        RAW_DUMP.parent.mkdir(parents=True, exist_ok=True)
        RAW_DUMP.write_text(json.dumps(payload, indent=2)[:200_000], encoding="utf-8")
        print(f"  {name}: no image in the response. Raw JSON written to {RAW_DUMP}")
        return

    ART_DIR.mkdir(parents=True, exist_ok=True)
    path, size = _write(images[0], ART_DIR / name)
    print(f"  {name}: {size // 1024} KB -> {path}")

    if mask:
        target = ART_DIR / f"{name.removesuffix('-lines')}-mask.webp"
        print(f"  {target.stem}: {write_mask(path, target) // 1024} KB -> {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="show image-capable models and exit")
    parser.add_argument("--model", help="model id to use (default: first Gemini image model)")
    parser.add_argument("--only", help="generate one piece by name", choices=sorted(PIECES))
    parser.add_argument("--prompt", help="generate one image from your own prompt")
    parser.add_argument("--name", default="custom", help="file name to use with --prompt")
    parser.add_argument(
        "--mask",
        action="store_true",
        help="also build a themeable white-on-transparent mask from the result",
    )
    parser.add_argument(
        "--house-style",
        action="store_true",
        help="append the shared line style to --prompt, so the piece joins the set",
    )
    args = parser.parse_args()

    # Imported here rather than at module scope because the repository root has
    # to be on the path first, and a module-level import after a `sys.path`
    # mutation is exactly the pattern the linter is right to flag.
    sys.path.insert(0, str(REPO))
    from career_copilot.core.config import get_settings

    settings = get_settings()
    with _client(settings) as client:
        available = image_models(client)
        if not available:
            print("Your key reaches no model that returns images.")
            return 1

        if args.list:
            for model in available:
                price = (model.get("pricing") or {}).get("image", "?")
                print(f"{model['id']:<52} {model.get('name', '')}  image={price}")
            return 0

        ids = [model["id"] for model in available]
        if args.model:
            if args.model not in ids:
                print(f"'{args.model}' is not image-capable on your key. Try --list.")
                return 1
            model_id = args.model
        else:
            gemini = [i for i in ids if "gemini" in i]
            model_id = (gemini or ids)[0]

        print(f"Using {model_id}\n")
        if args.prompt:
            prompt = f"{args.prompt}, {LINE_STYLE}" if args.house_style else args.prompt
            generate(client, model_id, args.name, prompt, mask=args.mask)
        else:
            wanted = {args.only: PIECES[args.only]} if args.only else PIECES
            for name, (prompt, wants_mask) in wanted.items():
                generate(client, model_id, name, prompt, mask=wants_mask)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
