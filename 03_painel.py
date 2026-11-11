"""
03_painel.py — Gera docs/index.html (site do GitHub Pages) a partir de painel/template.html.

Embute no HTML só o que é fixo: malhas (estados, regiões imediatas, mesorregiões, mundo), a lista de
municípios (para o "Meu lugar") e o logo. Os dados do dia ficam em docs/dados/*.json, que o painel
lê ao abrir e que o GitHub Actions regrava todo dia — por isso este script só precisa rodar de novo
quando o template mudar.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re

import geopandas as gpd
import pandas as pd

from clima_comum import COD_UF, RAIZ, RAW, REF
from geo_comum import geo_compacto

PAINEL = RAIZ / "painel"
GEO = RAW / "geo"
GOATCOUNTER = "ladri"   # contador anônimo de acessos (o mesmo do painel Eleições 2026; o caminho do site separa os dois)
REPO = "https://github.com/ladriasces/Monitor-El-Nino"


def base() -> dict:
    uf = gpd.read_file(GEO / "br_uf.geojson")
    uf["id"] = uf.codarea.astype(int).map(COD_UF)
    imed = gpd.read_file(GEO / "br_imediatas.geojson").rename(columns={"codarea": "id"})
    meso = gpd.read_file(GEO / "br_meso.geojson").rename(columns={"codarea": "id"})
    mundo_full = gpd.read_file(GEO / "mundo.geojson")
    mundo_full = mundo_full[mundo_full.ADM0_A3 != "ATA"]
    mundo = mundo_full[["ADM0_A3", "geometry"]].rename(columns={"ADM0_A3": "id"})
    # Código ISO de 2 letras (para o navegador escrever o nome do país em português)
    iso2 = {a3: a2 for a3, a2 in zip(mundo_full.ADM0_A3, mundo_full.get("ISO_A2_EH", mundo_full.get("ISO_A2")))
            if isinstance(a2, str) and len(a2) == 2}

    ri = pd.read_csv(REF / "regioes_imediatas.csv", dtype={"id": str})
    mun = pd.read_csv(REF / "municipios.csv", dtype=str)
    me = pd.read_csv(REF / "mesorregioes.csv", dtype=str)
    return {
        "geo": {
            "uf": geo_compacto(uf[["id", "geometry"]], 0.02),
            "imed": geo_compacto(imed[["id", "geometry"]], 0.008),
            "meso": geo_compacto(meso[["id", "geometry"]], 0.01),
            "mundo": geo_compacto(mundo, 0.1, 2),
        },
        "iso2": iso2,
        # [id, nome, uf]
        "imed": [[t.id, t.nome, t.uf] for t in ri.itertuples()],
        "meso": [[t.id, t.nome, t.uf] for t in me.itertuples()],
        # [ibge, nome, uf, região imediata, mesorregião]
        "mun": [[t.ibge, t.nome, t.uf, t.imediata, t.meso if isinstance(t.meso, str) else None] for t in mun.itertuples()],
    }


def main() -> None:
    dados = base()
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    logo = base64.b64encode((PAINEL / "logo_ladri.png").read_bytes()).decode("ascii")
    corpo = ((PAINEL / "template.html").read_text(encoding="utf-8")
             .replace("/*__BASE__*/null", texto).replace("__LOGO__", f"data:image/png;base64,{logo}")
             .replace("__REPO__", REPO))
    corpo = corpo.replace('<meta charset="utf-8">\n', "", 1)
    fim_head = corpo.index("</style>") + len("</style>")
    cabeca, resto = corpo[:fim_head], corpo[fim_head:]
    # Política de segurança de conteúdo: o navegador só executa o script do painel (pelo hash exato),
    # o D3 do cdnjs (com verificação de integridade) e o contador anônimo; nada de scripts injetados.
    inline = re.findall(r"<script>(.*?)</script>", resto, flags=re.S)
    if len(inline) != 1:
        raise RuntimeError(f"esperava 1 script embutido no template, achei {len(inline)}")
    hash_script = base64.b64encode(hashlib.sha256(inline[0].encode("utf-8")).digest()).decode("ascii")
    gc = f"https://{GOATCOUNTER}.goatcounter.com"
    csp = ("default-src 'self'; "
           f"script-src 'sha256-{hash_script}' https://cdnjs.cloudflare.com https://gc.zgo.at; "
           "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
           f"img-src 'self' data: {gc}; connect-src 'self' {gc}; "
           "object-src 'none'; base-uri 'none'; form-action 'none'")
    pagina = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<meta name="referrer" content="strict-origin-when-cross-origin">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="Monitor El Niño: acompanhe o fenômeno, a chuva, a temperatura, as queimadas, os alertas e as notícias sobre o clima no Brasil e no mundo, com dados abertos atualizados todo dia. LADRI · ASCES-UNITA.">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%23c8382a'/%3E%3Cpath d='M5 19c3-6 6-6 9 0s6 6 9 0 4-4 4-4' stroke='white' stroke-width='3' fill='none' stroke-linecap='round'/%3E%3C/svg%3E">
<style>[hidden] {{ display: none !important; }} img {{ max-width: 100%; }}</style>
<script data-goatcounter="https://{GOATCOUNTER}.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>
{cabeca}
</head>
<body>
{resto}
</body>
</html>
"""
    docs = RAIZ / "docs"
    docs.mkdir(exist_ok=True)
    # newline="\n": no Windows o Python gravaria "\r\n", o conteúdo do script mudaria e o hash da CSP não bateria
    (docs / "index.html").write_text(pagina, encoding="utf-8", newline="\n")
    (docs / ".nojekyll").write_text("", encoding="utf-8")
    print(f"docs/index.html gerado: {len(pagina.encode('utf-8')) / 1e6:.2f} MB (base {len(texto.encode('utf-8')) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
