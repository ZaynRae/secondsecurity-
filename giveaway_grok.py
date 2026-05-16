"""
giveaway_grok.py

Tool sederhana untuk auto-generate kalimat ikut giveaway memakai
"gaya bahasa Grok" yang dipakai di repo xai-org/x-algorithm:

  - System prompt imperatif (Analyze ... Provide JSON ...)
  - Suhu sampling sangat rendah (temperature = 0.000001) -> deterministik
  - Output dibungkus tag <json>...</json>, lalu di-parse pakai regex

Cara pakai:
    # via xAI API (perlu env var XAI_API_KEY)
    python giveaway_grok.py "Giveaway 1 iPhone 15! RT + follow @akun + comment alasan kamu"

    # baca dari file
    python giveaway_grok.py -f post.txt

    # baca dari stdin
    echo "Giveaway PS5..." | python giveaway_grok.py -

    # generate banyak varian sekaligus
    python giveaway_grok.py -n 5 "Giveaway saldo dana 500rb..."

    # offline / tanpa API key (pakai fallback template generator)
    python giveaway_grok.py --offline "Giveaway tumbler..."
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# 1) System prompt - meniru gaya yang dipakai grox/classifiers/content/*.py
#    Pola: imperatif, satu kalimat per baris, kunci output ke <json>...</json>
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are an assistant that writes short, natural-sounding giveaway entry comments
in the same language as the input post (Indonesian or English).

Rules:
- The comment MUST sound like a real human entry, not spammy.
- The comment MUST be relevant to the giveaway prize and the host account.
- Keep it concise (maximum 2 short sentences, under 220 characters).
- Include 1-2 tasteful emojis only when it fits the tone of the post.
- DO NOT invent fake follower counts, fake purchase history, or fake personal info.
- DO NOT use slurs, hate speech, or sensitive content.
- DO NOT start every comment with the same word; vary the openings.
- If the post asks to mention/tag friends, use generic placeholders like
  @teman1 @teman2 so the user can replace them later.

Output format:
- First write a short reasoning paragraph (1-3 sentences) explaining the tone
  and approach you chose for this specific post.
- Then output a single <json>...</json> block with this exact schema:

  {
    "language": "id" | "en",
    "prize": "<short description of the prize you detected>",
    "host": "<@handle of the host account, or empty string if not detected>",
    "comments": [
      "<comment variant 1>",
      "<comment variant 2>",
      "..."
    ]
  }

Always produce exactly N comment variants where N is given by the user.
"""


USER_TEMPLATE = """\
Post text:
\"\"\"
{post}
\"\"\"

Analyze the giveaway post above and provide the requested JSON object.
Generate exactly {n} distinct comment variants suitable for entering this
giveaway. Each variant must use a different opening word.\
"""


# ---------------------------------------------------------------------------
# 2) Output parser - meniru result_pattern di banger_initial_screen.py:
#    result_pattern = re.compile(r"(.*)<json>(.*)</json>", re.DOTALL)
# ---------------------------------------------------------------------------
RESULT_PATTERN = re.compile(r"(.*?)<json>(.*?)</json>", re.DOTALL)


@dataclass
class GiveawayResult:
    reasoning: str
    language: str
    prize: str
    host: str
    comments: list[str]

    def pretty(self) -> str:
        lines = [
            f"Detected language : {self.language}",
            f"Detected prize    : {self.prize}",
            f"Detected host     : {self.host or '(none)'}",
            "",
            "Reasoning:",
            f"  {self.reasoning.strip()}",
            "",
            "Generated comments:",
        ]
        for i, c in enumerate(self.comments, 1):
            lines.append(f"  {i}. {c}")
        return "\n".join(lines)


def parse_grok_output(raw: str, expected_n: int) -> GiveawayResult:
    """Parse output bergaya Grok: <reasoning> <json>{...}</json>."""
    m = RESULT_PATTERN.search(raw)
    if not m:
        raise ValueError(f"Output tidak mengandung blok <json>...</json>:\n{raw}")
    reasoning = m.group(1).strip()
    payload = json.loads(m.group(2).strip())

    comments = payload.get("comments") or []
    if not isinstance(comments, list) or not comments:
        raise ValueError("Field 'comments' kosong atau bukan list.")

    return GiveawayResult(
        reasoning=reasoning,
        language=payload.get("language", ""),
        prize=payload.get("prize", ""),
        host=payload.get("host", ""),
        comments=[str(c).strip() for c in comments[:expected_n]],
    )


