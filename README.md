# GitHub Tech Radar (Data Engineering)

Pipeline que coleta métricas da API do GitHub (repos de engenharia de dados) e publica um dashboard Power BI com:
- Atividade (commits 30d)
- Bus Factor (Top1/Top3 %)
- Qualidade/Processo (lead time de issues)
- Linguagens (composição por bytes)

## Como rodar
```bash
export GITHUB_TOKEN=SEU_PAT
python build_repo_list_from_search.py
python github_radar_etl.py


## Como trabalhar
- Edite no `.pbix` local.
- Ao finalizar um bloco: **Export → .pbit** e faça commit do `.pbit`.
- Releases esporádicas: gere `.pbix` e anexe em **GitHub Releases** (tag vX.Y.Z).

## Como recriar localmente
1. Rode o ETL (gera `out/*.csv`)
2. Abra `powerbi/GitHub_Tech_Radar.pbit`
3. Informe o parâmetro `OutFolderPath`
4. O Power BI cria um `.pbix` novo com seus dados locais
