"""
03_painel.py — Gera o site (docs/index.html) a partir de painel/template.html.

  python 03_painel.py

O HTML leva embutido só o que é fixo: as malhas dos mapas (estados, regiões imediatas, mesorregiões e
mundo), a lista de municípios (para a busca do "Meu lugar") e o logo. Os dados de cada dia ficam em
docs/dados/*.json, que o site lê ao abrir. Por isso este script só precisa rodar quando o visual
(template) mudar. Precisa do geopandas; o GitHub Actions não usa este script.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re

import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient

from clima_comum import COD_UF, RAIZ, RAW, REF

PAINEL = RAIZ / "painel"
GEO = RAW / "geo"   # malhas baixadas pelo 00_referencias.py
GOATCOUNTER = "ladri"   # contador anônimo de acessos (o mesmo do painel Eleições 2026; o endereço do site separa os dois)
REPO = "https://github.com/ladriasces/Monitor-El-Nino"


# ---------------------------------------------------------------- malhas compactas para o D3
def sentido_d3(g):
    """Orienta os polígonos como o D3 espera (anel externo no sentido horário).

    Pedaços sem área (ilhas que somem na simplificação) são descartados: o D3 os interpretaria
    como o globo inteiro."""
    partes = [g] if isinstance(g, Polygon) else list(g.geoms) if isinstance(g, MultiPolygon) else []
    partes = [orient(p, sign=-1.0) for p in partes if p.area > 0]
    if not partes:
        return g
    return partes[0] if len(partes) == 1 else MultiPolygon(partes)


def geo_compacto(gdf: gpd.GeoDataFrame, tolerancia: float, casas: int = 3) -> dict:
    """Simplifica as geometrias, arredonda as coordenadas e devolve um GeoJSON pequeno para o navegador.

    tolerancia: quanto simplificar (em graus); casas: casas decimais das coordenadas."""
    gdf = gdf.copy()
    simpl = shapely.set_precision(gdf.geometry.simplify(tolerancia, preserve_topology=True).values, 10 ** -casas)
    gdf["geometry"] = gpd.GeoSeries(simpl, index=gdf.index, crs=gdf.crs).map(sentido_d3)
    gj = json.loads(gdf.to_json(drop_id=True))

    def arred(c):
        return [arred(x) for x in c] if isinstance(c[0], list) else [round(c[0], casas), round(c[1], casas)]

    for f in gj["features"]:
        f["geometry"]["coordinates"] = arred(f["geometry"]["coordinates"])
    return gj


# ---------------------------------------------------------------- site
def base() -> dict:
    """Monta os dados fixos embutidos no site: malhas, códigos de países e listas de lugares."""
    uf = gpd.read_file(GEO / "br_uf.geojson")
    uf["id"] = uf.codarea.astype(int).map(COD_UF)
    imed = gpd.read_file(GEO / "br_imediatas.geojson").rename(columns={"codarea": "id"})
    meso = gpd.read_file(GEO / "br_meso.geojson").rename(columns={"codarea": "id"})
    mundo = gpd.read_file(GEO / "mundo.geojson")
    mundo = mundo[mundo.ADM0_A3 != "ATA"]   # sem a Antártida
    # Código ISO de 2 letras de cada país (para o navegador escrever o nome em português)
    iso2 = {a3: a2 for a3, a2 in zip(mundo.ADM0_A3, mundo.get("ISO_A2_EH", mundo.get("ISO_A2")))
            if isinstance(a2, str) and len(a2) == 2}

    ri = pd.read_csv(REF / "regioes_imediatas.csv", dtype={"id": str})
    mun = pd.read_csv(REF / "municipios.csv", dtype=str)
    me = pd.read_csv(REF / "mesorregioes.csv", dtype=str)
    return {
        "geo": {
            "uf": geo_compacto(uf[["id", "geometry"]], 0.02),
            "imed": geo_compacto(imed[["id", "geometry"]], 0.008),
            "meso": geo_compacto(meso[["id", "geometry"]], 0.01),
            "mundo": geo_compacto(mundo[["ADM0_A3", "geometry"]].rename(columns={"ADM0_A3": "id"}), 0.1, 2),
        },
        "iso2": iso2,
        "imed": [[t.id, t.nome, t.uf] for t in ri.itertuples()],                      # [id, nome, uf]
        "meso": [[t.id, t.nome, t.uf] for t in me.itertuples()],                      # [id, nome, uf]
        "mun": [[t.ibge, t.nome, t.uf, t.imediata, t.meso if isinstance(t.meso, str) else None]
                for t in mun.itertuples()],                                           # [ibge, nome, uf, região imediata, mesorregião]
    }


def politica_seguranca(script: str) -> str:
    """Política de segurança de conteúdo (CSP): o navegador só executa o script do painel (autorizado
    pelo hash exato do conteúdo), o D3 do cdnjs (com verificação de integridade no template) e o
    contador anônimo. Qualquer script injetado é bloqueado."""
    hash_script = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
    gc = f"https://{GOATCOUNTER}.goatcounter.com"
    return ("default-src 'self'; "
            f"script-src 'sha256-{hash_script}' https://cdnjs.cloudflare.com https://gc.zgo.at; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
            f"img-src 'self' data: {gc}; connect-src 'self' {gc}; "
            "object-src 'none'; base-uri 'none'; form-action 'none'")


def main() -> None:
    """Preenche o template com os dados fixos e grava docs/index.html."""
    dados = base()
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    logo = base64.b64encode((PAINEL / "logo_ladri.png").read_bytes()).decode("ascii")
    corpo = ((PAINEL / "template.html").read_text(encoding="utf-8")
             .replace("/*__BASE__*/null", texto).replace("__LOGO__", f"data:image/png;base64,{logo}")
             .replace("__REPO__", REPO)
             .replace('<meta charset="utf-8">\n', "", 1))
    fim_head = corpo.index("</style>") + len("</style>")
    cabeca, resto = corpo[:fim_head], corpo[fim_head:]
    scripts = re.findall(r"<script>(.*?)</script>", resto, flags=re.S)
    if len(scripts) != 1:
        raise RuntimeError(f"esperava 1 script embutido no template, achei {len(scripts)}")
    pagina = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{politica_seguranca(scripts[0])}">
<meta name="referrer" content="strict-origin-when-cross-origin">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="Monitor El Niño: acompanhe o fenômeno, a chuva, a temperatura, as queimadas, os alertas e as notícias sobre o clima no Brasil e no mundo, com dados abertos atualizados todo dia. LADRI · ASCES-UNITA.">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%232f6b45'/%3E%3Cpath d='M5 19c3-6 6-6 9 0s6 6 9 0 4-4 4-4' stroke='white' stroke-width='3' fill='none' stroke-linecap='round'/%3E%3C/svg%3E">
<style>[hidden] {{ display: none !important; }} img {{ max-width: 100%; }}</style>
<script data-goatcounter="https://{GOATCOUNTER}.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>
{cabeca}
</head>
<body>
{resto}
</body>
</html>
"""
    destino = RAIZ / "docs" / "index.html"
    destino.parent.mkdir(exist_ok=True)
    # newline="\n": no Windows o Python gravaria "\r\n", o script mudaria e o hash da CSP deixaria de valer
    destino.write_text(pagina, encoding="utf-8", newline="\n")
    print(f"docs/index.html gerado: {len(pagina.encode('utf-8')) / 1e6:.2f} MB (dados fixos {len(texto.encode('utf-8')) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
