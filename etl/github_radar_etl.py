
import os, csv, time, sys
from datetime import datetime, timedelta
import requests
from pathlib import Path
from dotenv import load_dotenv

# === Paths base ===
THIS = Path(__file__).resolve()
ROOT = THIS.parents[1]                  # raiz do repo
OUT_DIR = ROOT / "out"                  # saída unificada
OUT_DIR.mkdir(parents=True, exist_ok=True)

# .env na raiz
load_dotenv(ROOT / ".env")


# ===== CONFIG =====
INPUT_CSV = OUT_DIR / "repo_list.csv"
OUT_DIR = "out"
DAYS_COMMITS = 30      # janela de commits
DAYS_ISSUES  = 60      # janela de issues fechadas
PER_PAGE = 100         # paginação máxima na API
SLEEP_BETWEEN_CALLS = 0.5  # polidez / evitar throttling

TOKEN = os.getenv("GITHUB_TOKEN")
if not TOKEN:
    print("Erro: defina a variável de ambiente GITHUB_TOKEN com seu PAT do GitHub.")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
}

os.makedirs(OUT_DIR, exist_ok=True)

# ===== HELPERS =====
def gh_get(url, params=None):
    """GET com retry básico e respeito a rate limit."""
    params = params or {}
    max_retries = 5
    backoff = 2
    for attempt in range(1, max_retries + 1):
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30)

        # Rate limit?
        if resp.status_code == 403:
            try:
                data = resp.json()
            except Exception:
                data = {}
            reset = resp.headers.get("X-RateLimit-Reset")
            remaining = resp.headers.get("X-RateLimit-Remaining")
            if remaining == "0" and reset:
                wait = max(0, int(reset) - int(time.time())) + 1
                print(f"[rate limit] Aguardando {wait}s até reset…")
                time.sleep(wait)
                continue
            print(f"[403] {data}. Tentativa {attempt}/{max_retries}; aguardando {backoff}s…")
            time.sleep(backoff); backoff *= 2
            continue

        if resp.status_code in (500, 502, 503, 504):
            print(f"[{resp.status_code}] Tentativa {attempt}/{max_retries}; aguardando {backoff}s…")
            time.sleep(backoff); backoff *= 2
            continue

        if resp.ok:
            time.sleep(SLEEP_BETWEEN_CALLS)
            return resp.json()

        print(f"[{resp.status_code}] {resp.text}")
        time.sleep(backoff); backoff *= 2

    resp.raise_for_status()

def gh_paged(url, since_iso=None):
    """Itera paginação (issues/commits/contributors). Usa 'since' quando aplicável."""
    page = 1
    while True:
        params = {"per_page": PER_PAGE, "page": page}
        if since_iso:
            params["since"] = since_iso
        data = gh_get(url, params=params)
        if not isinstance(data, list) or len(data) == 0:
            break
        for item in data:
            yield item
        if len(data) < PER_PAGE:
            break
        page += 1

def parse_iso(dt_str):
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None

# ===== COLETORES =====
def fetch_repo_meta(owner, repo):
    url = f"https://api.github.com/repos/{owner}/{repo}"
    return gh_get(url)

def fetch_repo_languages(owner, repo):
    url = f"https://api.github.com/repos/{owner}/{repo}/languages"
    return gh_get(url)

def fetch_contributors(owner, repo):
    url = f"https://api.github.com/repos/{owner}/{repo}/contributors"
    return list(gh_paged(url))

def fetch_commits(owner, repo, since_iso):
    url = f"https://api.github.com/repos/{owner}/{repo}/commits"
    return list(gh_paged(url, since_iso=since_iso))

def fetch_closed_issues(owner, repo, since_iso):
    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    items = []
    page = 1
    while True:
        params = {"per_page": PER_PAGE, "page": page, "state": "closed", "since": since_iso}
        data = gh_get(url, params=params)
        if not isinstance(data, list) or len(data) == 0:
            break
        items.extend(data)
        if len(data) < PER_PAGE:
            break
        page += 1
    # filtra apenas issues (a API mistura PRs)
    return [i for i in items if "pull_request" not in i]

# ===== EXECUÇÃO =====
now = datetime.utcnow()
since_commits = (now - timedelta(days=DAYS_COMMITS)).isoformat() + "Z"
since_issues  = (now - timedelta(days=DAYS_ISSUES)).isoformat() + "Z"

