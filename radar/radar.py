#!/usr/bin/env python3
"""Daily bug-bounty target radar (GitHub Actions free tier).
Finds freshly-published contract repos, scores money-path signals, dedupes vs
radar/seen.json, writes radar/latest.md and commits both back."""
import base64, datetime, json, os, urllib.parse, urllib.request

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

W = [r"\bfee", "vault", "treasury", "curve", "swap", "amm", "pool", "stake",
     "escrow", "bonding", "lending", "royalt", "reward"]
HOT = ["mainnet", "program", "anchor", "deployed", "verifiable"]
BAD = ["test", "tutorial", "example", "course", "bootcamp", "prereq",
       "security advisories", "reverse-engineer", "analyzer"]

items = {}
for q in ["language:Rust solana", "language:Rust bonding curve", "language:Rust anchor program",
          "language:Solidity vault", "language:Solidity staking"]:
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
    text = ((i.get("description") or "") + " " + readme(full)).lower()
    score = sum(2 for k in W if k in text) + sum(3 for k in HOT if k in text) \
          - sum(5 for k in BAD if k in text)
    has_audit_word = "audit" in text and "security.md" not in text
    if has_audit_word:
        score -= 2
    if score >= 3:
        rows.append((score, full, (i.get("description") or "")[:110],
                     "mainnet" if "mainnet" in text else "-",
                     "SECURITY.md" if "security.md" in text else "-"))

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
