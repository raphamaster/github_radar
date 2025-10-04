import os, csv, time
from datetime import datetime, timedelta
import requests

# =========================
# CONFIG
# =========================
# Termos/temas para buscar (pode ajustar livremente):
QUERIES = [
    'data engineering',               # amplo
    'ETL OR ELT',                     # pipelines
    'airflow OR "apache airflow"',    # orquestração
    'dbt OR "dbt-core"',              # transformação
    'duckdb',                         # query engine moderna
    '"great expectations" OR "data quality"',  # qualidade de dados
    'kafka OR "apache kafka"',        # streaming
    'delta lake OR "delta-io"',       # lakehouse
]

# linguagens/qualificadores adicionais (opcionais)
LANG = 'language:Python'   # troque/adicione: language:SQL, language:Go, etc.
EXTRA_QUALS = 'fork:false' # descarta forks no resultado da busca

STARS_MIN = 100            # estrelas mínimas
PUSHED_SINCE_DAYS = 180    # atividade recente (últimos N dias)
PER_PAGE = 100             # máximo por página
MAX_PAGES = 2              # até 200 por query (ajuste se quiser)

OUT_LIST = 'repo_list.csv'     # lista mínima pro ETL
OUT_CATALOG = 'repo_catalog.csv'  # catálogo com metadados

# =========================
# SETUP
# =========================
TOKEN = os.getenv("GITHUB_TOKEN")
if not TOKEN:
    raise SystemExit("Defina GITHUB_TOKEN com seu PAT do GitHub.")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

base_url = "https://api.github.com/search/repositories"
pushed_since = (datetime.utcnow() - timedelta(days=PUSHED_SINCE_DAYS)).date().isoformat()

def search_repos(query):
    """Busca repositórios com paginação e filtros globais."""
    results = []
    # Monta a query final com qualificadores
    # Ex.: q='data engineering language:Python stars:>100 pushed:>2025-04-05 fork:false'
    q = f'{query} {LANG} stars:>{STARS_MIN} pushed:>{pushed_since} {EXTRA_QUALS}'
    for page in range(1, MAX_PAGES + 1):
        params = {"q": q, "sort": "stars", "order": "desc", "per_page": PER_PAGE, "page": page}
        resp = requests.get(base_url, headers=HEADERS, params=params, timeout=30)
        if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
            # Atingiu rate limit de busca (30 req/min). Espera até reset.
            reset = int(resp.headers.get("X-RateLimit-Reset", "0"))
            wait = max(0, reset - int(time.time())) + 1
            print(f"[rate limit] aguardando {wait}s…")
            time.sleep(wait)
            resp = requests.get(base_url, headers=HEADERS, params=params, timeout=30)

        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        results.extend(items)
        if len(items) < PER_PAGE:
            break
        time.sleep(1)  # polidez
    return results

def main():
    print(f"Buscando com pushed:>{pushed_since}, stars:>{STARS_MIN}, {LANG} …")

    seen = set()
    catalog = []

    for q in QUERIES:
        print(f"\n== Query: {q}")
        items = search_repos(q)
        print(f"  {len(items)} itens brutos")

        for it in items:
            full = it.get("full_name") or ""
            if not full or full in seen:
                continue
            seen.add(full)

            catalog.append({
                "owner": full.split("/")[0],
                "repo": full.split("/")[1] if "/" in full else "",
                "full_name": full,
                "html_url": it.get("html_url"),
                "description": (it.get("description") or "").replace("\n", " ")[:1000],
                "language": it.get("language"),
                "stargazers_count": it.get("stargazers_count"),
                "forks_count": it.get("forks_count"),
                "open_issues_count": it.get("open_issues"),
                "archived": it.get("archived"),
                "created_at": it.get("created_at"),
                "updated_at": it.get("updated_at"),
                "pushed_at": it.get("pushed_at"),
            })

    # Ordena por estrelas desc
    catalog.sort(key=lambda r: (r["stargazers_count"] or 0), reverse=True)

    # Escreve repo_list.csv (owner,repo)
    with open(OUT_LIST, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["owner", "repo"])
        for r in catalog:
            w.writerow([r["owner"], r["repo"]])
    print(f"[ok] {OUT_LIST} ({len(catalog)} linhas)")

    # Escreve repo_catalog.csv com metadados
    with open(OUT_CATALOG, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["owner","repo","full_name","html_url","description","language",
                      "stargazers_count","forks_count","open_issues_count","archived",
                      "created_at","updated_at","pushed_at"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in catalog:
            w.writerow(r)
    print(f"[ok] {OUT_CATALOG} ({len(catalog)} linhas)")

if __name__ == "__main__":
    main()
