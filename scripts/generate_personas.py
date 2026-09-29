"""Portraits for the three interview personas, generated once by hand.

Same shape as `generate_art.py`, and for the same reason: this is decoration
that changes roughly never, so generating it at request time would make every
interview pay for an image model call to look at a face. It runs once, writes
WEBP files into `frontend/public/personas/`, and after that the page is static.

**Why invented people and not stock photography.** The personas are fictional -
a warm first-round recruiter, a tech lead, a principal engineer - and a face
makes the choice between them concrete in a way a job title does not. The
prompts below describe nobody: no name, no real company, no likeness of any
person. A portrait that resembled a real individual would be a different thing
entirely, and not one to ship.

**The fourth figure is the candidate's chair, not the candidate.** It sits
opposite the interviewer so the page reads as two people across a desk. It is
deliberately generic: generating something meant to look like the person using
the application would be a likeness, and that is the line this script does not
cross. Anyone who wants their own face there can replace
`frontend/public/personas/candidate.webp` with a photo of themselves.

**They are labelled as illustrations in the UI.** A generated face presented
without comment invites the reader to think there is a person behind it. There
is not, and the interview is no more or less useful for that.

Nothing here guesses a model id. OpenRouter's `/models` endpoint says which
models return an image:

    python scripts/generate_personas.py --list

Costs a cent or two per image, and like the art script it is not metered by the
usage ledger, because it is not part of anyone's session.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
_OUT = REPO / "frontend" / "public" / "personas"

# Deliberately plain: a neutral background, a plain shirt, no logos, no badges,
# no text. Anything that looks like a real company or a real person is the one
# outcome worth avoiding here.
_STYLE = (
    "Soft flat vector illustration, not photorealistic. Seated at a desk, "
    "upper body visible, three-quarter view, plain single-colour background, "
    "muted indigo and slate palette, no text, no logos, no branding, "
    "no name badge, no coffee cup. An invented person, resembling nobody. "
    "Consistent style across the set: same line weight, same palette, "
    "same level of detail."
)

#: The expression is the point. Three interviewers who look identical tell you
#: nothing, and the difference between them is exactly what the personas encode:
#: the recruiter is forgiving, the principal is not. The wording stays at
#: "severe and unimpressed" rather than anything frightening - the aim is to
#: practise under pressure, not to be intimidated by a picture.
_LOOKS: dict[str, str] = {
    "recruiter": (
        "An approachable person in a soft collared shirt, seated, leaning "
        "slightly forward, open posture, warm and genuine smile, relaxed."
    ),
    "tech_lead": (
        "A focused person in a plain dark t-shirt, seated upright, glasses, "
        "attentive and neutral expression, hands resting on the desk, "
        "evaluating rather than smiling."
    ),
    "principal": (
        "A composed older person in a plain jacket, seated back in the chair, "
        "arms folded, eyebrow slightly raised, severe and unimpressed "
        "expression, direct unwavering gaze."
    ),
    # The candidate's side of the desk. Deliberately generic and deliberately
    # not anyone: this is the seat the user occupies, not a portrait of them.
    # Mirrored, so the two figures face each other across the layout.
    "candidate": (
        "A person in a plain light shirt, seated, facing left toward the "
        "viewer's left, calm and attentive, notebook on the desk, "
        "neutral hopeful expression."
    ),
}


def _client(settings) -> httpx.Client:
    return httpx.Client(
        base_url=settings.openrouter_base_url,
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key.get_secret_value()}",
            "HTTP-Referer": "http://localhost:5173",
            "X-Title": "PRAXA persona portraits",
        },
        timeout=180.0,
    )


def _prompt(key: str) -> str:
    look = _LOOKS.get(key, "A neutral professional person.")
    return f"{look} {_STYLE}"


def generate_one(client: httpx.Client, model: str, key: str, images_in, write) -> bool:
    body = {
        "model": model,
        "modalities": ["image", "text"],
        "messages": [{"role": "user", "content": _prompt(key)}],
    }
    response = client.post("/chat/completions", json=body)
    if response.status_code >= 400:
        print(f"  {key}: HTTP {response.status_code} - {response.text[:200]}")
        return False

    images = images_in(response.json())
    if not images:
        print(f"  {key}: the response carried no image")
        return False

    _OUT.mkdir(parents=True, exist_ok=True)
    path, size = write(images[0], _OUT / f"{key}.webp")
    print(f"  {key}: {path.name} ({size // 1024} KB)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="show image-capable models and exit")
    parser.add_argument("--model", help="model id (default: the first Gemini image model)")
    parser.add_argument("--only", choices=sorted(_LOOKS), help="generate one figure")
    args = parser.parse_args()

    # Imported here rather than at module scope because the repository root has
    # to be on the path first: `career_copilot` is pip-installed and imports
    # anywhere, but `scripts` is not a package, so `scripts.generate_art` does
    # not resolve until the root is on `sys.path`. Same pattern, and same
    # reason, as `generate_art.main`.
    sys.path.insert(0, str(REPO))
    from career_copilot.core.config import get_settings
    from career_copilot.interview.personas import PERSONAS

    # The art script's plumbing, reused rather than copied. The response-shape
    # handling in particular is hard-won: the key OpenRouter returns an image
    # under has moved more than once, and `_images_in` walks for it instead of
    # pinning one.
    from scripts.generate_art import _images_in, _write, image_models

    with _client(get_settings()) as client:
        available = image_models(client)
        if args.list:
            for model in available:
                print(model["id"])
            return 0
        if not available:
            print("Your key reaches no image-capable model.")
            return 1

        model = args.model or next(
            (entry["id"] for entry in available if "gemini" in entry["id"]),
            available[0]["id"],
        )
        # Every persona, plus the candidate who sits opposite them.
        keys = [args.only] if args.only else sorted(set(PERSONAS) | {"candidate"})
        print(f"model: {model}\ninto : {_OUT}\n")

        written = sum(generate_one(client, model, key, _images_in, _write) for key in keys)

    print(f"\n{written} of {len(keys)} written.")
    if written:
        print("These are illustrations of invented people, and the UI says so.")
    return 0 if written == len(keys) else 1


if __name__ == "__main__":
    sys.exit(main())