# ---------------------------------------------------------------------------
# 3) Pemanggilan API xAI (Grok). Pakai endpoint OpenAI-compatible.
#    Lihat https://docs.x.ai untuk dokumentasi resmi.
# ---------------------------------------------------------------------------
XAI_API_URL = "https://api.x.ai/v1/chat/completions"


def call_grok(post: str, n: int, model: str, api_key: str, timeout: int = 60) -> str:
    body = {
        "model": model,
        "temperature": 0.000001,  # nilai yang dipakai di repo x-algorithm
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(post=post, n=n)},
        ],
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        XAI_API_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"xAI API HTTP {e.code}: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"xAI API network error: {e}") from e

    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Respons API tidak terduga: {payload}") from e


# ---------------------------------------------------------------------------
# 4) Fallback offline: generator template sederhana yang tetap mengikuti
#    "kontrak output" (reasoning + <json>{...}</json>).
# ---------------------------------------------------------------------------
HANDLE_RE = re.compile(r"@([A-Za-z0-9_]{1,20})")

# Kata-kata khas Indonesia yang biasanya TIDAK muncul di teks Inggris.
ID_HINTS = (
    "kak", "aku", "kamu", "saya", "udah", "sudah", "yang", "dan",
    "buat", "untuk", "alasan", "menang", "ikutan", "ikut", "rezeki",
    "saldo", "rupiah", "ribu", "juta", " rb ", "hadiah", "syarat",
    "periode", "doain", "mau ", "banget",
)
EN_HINTS = (
    " the ", " and ", " with ", " what ", " you'd ", " your ",
    " win ", " ends ", " gift ", " card ", " entry ", " enter ",
    " thanks ", " comment ", " hope ",
)


def detect_language(text: str) -> str:
    low = " " + text.lower() + " "
    id_score = sum(1 for h in ID_HINTS if h in low)
    en_score = sum(1 for h in EN_HINTS if h in low)
    if id_score == en_score == 0:
        # tidak ada petunjuk -> default ke English
        return "en"
    return "id" if id_score >= en_score else "en"


def detect_host(text: str) -> str:
    handles = HANDLE_RE.findall(text)
    return f"@{handles[0]}" if handles else ""


