"""
00_referencias.py — Monta, uma única vez, as tabelas de referência da plataforma (data/ref/).
Roda no computador do LADRI (precisa do geopandas: pip install geopandas); o resultado vai para o repositório.

  python 00_referencias.py                 # tudo o que ainda não existe
  python 00_referencias.py --refazer focos # refaz uma etapa (malhas|locais|normais|focos)

Etapas:
  malhas  IBGE (estados, regiões imediatas, mesorregiões) e Natural Earth (mundo) -> data/raw/geo/
  locais  municípios, regiões imediatas (com centroide) e mesorregiões -> data/ref/*.csv
  normais NASA POWER, normais climatológicas 1991–2020 (chuva e temperatura) por região imediata
  focos   INPE, focos de queimada do satélite de referência (AQUA_M-T): 2003–2025 (arquivos anuais)
          e o ano corrente (arquivos mensais) -> data/ref/focos_*.csv
"""
from __future__ import annotations

import argparse
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor

import geopandas as gpd
import pandas as pd

from clima_comum import RAW, REF, UF_POR_NOME, agora, baixar, chave

GEO = RAW / "geo"
IBGE = "https://servicodados.ibge.gov.br/api"
INPE = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv"
SAT_REF = "AQUA_M-T"


# ---------------------------------------------------------------- malhas
def malhas() -> None:
    """Baixa as malhas do IBGE (estados, regiões imediatas, mesorregiões) e o mapa-múndi (Natural Earth)."""
    fmt = "formato=application/vnd.geo+json&qualidade=minima"
    for nome, intra in [("br_uf", "UF"), ("br_imediatas", "regiao-imediata"), ("br_meso", "mesorregiao")]:
        baixar(f"{IBGE}/v3/malhas/paises/BR?intrarregiao={intra}&{fmt}", GEO / f"{nome}.geojson", cache=True, timeout=180)
    baixar("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson",
           GEO / "mundo.geojson", cache=True)
    print("Malhas: ok")


# ---------------------------------------------------------------- locais
def locais() -> None:
    """Monta as tabelas de lugares a partir da API de localidades do IBGE:
    municipios.csv (município -> estado, região imediata, mesorregião), regioes_imediatas.csv (com o
    ponto representativo usado nas consultas de clima) e mesorregioes.csv (para ligar os avisos do INMET)."""
    muns = json.loads(baixar(f"{IBGE}/v1/localidades/municipios", GEO / "ibge_municipios.json", cache=True))
    imeds = json.loads(baixar(f"{IBGE}/v1/localidades/regioes-imediatas", GEO / "ibge_imediatas.json", cache=True))
    mesos = json.loads(baixar(f"{IBGE}/v1/localidades/mesorregioes", GEO / "ibge_meso.json", cache=True))

    linhas = []
    for m in muns:
        ri = m.get("regiao-imediata") or {}
        mi = m.get("microrregiao") or {}
        me = mi.get("mesorregiao") or {}
        uf = (ri.get("regiao-intermediaria") or {}).get("UF") or me.get("UF") or {}
        linhas.append({"ibge": str(m["id"]), "nome": m["nome"], "uf": uf.get("sigla"),
                       "imediata": str(ri.get("id", "")), "meso": str(me.get("id", "")) or None})
    mun = pd.DataFrame(linhas)
    REF.mkdir(parents=True, exist_ok=True)
    mun.to_csv(REF / "municipios.csv", index=False)

    ri = pd.DataFrame([{"id": str(x["id"]), "nome": x["nome"], "uf": x["regiao-intermediaria"]["UF"]["sigla"]} for x in imeds])
    geo = gpd.read_file(GEO / "br_imediatas.geojson").rename(columns={"codarea": "id"})
    pt = geo.geometry.representative_point()
    geo["lon"], geo["lat"] = pt.x.round(3), pt.y.round(3)
    ri = ri.merge(geo[["id", "lat", "lon"]], on="id", how="left")
    ri["n_mun"] = ri.id.map(mun.imediata.value_counts()).fillna(0).astype(int)
    faltam = ri[ri.lat.isna()]
    if len(faltam):
        print("Regiões imediatas sem geometria:", faltam.nome.tolist())
    ri.sort_values("id").to_csv(REF / "regioes_imediatas.csv", index=False)

    me = pd.DataFrame([{"id": str(x["id"]), "nome": x["nome"], "uf": x["UF"]["sigla"]} for x in mesos])
    me["chave"] = me.nome.map(chave)
    me.sort_values("id").to_csv(REF / "mesorregioes.csv", index=False)
    print(f"Locais: {len(mun)} municípios, {len(ri)} regiões imediatas, {len(me)} mesorregiões")


