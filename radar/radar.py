#!/usr/bin/env python3
"""Daily bug-bounty target radar (GitHub Actions free tier).
Finds freshly-published contract repos, scores money-path signals, dedupes vs
radar/seen.json, writes radar/latest.md and commits both back."""
import base64, datetime, json, os, re, urllib.parse, urllib.request

H = {"Accept": "application/vnd.github+json", "User-Agent": "bb-radar"}
TOK = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
if TOK:
    H["Authorization"] = f"Bearer {TOK}"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEN_F = os.path.join(ROOT, "radar", "seen.json")
LATEST_F = os.path.join(ROOT, "radar", "latest.md")
os.makedirs(os.path.dirname(SEEN_F), exist_ok=True)
seen = set(json.load(open(SEEN_F))) if os.path.exists(SEEN_F) else set()

def gh(path):
    req = urllib.request.Request("https://api.github.com" + path, headers=H)
    return json.load(urllib.request.urlopen(req, timeout=30))

def readme(full):
    try:
        d = gh(f"/repos/{full}/readme")
        return base64.b64decode(d["content"]).decode("utf-8", "replace")[:2500]
    except Exception:
        return ""

def sec_text(full):
    """Isi SECURITY.md bila ada (dipotong 4000 char)."""
    try:
        d = gh(f"/repos/{full}/contents/SECURITY.md")
        return base64.b64decode(d["content"]).decode("utf-8", "replace")[:4000]
    except Exception:
        return ""


def has_contract_code(full):
    """True bila root repo memuat artefak kontrak (foundry/hardhat/anchor/cargo program)."""
    try:
        names = {e["name"].lower() for e in gh(f"/repos/{full}/contents/")}
    except Exception:
        return False
    if {"foundry.toml", "hardhat.config.js", "hardhat.config.ts", "anchor.toml", "programs"} & names:
        return True
    if "cargo.toml" in names:
        try:
            t = gh(f"/repos/{full}/contents/Cargo.toml")
            body = base64.b64decode(t["content"]).decode("utf-8", "replace").lower()
            return "solana-program" in body or "anchor-lang" in body
        except Exception:
            return False
    return False


PAY = {
    "immunefi": "Immunefi", "bugcrowd": "Bugcrowd", "hackerone": "HackerOne",
    "cantina": "Cantina", "code4rena": "Code4rena", "sherlock": "Sherlock",
    "hackenproof": "HackenProof", "yeswehack": "YesWeHack", "intigriti": "Intigriti",
}
MONEY_RE = re.compile(r"(?:\$|USD[TC]?\s?)\s?([0-9][0-9,\.]{2,})", re.I)


def bounty_signal(sec, readme_text):
    """Kembalikan (skor_bonus, label_kanal). Kosong = tidak ada jalur hadiah."""
    t = (sec + " " + readme_text)
    low = t.lower()
    chan = next((v for k, v in PAY.items() if k in low), "")
    if not chan and "security@" in low:
        chan = "email"
    monies = [float(m.replace(",", "")) for m in MONEY_RE.findall(t)]
    big = max(monies) if monies else 0
    says_pay = any(k in low for k in ("bounty", "reward", "bug hunt", "payout", "compensation"))
    if chan and big >= 1000:
        return 6, f"{chan} (max {int(big)})"
    if chan:
        return 4, chan
    if says_pay and big >= 1000:
        return 4, f"direct (max {int(big)})"
    if says_pay:
        return 3, "direct/bounty"
    return 1, "security.md saja"


W = [r"\bfee", "vault", "treasury", "curve", "swap", "amm", "pool", "stake",
     "escrow", "bonding", "lending", "royalt", "reward"]
HOT = ["mainnet", "program", "anchor", "deployed", "verifiable"]
BAD = ["test", "tutorial", "example", "course", "bootcamp", "prereq",
       "security advisories", "reverse-engineer", "analyzer", "writeup", "hall of fame",
       "profile", "collection", "curated", "tracker", "aggregator", "cli", "toolkit",
       "cheat sheet", "awesome", "list of", "newsletter", "blog"]

items = {}
for q in ["language:Rust solana", "language:Rust bonding curve", "language:Rust anchor program",
          "language:Solidity vault", "language:Solidity staking",
          "bug bounty in:readme language:Rust", "bug bounty in:readme language:Solidity",
          "immunefi in:readme", "audit competition in:readme"]:
    since = (datetime.date.today() - datetime.timedelta(days=4)).isoformat()
    qs = urllib.parse.quote(f"{q} created:>{since}")
    try:
        for i in gh(f"/search/repositories?q={qs}&sort=updated&order=desc&per_page=12")["items"]:
            items[i["full_name"]] = i
    except Exception as e:
        print("query fail", q, str(e)[:60])

rows = []
for full, i in items.items():
    if full in seen:
        continue
    readme_text = readme(full)
    text = ((i.get("description") or "") + " " + readme_text).lower()
    sec = sec_text(full)
    bonus, chan = (0, "-") if not sec else bounty_signal(sec, "")
    score = sum(2 for k in W if k in text) + sum(3 for k in HOT if k in text) \
          - sum(5 for k in BAD if k in text)
    has_audit_word = "audit" in text and "security.md" not in text
    if has_audit_word:
        score -= 2
    score += bonus
    if score >= 3 and bonus >= 3 and has_contract_code(full):          # hanya target yang punya jalur hadiah
        rows.append((score, full, (i.get("description") or "")[:110],
                     "mainnet" if "mainnet" in text else "-", chan))

new_names = sorted(i for i in items if i not in seen)
if not rows:
    body = f"_radar {datetime.date.today()} — {len(new_names)} repo baru, nggak ada yang lolos skor._\n"
else:
    body = f"## 🎯 BB-radar {datetime.date.today()}\n\n| score | repo | catatan | live | channel |\n|---|---|---|---|---|\n"
    for score, full, desc, live, chan in sorted(rows, reverse=True):
        body += f"| {score} | `{full}` | {desc} | {live} | {chan} |\n"

open(LATEST_F, "w").write(body)
seen |= set(items)
json.dump(sorted(seen), open(SEEN_F, "w"))
print(body)
