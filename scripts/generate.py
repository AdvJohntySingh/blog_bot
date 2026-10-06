"""Daily legal blog draft generator.

Usage:
  python scripts/generate.py generate   # creates drafts/<date>/ (post.md, image.jpg, draft.json)
  python scripts/generate.py notify     # sends the latest draft to Telegram with Approve/Reject buttons
"""
import datetime
import json
import os
import pathlib
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET

import requests

JURISDICTION = os.environ.get("JURISDICTION", "India")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
FEEDS = [
    "https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{JURISDICTION} law court judgment when:2d")
    + "&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{JURISDICTION} legal amendment new law when:3d")
    + "&hl=en-IN&gl=IN&ceid=IN:en",
]
ID_FILE = pathlib.Path(".draft_id")


def headlines():
    seen, out = set(), []
    for url in FEEDS:
        try:
            root = ET.fromstring(requests.get(url, timeout=30).content)
        except Exception as e:  # keep going if one feed fails
            print("feed failed:", e)
            continue
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            if title and title not in seen:
                seen.add(title)
                out.append(title)
    return out[:20]


def gemini(prompt):
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        },
        timeout=180,
    )
    r.raise_for_status()
    return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])


def generate():
    news = headlines()
    if not news:
        sys.exit("No headlines fetched")
    recent = [
        json.loads(f.read_text(encoding="utf-8")).get("title", "")
        for f in sorted(pathlib.Path("published").glob("*.json"))[-30:]
    ]
    prompt = f"""You write blog posts for a practising lawyer's website (jurisdiction: {JURISDICTION}).
From these recent headlines, pick ONE topic that is relevant and useful to the public or other lawyers:
{json.dumps(news, indent=1)}

Avoid repeating these recent post titles: {recent}

Write a 600-800 word blog post in clear, plain English with short paragraphs and a few ## subheadings.
Do not invent case names, section numbers or quotes. If unsure of a detail, stay general.
End with a one-line note that this is general information, not legal advice.

Return JSON with keys:
title, slug (lowercase-hyphens), description (max 160 chars), tags (list of 3-5 short strings),
body_markdown (no title heading), image_prompt (a photorealistic professional portrait of a lawyer
in a setting that visually relates to the topic; no text in the image)."""
    d = gemini(prompt)
    slug = re.sub(r"[^a-z0-9-]+", "-", d["slug"].lower()).strip("-")[:70] or "post"
    today = datetime.date.today().isoformat()

    folder = pathlib.Path("drafts") / today
    folder.mkdir(parents=True, exist_ok=True)

    img_url = (
        "https://image.pollinations.ai/prompt/"
        + urllib.parse.quote(d["image_prompt"])
        + "?width=1024&height=1024&nologo=true"
    )
    img = requests.get(img_url, timeout=180)
    img.raise_for_status()
    (folder / "image.jpg").write_bytes(img.content)

    post = d["body_markdown"].strip() + "\n\n*Cover image: AI-generated, for illustration.*\n"
    (folder / "post.md").write_text(post, encoding="utf-8")
    (folder / "draft.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "title": d["title"],
                "description": d["description"],
                "tags": d["tags"],
            }
        ),
        encoding="utf-8",
    )
    ID_FILE.write_text(today)
    print("Draft created:", folder)


def notify():
    today = ID_FILE.read_text().strip()
    folder = pathlib.Path("drafts") / today
    meta = json.loads((folder / "draft.json").read_text(encoding="utf-8"))
    token, chat = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    api = f"https://api.telegram.org/bot{token}"

    with open(folder / "image.jpg", "rb") as f:
        requests.post(
            f"{api}/sendPhoto",
            data={"chat_id": chat, "caption": f"{meta['title']}\n\n{meta['description']}"[:1000]},
            files={"photo": f},
            timeout=60,
        ).raise_for_status()

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "Approve", "callback_data": f"approve:{today}"},
                {"text": "Reject", "callback_data": f"reject:{today}"},
            ]
        ]
    }
    with open(folder / "post.md", "rb") as f:
        requests.post(
            f"{api}/sendDocument",
            data={
                "chat_id": chat,
                "caption": "Full draft attached. Review the facts, then choose.",
                "reply_markup": json.dumps(keyboard),
            },
            files={"document": ("post.md", f)},
            timeout=60,
        ).raise_for_status()


if __name__ == "__main__":
    {"generate": generate, "notify": notify}[sys.argv[1]]()