repo_meta_rows = []
repo_lang_rows = []
repo_contrib_rows = []
repo_activity_rows = []   # commits por dia
repo_issue_rows = []

with open(INPUT_CSV, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        owner, repo = row["owner"].strip(), row["repo"].strip()
        repo_key = f"{owner}/{repo}"
        print(f"\n=== {repo_key} ===")

        # 1) Metadados
        meta = fetch_repo_meta(owner, repo)
        repo_meta_rows.append({
            "owner": owner,
            "repo": repo,
            "full_name": meta.get("full_name"),
            "description": (meta.get("description") or "")[:1000],
            "created_at": meta.get("created_at"),
            "updated_at": meta.get("updated_at"),
            "pushed_at": meta.get("pushed_at"),
            "stargazers_count": meta.get("stargazers_count"),
            "forks_count": meta.get("forks_count"),
            "open_issues_count": meta.get("open_issues_count"),
            "subscribers_count": meta.get("subscribers_count"),
            "default_branch": meta.get("default_branch"),
            "language": meta.get("language"),
            "license": (meta.get("license") or {}).get("spdx_id"),
            "archived": meta.get("archived"),
            "disabled": meta.get("disabled"),
            "visibility": meta.get("visibility"),
            "html_url": meta.get("html_url")
        })

        # 2) Linguagens
        langs = fetch_repo_languages(owner, repo) or {}
        for lang, bytes_count in langs.items():
            repo_lang_rows.append({
                "owner": owner, "repo": repo, "language": lang, "bytes": bytes_count
            })

        # 3) Contribuidores (bus factor)
        contribs = fetch_contributors(owner, repo)
        for c in contribs:
            repo_contrib_rows.append({
                "owner": owner, "repo": repo,
                "login": c.get("login"),
                "contributions": c.get("contributions")
            })

        # 4) Commits (atividade diária)
        commits = fetch_commits(owner, repo, since_commits)
        day_counts = {}
        for cm in commits:
            commit = cm.get("commit", {})
            author = commit.get("author") or {}
            dt = parse_iso(author.get("date") or commit.get("committer", {}).get("date") or "")
            if not dt:
                continue
            day = dt.date().isoformat()
            day_counts[day] = day_counts.get(day, 0) + 1
        for d, cnt in sorted(day_counts.items()):
            repo_activity_rows.append({
                "owner": owner, "repo": repo, "date": d, "commits": cnt
            })

        # 5) Issues fechadas (lead time)
        issues = fetch_closed_issues(owner, repo, since_issues)
        for it in issues:
            created_at = parse_iso(it.get("created_at") or "")
            closed_at  = parse_iso(it.get("closed_at") or "")
            lead_time_days = None
            if created_at and closed_at:
                lead_time_days = (closed_at - created_at).total_seconds() / 86400.0
            repo_issue_rows.append({
                "owner": owner, "repo": repo, "number": it.get("number"),
                "title": (it.get("title") or "")[:300],
                "created_at": it.get("created_at"),
                "closed_at": it.get("closed_at"),
                "lead_time_days": round(lead_time_days, 2) if lead_time_days is not None else None,
                "labels": ",".join([lb.get("name") for lb in it.get("labels", []) if lb.get("name")])
            })

# ===== SALVA =====
def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"[ok] {path} ({len(rows)} linhas)")

write_csv(
    os.path.join(OUT_DIR, "repo_meta.csv"),
    repo_meta_rows,
    ["owner","repo","full_name","description","created_at","updated_at","pushed_at",
     "stargazers_count","forks_count","open_issues_count","subscribers_count","default_branch",
     "language","license","archived","disabled","visibility","html_url"]
)

write_csv(
    os.path.join(OUT_DIR, "repo_languages.csv"),
    repo_lang_rows,
    ["owner","repo","language","bytes"]
)

write_csv(
    os.path.join(OUT_DIR, "repo_contributors.csv"),
    repo_contrib_rows,
    ["owner","repo","login","contributions"]
)

write_csv(
    os.path.join(OUT_DIR, "repo_commits_daily.csv"),
    repo_activity_rows,
    ["owner","repo","date","commits"]
)

write_csv(
    os.path.join(OUT_DIR, "repo_issues_closed.csv"),
    repo_issue_rows,
    ["owner","repo","number","title","created_at","closed_at","lead_time_days","labels"]
)

print("\nConcluído. Importe os CSVs no Power BI e modele os relacionamentos.")