# ---------------------------------------------------------------- normais
POWER_CLIM = "https://power.larc.nasa.gov/api/temporal/climatology/point"
MESES = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _normal(linha) -> list[dict]:
    """Normais mensais 1991–2020 de chuva (mm/dia) e temperatura (°C) de uma região imediata."""
    p = {"parameters": "PRECTOTCORR,T2M", "community": "AG", "longitude": linha.lon, "latitude": linha.lat,
         "start": 1991, "end": 2020, "format": "JSON"}
    d = json.loads(baixar(POWER_CLIM, params=p, timeout=120))["properties"]["parameter"]
    return [{"id": linha.id, "var": var, **{f"m{i + 1}": d[var][m] for i, m in enumerate(MESES)}}
            for var in ("PRECTOTCORR", "T2M")]


def normais() -> None:
    """Grava normais_power.csv: a régua de comparação (1991–2020) de cada uma das 510 regiões imediatas.
    Vem do mesmo produto (NASA POWER) dos dados diários, para a comparação ser coerente."""
    ri = pd.read_csv(REF / "regioes_imediatas.csv", dtype={"id": str})
    with ThreadPoolExecutor(max_workers=4) as pool:
        res = list(pool.map(_normal, ri.itertuples()))
    df = pd.DataFrame([x for lst in res for x in lst])
    df.to_csv(REF / "normais_power.csv", index=False)
    print(f"Normais NASA POWER 1991–2020: {df.id.nunique()} regiões imediatas")


# ---------------------------------------------------------------- focos
def _uf(nome) -> str | None:
    """Sigla do estado a partir do nome por extenso usado pelo INPE (ex.: "PARÁ" -> "PA")."""
    return UF_POR_NOME.get(chave(nome))


def _ler_csv(conteudo: bytes, **kw) -> pd.DataFrame:
    """Lê um CSV do INPE, que pode vir em UTF-8 ou Latin-1."""
    for enc in ("utf-8", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(conteudo), encoding=enc, **kw)
        except UnicodeDecodeError:
            continue
    raise ValueError("codificação desconhecida")


def focos() -> None:
    """Histórico de focos de queimada do satélite de referência do INPE (AQUA_M-T, o das séries oficiais):
    focos_hist_mensal.csv e focos_hist_diario_br.csv (2003 até o ano passado, arquivos anuais) e
    focos_ref_diario.csv (ano corrente, arquivos mensais; depois o 02_tratamento.py o atualiza todo dia)."""
    ano_atual = agora().year
    mensal, diario = [], []
    for ano in range(2003, ano_atual):
        try:
            z = zipfile.ZipFile(io.BytesIO(baixar(f"{INPE}/anual/Brasil_sat_ref/focos_br_ref_{ano}.zip", timeout=300)))
        except RuntimeError as erro:
            print("  sem arquivo anual:", ano, erro)
            continue
        d = _ler_csv(z.read(z.namelist()[0]), usecols=["data_pas", "estado", "bioma"])
        dt = pd.to_datetime(d.data_pas)
        d["data"], d["ano"], d["mes"] = dt.dt.date, dt.dt.year, dt.dt.month
        d["uf"] = d.estado.map(_uf)
        mensal.append(d.groupby(["ano", "mes", "uf", "bioma"], dropna=False).size().rename("n"))
        diario.append(d.groupby("data").size().rename("n"))
        print(f"  {ano}: {len(d):,} focos (sem UF: {d.uf.isna().sum()})")
    pd.concat(mensal).reset_index().to_csv(REF / "focos_hist_mensal.csv", index=False)
    pd.concat(diario).reset_index().to_csv(REF / "focos_hist_diario_br.csv", index=False)

    # Ano corrente: arquivos mensais (todos os satélites), filtrando o satélite de referência
    partes = []
    for mes in range(1, agora().month + 1):
        url = f"{INPE}/mensal/Brasil/focos_mensal_br_{ano_atual}{mes:02d}.csv"
        d = _ler_csv(baixar(url, timeout=600), usecols=["data_hora_gmt", "satelite", "estado", "bioma"])
        d = d[d.satelite == SAT_REF]
        d["data"] = pd.to_datetime(d.data_hora_gmt).dt.date
        d["uf"] = d.estado.map(_uf)
        partes.append(d.groupby(["data", "uf", "bioma"], dropna=False).size().rename("n"))
        print(f"  {ano_atual}-{mes:02d}: {len(d):,} focos do satélite de referência")
    pd.concat(partes).reset_index().to_csv(REF / "focos_ref_diario.csv", index=False)
    print("Focos: ok")


# Cada etapa e o arquivo que indica que ela já foi feita (só roda de novo com --refazer)
ETAPAS = {"malhas": (malhas, GEO / "mundo.geojson"), "locais": (locais, REF / "mesorregioes.csv"),
          "normais": (normais, REF / "normais_power.csv"), "focos": (focos, REF / "focos_ref_diario.csv")}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Tabelas de referência da plataforma El Niño.")
    ap.add_argument("--refazer", nargs="*", default=[], choices=list(ETAPAS))
    args = ap.parse_args()
    for nome, (fn, marca) in ETAPAS.items():
        if nome in args.refazer or not marca.exists():
            print(f"== {nome}")
            fn()
        else:
            print(f"== {nome}: já existe ({marca.relative_to(REF.parent.parent)})")