def detect_prize(text: str) -> str:
    """Tebakan kasar: ambil potongan kalimat yang menyebut prize-nya."""
    # Pisahkan jadi kalimat pendek dulu (titik, seru, koma, baris baru, kolon).
    sentences = re.split(r"[.!?\n]", text)
    for sentence in sentences:
        low = sentence.lower()
        if "giveaway" in low or "hadiah" in low or "prize" in low:
            cleaned = sentence.strip()
            # Buang kata "GIVEAWAY"/"HADIAH" di depan & teks "Syarat:" ke
            # belakang supaya yang tersisa hanya nama hadiahnya.
            cleaned = re.sub(
                r"^(giveaway|hadiah|prize)[:\s]*",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
            cleaned = re.split(
                r"\b(syarat|caranya|cara ikut|terms|rules|deadline)\b",
                cleaned,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            cleaned = cleaned.strip(" ,!.:-")
            if cleaned:
                return cleaned[:80]
    return text.strip()[:60]


ID_TEMPLATES = [
    "Ikutan ya kak! {prize_short} banget bisa bikin {benefit}. Semoga rezeki ada di aku {emoji}",
    "Wah {prize_short} idamanku banget {emoji} udah follow + RT, fingers crossed!",
    "Done semua syarat {host}! Kalau menang aku mau {use_case}, makasih giveaway-nya {emoji}",
    "Aku ikutan dong, alasan: {reason}. Done RT + follow + tag @teman1 @teman2 {emoji}",
    "Mau banget {prize_short} ini buat {use_case}, doain menang ya {emoji}",
    "Auto ikut! {prize_short} pas banget aku lagi butuh. Semoga kepilih {emoji}",
    "Wishlist banget {prize_short}, semoga kali ini rezekinya nempel {emoji}",
]

EN_TEMPLATES = [
    "Counting me in! {prize_short} would totally help me {benefit} {emoji}",
    "Done all the steps {host}! If I win I'd love to {use_case}, thank you {emoji}",
    "Following + RT'd! {prize_short} has been on my list forever, fingers crossed {emoji}",
    "Hoping for some luck here, {prize_short} is exactly what I need to {use_case} {emoji}",
    "In! Tagging @friend1 @friend2 - this giveaway is amazing {emoji}",
    "Pick me please! {prize_short} would make my month {emoji}",
]

ID_BENEFITS = [
    "produktif kerja",
    "konten makin rapi",
    "belajar online lebih nyaman",
    "ngirim hadiah ke ortu",
    "ngebantu kebutuhan harian",
]
EN_BENEFITS = [
    "level up my workflow",
    "stay productive",
    "upgrade my setup",
    "help out at home",
]
ID_USE_CASES = [
    "kasih ke ibu",
    "dipake kerja remote",
    "buat hadiah ulang tahun adik",
    "nemenin belajar tiap malam",
]
EN_USE_CASES = [
    "give it to my mom",
    "use it for daily work",
    "gift it to my sibling",
    "level up my home setup",
]
EMOJIS = ["🤞", "✨", "🙏", "🔥", "🎉", ""]


def offline_generate(post: str, n: int) -> str:
    lang = detect_language(post)
    host = detect_host(post)
    prize = detect_prize(post)
    prize_short = re.sub(r"\s+", " ", prize).strip().rstrip(",.!?:;")[:60]
    if not prize_short:
        prize_short = "hadiahnya" if lang == "id" else "the prize"

    rng = random.Random(hash(post) & 0xFFFFFFFF)
    templates = ID_TEMPLATES if lang == "id" else EN_TEMPLATES
    benefits = ID_BENEFITS if lang == "id" else EN_BENEFITS
    use_cases = ID_USE_CASES if lang == "id" else EN_USE_CASES

    chosen = rng.sample(templates, k=min(n, len(templates)))
    while len(chosen) < n:
        chosen.append(rng.choice(templates))

    comments = []
    for tpl in chosen:
        c = tpl.format(
            prize_short=prize_short,
            host=host or "",
            benefit=rng.choice(benefits),
            use_case=rng.choice(use_cases),
            emoji=rng.choice(EMOJIS),
            reason=rng.choice(benefits),
        )
        c = re.sub(r"\s+", " ", c).strip()
        comments.append(c)

    reasoning = (
        f"Bahasa terdeteksi: {lang}. Prize tebakan: '{prize_short}'. "
        f"Host: {host or '(tidak ada)'}. "
        "Saya pilih nada santai-positif, hindari spam, dan variasikan kata pembuka "
        "supaya tidak terlihat seragam."
    )
    payload = {
        "language": lang,
        "prize": prize_short,
        "host": host,
        "comments": comments,
    }
    return f"{reasoning}\n<json>{json.dumps(payload, ensure_ascii=False)}</json>"


# ---------------------------------------------------------------------------
# 5) CLI
# ---------------------------------------------------------------------------
def read_post(args: argparse.Namespace) -> str:
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            return f.read().strip()
    if args.post == "-" or (not args.post and not sys.stdin.isatty()):
        return sys.stdin.read().strip()
    if args.post:
        return args.post.strip()
    raise SystemExit(
        "Tidak ada teks giveaway. Berikan via argumen, -f FILE, atau pipe ke stdin."
    )


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Auto-generate kalimat ikut giveaway dengan gaya bahasa Grok."
    )
    p.add_argument("post", nargs="?", help="Teks postingan giveaway (atau '-' untuk stdin).")
    p.add_argument("-f", "--file", help="Baca teks giveaway dari file.")
    p.add_argument("-n", "--num", type=int, default=3, help="Jumlah varian komentar (default: 3).")
    p.add_argument("--model", default=os.environ.get("XAI_MODEL", "grok-4-latest"),
                   help="Model xAI (default: grok-4-latest atau env XAI_MODEL).")
    p.add_argument("--offline", action="store_true",
                   help="Paksa pakai generator template lokal, jangan panggil API.")
    p.add_argument("--raw", action="store_true",
                   help="Tampilkan output mentah (reasoning + <json>) tanpa diparse.")
    args = p.parse_args(argv)

    if args.num < 1 or args.num > 10:
        p.error("--num harus 1..10")

    post = read_post(args)
    if not post:
        p.error("Teks giveaway kosong.")

    api_key = os.environ.get("XAI_API_KEY", "").strip()

    if args.offline or not api_key:
        if not api_key and not args.offline:
            print("[info] XAI_API_KEY tidak diset, pakai mode offline.", file=sys.stderr)
        raw = offline_generate(post, args.num)
    else:
        raw = call_grok(post, args.num, args.model, api_key)

    if args.raw:
        print(raw)
        return 0

    try:
        result = parse_grok_output(raw, args.num)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"[error] gagal parse output: {e}", file=sys.stderr)
        print("---- raw ----", file=sys.stderr)
        print(raw, file=sys.stderr)
        return 2

    print(result.pretty())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
