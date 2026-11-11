"""
02_tratamento.py — Transforma os arquivos brutos (data/raw/) nos JSON lidos pelo site (docs/dados/).

  python 02_tratamento.py                  # todos os blocos
  python 02_tratamento.py --bloco focos    # só alguns

Blocos (cada um gera docs/dados/<bloco>.json):
  enso      índice ONI, regiões Niño semana a semana e o status do boletim do NOAA
  pacifico  mapa da anomalia da temperatura do mar no Pacífico (fundo do cabeçalho)
  clima     chuva e temperatura de 30 e 90 dias contra 1991–2020 por região imediata, previsão de 7 dias
            e as séries diárias por estado (docs/dados/serie/<UF>.json)
  focos     queimadas: últimas 48 h, acumulado do ano contra 2003 em diante, estados, biomas e municípios
            (também atualiza a série histórica data/ref/focos_ref_diario.csv)
  avisos    avisos do INMET em vigor, ligados às mesorregiões do IBGE
  mundo     desastres do GDACS e temperatura média global diária
  swic      avisos meteorológicos oficiais graves por país (OMM)
  noticias  manchetes dos últimos 14 dias, com temas, estados e regiões

Se a coleta de uma fonte falhou, ou o bloco dá erro, o JSON anterior é mantido e o site mostra a data
da última atualização bem-sucedida (docs/dados/atualizacao.json).
"""
from __future__ import annotations

import argparse
import html
import re
import traceback
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import pandas as pd
from defusedxml import ElementTree as ET   # XML vindo de fora: protegido contra entidades maliciosas

from clima_comum import (BRT, NOME_UF, RAW, REF, RX_TEMAS, SAIDA, UF_POR_NOME, agora, chave, gravar_json, ler_json, r,
                         url_segura)

SAT_REF = "AQUA_M-T"   # satélite de referência do INPE (o das séries históricas oficiais de queimadas)


# ================================================================ ENSO
def fase_oni(v: float) -> tuple[str, str]:
    """Classificação usual do NOAA: El Niño/La Niña a partir de ±0,5 °C; intensidade pelo valor."""
    if v is None:
        return "indefinido", ""
    a = abs(v)
    if a < 0.5:
        return "neutro", ""
    forca = "fraco" if a < 1.0 else "moderado" if a < 1.5 else "forte" if a < 2.0 else "muito forte"
    return ("el_nino" if v > 0 else "la_nina"), forca


STATUS_CPC = {
    "El Niño Advisory": "Alerta de El Niño: o fenômeno está em curso e deve continuar",
    "La Niña Advisory": "Alerta de La Niña: o fenômeno está em curso e deve continuar",
    "El Niño Watch": "Vigilância de El Niño: condições favoráveis à formação nos próximos meses",
    "La Niña Watch": "Vigilância de La Niña: condições favoráveis à formação nos próximos meses",
    "Final El Niño Advisory": "Fim do El Niño: as condições voltaram à neutralidade",
    "Final La Niña Advisory": "Fim da La Niña: as condições voltaram à neutralidade",
    "Not Active": "Sem alerta: condições neutras",
}


def bloco_enso() -> dict:
    """Índice ONI desde 1950, as regiões Niño semana a semana (desde 2014), a fase atual e o status
    do boletim mensal do NOAA (lido da página do ENSO Diagnostic Discussion)."""
    # ONI: estação de 3 meses, ano, temperatura total, anomalia
    oni = []
    for linha in (RAW / "enso" / "oni.txt").read_text(encoding="utf-8").splitlines()[1:]:
        p = linha.split()
        if len(p) == 4:
            oni.append([p[0], int(p[1]), float(p[3])])
    # Niño semanal (anomalias): Niño 1+2, 3, 3.4, 4 e a temperatura do Niño 3.4
    semanal = []
    for linha in (RAW / "enso" / "semanal.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*(\d{2}[A-Z]{3}\d{4})(.*)", linha)
        if not m:
            continue
        nums = [float(x) for x in re.findall(r"-?\d+\.\d", m.group(2))]
        if len(nums) == 8:
            d = datetime.strptime(m.group(1).title(), "%d%b%Y").date()
            semanal.append([d.isoformat(), nums[1], nums[3], nums[5], nums[7], nums[4]])
    semanal = [s for s in semanal if s[0] >= "2014-01-01"]

    pag = (RAW / "enso" / "discussao.html").read_text(encoding="utf-8", errors="replace")
    texto = html.unescape(re.sub(r"<[^>]+>", " ", pag))
    texto = re.sub(r"\s+", " ", texto)
    trecho_status = texto[texto.find("ENSO Alert System Status"):][:200]
    alerta = next((k for k in sorted(STATUS_CPC, key=len, reverse=True) if k in trecho_status), None)
    sinopse = re.search(r"Synopsis:\s*(.+?\.)\s", texto)
    emitido = re.search(r"issued by\s+CLIMATE PREDICTION CENTER.*?(\d{1,2} [A-Z][a-z]+ \d{4})", texto)
    data_disc = None
    if emitido:
        try:
            data_disc = datetime.strptime(emitido.group(1), "%d %B %Y").date().isoformat()
        except ValueError:
            pass

    ult = oni[-1]
    fase, forca = fase_oni(ult[2])
    return {
        "oni": oni,
        "semanal": semanal,
        "atual": {"estacao": ult[0], "ano": ult[1], "oni": ult[2], "fase": fase, "forca": forca,
                  "nino34_semana": semanal[-1][0] if semanal else None, "nino34": semanal[-1][3] if semanal else None},
        "cpc": {"alerta": alerta, "alerta_pt": STATUS_CPC.get(alerta), "sinopse": sinopse.group(1).strip() if sinopse else None,
                "data": data_disc},
    }


def bloco_pacifico() -> dict:
    """Mapa da anomalia da temperatura do mar no Pacífico (NOAA OISST) para o fundo do cabeçalho.

    A grade original de 0,25° vira uma grade de 1° pela média de cada bloco de 4 × 4 pontos (mais fiel
    e mais suave que pegar um ponto isolado). Um bloco com menos da metade de mar conta como terra (None).
    Valores em décimos de °C, inteiros, para o arquivo ficar pequeno."""
    texto = (RAW / "pacifico.txt").read_text(encoding="utf-8")
    dias = float(re.search(r"^time\[1\]\s*\n\s*([\d.]+)", texto, flags=re.M).group(1))
    data = (datetime(1800, 1, 1) + timedelta(days=dias)).date().isoformat()   # "dias desde 1800-01-01"
    grade = []
    for linha in texto.splitlines():
        m = re.match(r"\[0\]\[(\d+)\], (.*)", linha)
        if m:
            grade.append([None if abs(v) > 30 else v for v in map(float, m.group(2).split(","))])   # -9.97e36 = terra
    if len(grade) != 320 or any(len(l) != 800 for l in grade):
        raise ValueError(f"grade inesperada: {len(grade)} linhas")
    linhas = []
    for i in range(0, 320, 4):
        linha = []
        for j in range(0, 800, 4):
            mar = [v for di in range(4) for v in grade[i + di][j:j + 4] if v is not None]
            linha.append(round(10 * sum(mar) / len(mar)) if len(mar) >= 8 else None)
        linhas.append(linha)
    # Linha 0 = centro 39,5°S; coluna 0 = centro 100,5°E; passo de 1°
    return {"data": data, "lat0": -39.5, "lon0": 100.5, "passo": 1.0, "linhas": linhas}


# ================================================================ clima (NASA POWER) e previsão (Open-Meteo)
def _normais() -> dict:
    """Normais 1991–2020 por (região, variável): lista de 12 médias mensais (chuva em mm/dia, temperatura em °C)."""
    nm = pd.read_csv(REF / "normais_power.csv", dtype={"id": str})
    return {(t.id, t.var): [getattr(t, f"m{i}") for i in range(1, 13)] for t in nm.itertuples()}


def bloco_clima() -> dict:
    """Chuva e temperatura dos últimos 30 e 90 dias contra as normais 1991–2020, por região imediata;
    séries diárias de 120 dias por estado; e a previsão de 7 dias do Open-Meteo."""
    ri = pd.read_csv(REF / "regioes_imediatas.csv", dtype={"id": str})
    NORM = _normais()
    series = {}
    for t in ri.itertuples():
        arq = RAW / "power" / f"{t.id}.json"
        if not arq.exists():
            continue
        par = ler_json(arq)["properties"]["parameter"]
        df = pd.DataFrame({"p": par["PRECTOTCORR"], "t": par["T2M"]})
        df.index = pd.to_datetime(df.index, format="%Y%m%d")
        series[t.id] = df.where(df > -900)
    # Último dia com dados em pelo menos 95% das regiões (o NASA POWER tem ~3 dias de atraso)
    validos = pd.concat([s.p.notna() for s in series.values()], axis=1).mean(axis=1)
    fim = validos[validos >= 0.95].index.max()

    def resumo(rid, df, dias):
        """[chuva, chuva normal, diferença em %, temperatura média, diferença em °C] nos últimos `dias` dias.
        A normal do período soma, dia a dia, a média do mês correspondente."""
        jan = df.loc[fim - timedelta(days=dias - 1):fim]
        meses = jan.index.month
        np_ = sum(NORM[(rid, "PRECTOTCORR")][m - 1] for m in meses)       # mm/dia normais somados = mm no período
        nt = sum(NORM[(rid, "T2M")][m - 1] for m in meses) / len(meses)
        p, t = jan.p.sum(min_count=int(dias * .9)), jan.t.mean()
        anom_p = None if p != p or np_ <= 0 else 100 * (p - np_) / np_
        # Estação seca: com chuva normal muito baixa (< 1/3 mm por dia), a diferença em % não tem sentido
        return [r(p, 1), r(np_, 1), r(anom_p, 0) if np_ >= dias / 3 else None, r(t, 1), r(t - nt, 2) if t == t else None]

    regioes, por_uf = {}, {}
    for t in ri.itertuples():
        if t.id not in series:
            continue
        df = series[t.id]
        regioes[t.id] = resumo(t.id, df, 30) + resumo(t.id, df, 90)
        # Série diária (para o gráfico do "Meu lugar"), separada por estado e carregada só quando pedida
        jan = df.loc[fim - timedelta(days=119):fim]
        norm_p = [r(NORM[(t.id, "PRECTOTCORR")][d.month - 1], 2) for d in jan.index]
        norm_t = [r(NORM[(t.id, "T2M")][d.month - 1], 2) for d in jan.index]
        por_uf.setdefault(t.uf, {})[t.id] = {"p": [r(x, 1) for x in jan.p], "t": [r(x, 1) for x in jan.t],
                                             "np": norm_p, "nt": norm_t}
    ini_serie = (fim - timedelta(days=119)).date().isoformat()
    for uf, dados in por_uf.items():
        gravar_json({"ini": ini_serie, "regioes": dados}, SAIDA / "serie" / f"{uf}.json")

    # Previsão de 7 dias (Open-Meteo)
    prev = {}
    datas = None
    for arq in sorted((RAW / "previsao").glob("lote_*.json")):
        lote = ler_json(arq)
        for rid, d in zip(lote["ids"], lote["dados"]):
            dd = d["daily"]
            datas = dd["time"]
            prev[rid] = [[r(x, 1) for x in dd["precipitation_sum"]], [r(x, 1) for x in dd["temperature_2m_max"]],
                         [r(x, 1) for x in dd["temperature_2m_min"]]]
    return {
        "fim": fim.date().isoformat(),
        "cols": ["p30", "p30_normal", "p30_anom", "t30", "t30_anom", "p90", "p90_normal", "p90_anom", "t90", "t90_anom"],
        "regioes": regioes,
        "previsao": {"datas": datas, "regioes": prev},
    }


# ================================================================ focos de queimada (INPE)
def nome_proprio(nome: str) -> str:
    """'MOJUÍ DOS CAMPOS' -> 'Mojuí dos Campos'; "SANTA BÁRBARA D'OESTE" -> "Santa Bárbara d'Oeste"."""
    s = re.sub(r"\b(Da|De|Do|Das|Dos|E)\b", lambda m: m.group(1).lower(), str(nome).title())
    return re.sub(r"\bD'(\w)", lambda m: "d'" + m.group(1).upper(), s)


def _ler_focos(arq) -> pd.DataFrame:
    """Lê um CSV diário do INPE, que pode vir em UTF-8 ou Latin-1."""
    for enc in ("utf-8", "latin-1"):
        try:
            return pd.read_csv(arq, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(arq)


def bloco_focos() -> dict:
    """Queimadas: (1) atualiza a série do satélite de referência com os dias baixados; (2) focos das
    últimas 48 h (todos os satélites) em pontos, por região imediata e por município; (3) acumulado do
    ano comparado com os anos anteriores, por estado e por bioma."""
    mun = pd.read_csv(REF / "municipios.csv", dtype=str)
    mun_imed = dict(zip(mun.ibge, mun.imediata))
    arqs = sorted((RAW / "focos").glob("focos_diario_br_*.csv"))
    dias = {a.stem[-8:]: _ler_focos(a) for a in arqs}

    # 1) Atualiza a série do satélite de referência (data/ref/focos_ref_diario.csv) com os dias baixados
    serie = pd.read_csv(REF / "focos_ref_diario.csv")
    novos = []
    for dia, d in dias.items():
        data = f"{dia[:4]}-{dia[4:6]}-{dia[6:]}"
        ref = d[d.satelite == SAT_REF].copy()
        ref["uf"] = ref.estado.map(lambda x: UF_POR_NOME.get(chave(x)))
        ref["data"] = pd.to_datetime(ref.data_hora_gmt).dt.date.astype(str)
        ref = ref[ref.data == data]
        g = ref.groupby(["data", "uf", "bioma"], dropna=False).size().rename("n").reset_index()
        serie = serie[serie.data != data]
        novos.append(g)
    serie = pd.concat([serie, *novos]).sort_values(["data", "uf", "bioma"])
    serie.to_csv(REF / "focos_ref_diario.csv", index=False)

    # 2) Focos das últimas 48 horas, todos os satélites (mapa de pontos e por região imediata)
    todos = pd.concat(dias.values())
    todos["quando"] = pd.to_datetime(todos.data_hora_gmt)
    limite = todos.quando.max() - timedelta(hours=48)
    rec = todos[todos.quando > limite].copy()
    rec["imediata"] = rec.municipio_id.astype(str).map(mun_imed)
    por_imed = rec.groupby("imediata").size().to_dict()
    pontos = rec.drop_duplicates(subset=["lat", "lon"])
    top_mun = (rec.groupby(["municipio_id", "municipio", "estado"]).size().sort_values(ascending=False).head(25).reset_index())

    # 3) Acumulado do ano (satélite de referência) contra os anos anteriores.
    # O "ano" exibido é o do dado mais recente: em 1º de janeiro, antes do primeiro foco do ano novo,
    # o painel continua mostrando o ano que terminou (completo), em vez de quebrar.
    hist_d = pd.read_csv(REF / "focos_hist_diario_br.csv", parse_dates=["data"])
    atual_d = serie.groupby("data").n.sum().reset_index()
    atual_d["data"] = pd.to_datetime(atual_d.data)
    nac = pd.concat([hist_d, atual_d]).groupby("data").n.sum()
    ult = atual_d.data.max()
    ano = int(ult.year)
    hoje_doy = int(ult.dayofyear)
    curvas = {}
    for a, s in nac.groupby(nac.index.year):
        doy = s.index.dayofyear
        diario = pd.Series(0, index=range(1, 367))
        diario.loc[doy] = s.values
        cum = diario.cumsum()
        curvas[str(a)] = [int(x) for x in (cum.loc[:hoje_doy] if a == ano else cum.loc[:365])]
    passados = {a: c for a, c in curvas.items() if int(a) < ano}
    ate_hoje = {a: c[min(hoje_doy, len(c)) - 1] for a, c in passados.items()}

    # Série mensal por estado e bioma: arquivos anuais (até 2025) + anos fechados da série diária (2026 em diante)
    s_todos = serie.assign(data=pd.to_datetime(serie.data))
    hist_m = pd.read_csv(REF / "focos_hist_mensal.csv")
    extra = s_todos[(s_todos.data.dt.year < ano) & (~s_todos.data.dt.year.isin(hist_m.ano.unique()))]
    if len(extra):
        extra_m = (extra.assign(ano=extra.data.dt.year, mes=extra.data.dt.month)
                   .groupby(["ano", "mes", "uf", "bioma"], dropna=False).n.sum().reset_index())
        hist_m = pd.concat([hist_m, extra_m], ignore_index=True)
    hist_m = hist_m[hist_m.ano < ano]
    s_atual = s_todos[s_todos.data.dt.year == ano]
    # Mesmo período (1º de janeiro até o último dia disponível) nos anos anteriores, por estado e por bioma:
    # meses completos + a fração do mês corrente (aproximação pelos dias decorridos)
    frac = ult.day / pd.Period(ult, "M").days_in_month

    def periodo_hist(chave_col):
        """Média, nos anos anteriores, dos focos de 1º de janeiro até a data atual, por estado ou bioma."""
        h = hist_m[hist_m.mes < ult.month].groupby(["ano", chave_col]).n.sum()
        hm = hist_m[hist_m.mes == ult.month].groupby(["ano", chave_col]).n.sum() * frac
        return h.add(hm, fill_value=0).groupby(chave_col).mean()

    por_uf_atual = s_atual.groupby("uf").n.sum()
    media_uf = periodo_hist("uf")
    h_ant = hist_m[(hist_m.ano == ano - 1)]
    ano_ant_uf = (h_ant[h_ant.mes < ult.month].groupby("uf").n.sum()
                  .add(h_ant[h_ant.mes == ult.month].groupby("uf").n.sum() * frac, fill_value=0))
    ufs = {uf: [int(por_uf_atual.get(uf, 0)), r(media_uf.get(uf), 0), r(ano_ant_uf.get(uf), 0)] for uf in NOME_UF}
    por_bioma = s_atual.groupby("bioma").n.sum()
    media_bioma = periodo_hist("bioma")
    biomas = {b: [int(por_bioma.get(b, 0)), r(media_bioma.get(b), 0)]
              for b in sorted(set(media_bioma.index) | set(por_bioma.index)) if isinstance(b, str)}

    return {
        "ultimo_dado": str(todos.quando.max()),
        "h48": {"total": int(len(rec)), "por_imediata": {k: int(v) for k, v in por_imed.items()},
                "pontos": [[round(t.lon, 2), round(t.lat, 2)] for t in pontos.itertuples()],
                "top_mun": [[str(t.municipio_id), nome_proprio(t.municipio), UF_POR_NOME.get(chave(t.estado)), int(t[4])]
                            for t in top_mun.itertuples()]},
        "ano": {"ano": ano, "ate": ult.date().isoformat(), "doy": hoje_doy, "curvas": curvas,
                "total": int(por_uf_atual.sum()),
                "media_mesmo_periodo": r(sum(ate_hoje.values()) / len(ate_hoje), 0) if ate_hoje else None,
                "ranking": sorted(ate_hoje.items(), key=lambda x: -x[1])[:5]},
        "ufs": ufs, "ufs_cols": ["ano_atual", "media_2003_ano_ant", "ano_anterior"],
        "biomas": biomas,
    }


# ================================================================ avisos do INMET
SEVERIDADE = {"Perigo Potencial": 1, "Perigo": 2, "Grande Perigo": 3}


def bloco_avisos() -> dict:
    """Avisos do INMET em vigor (ou que ainda vão começar), com severidade e as mesorregiões atingidas.
    O RSS traz as áreas pelo nome da mesorregião; a ligação com o mapa é feita pelo nome normalizado."""
    me = pd.read_csv(REF / "mesorregioes.csv", dtype=str)
    por_chave = {}
    for t in me.itertuples():
        por_chave.setdefault(t.chave, []).append(t.id)
    raiz = ET.parse(RAW / "avisos.xml").getroot()
    agora_ = agora()
    lista, sem_meso = [], set()
    for it in raiz.iter("item"):
        desc = it.findtext("description") or ""
        campos = dict((html.unescape(k).strip(), html.unescape(re.sub(r"<[^>]+>", "", v)).strip())
                      for k, v in re.findall(r"<th[^>]*>(.*?)</th>\s*<td>(.*?)</td>", desc, flags=re.S))
        try:
            ini = datetime.fromisoformat(campos["Início"][:19]).replace(tzinfo=BRT)
            fim = datetime.fromisoformat(campos["Fim"][:19]).replace(tzinfo=BRT)
        except (KeyError, ValueError):
            continue
        if fim < agora_ or campos.get("Status", "Alert") != "Alert":
            continue
        texto_areas = re.sub(r"^Aviso para as [Áá]reas:", "", campos.get("Área", "").strip())
        areas = [a.strip() for a in texto_areas.split(",") if a.strip()]
        mesos = []
        for a in areas:
            ids = por_chave.get(chave(a))
            if ids:
                mesos += ids
            else:
                sem_meso.add(a)
        link = re.search(r"href='([^']+)'", desc)
        lista.append({"id": (it.findtext("guid") or "").rsplit("/", 1)[-1], "evento": campos.get("Evento"),
                      "sev": SEVERIDADE.get(campos.get("Severidade"), 1), "severidade": campos.get("Severidade"),
                      "ini": ini.isoformat(timespec="minutes"), "fim": fim.isoformat(timespec="minutes"),
                      "descricao": campos.get("Descrição"), "areas": areas, "mesos": sorted(set(mesos)),
                      "link": url_segura(link.group(1) if link else it.findtext("link"))})
    lista.sort(key=lambda a: (-a["sev"], a["ini"]))
    if sem_meso:
        print("  avisos: áreas sem mesorregião correspondente:", sorted(sem_meso)[:15])
    return {"avisos": lista}


# ================================================================ mundo
def severidade_pt(tipo: str, txt: str | None) -> str | None:
    """Traduz os textos de intensidade mais comuns do GDACS; o que não reconhece fica como veio."""
    if not txt:
        return None
    milhar = lambda v: f"{v:,.0f}".replace(",", ".")  # noqa: E731
    vento = re.search(r"maximum wind speed of (\d+) km/h", txt)
    if tipo == "TC" and vento:
        # Categoria pela velocidade máxima do vento (escala de Saffir-Simpson)
        v = int(vento.group(1))
        cat = "Depressão tropical" if v < 63 else "Tempestade tropical" if v < 119 else "Furacão/tufão"
        return f"{cat}, ventos máximos de {v} km/h"
    m = re.search(r"Magnitude ([\d.]+)M?,?\s*Depth:?\s*([\d.]+)\s*km", txt)
    if tipo == "EQ" and m:
        return f"Magnitude {m.group(1).replace('.', ',')}, profundidade de {m.group(2).replace('.', ',')} km"
    m = re.search(r"(Low|Medium|High) impact for agricultural drought in (\d+) km2", txt)
    if tipo == "DR" and m:
        nivel = {"Low": "baixo", "Medium": "médio", "High": "alto"}[m.group(1)]
        return f"Impacto {nivel} na agricultura, em {milhar(int(m.group(2)))} km²"
    m = re.search(r"([\d.]+) ha", txt)
    if tipo == "WF" and m:
        return f"Área queimada de cerca de {milhar(float(m.group(1)))} hectares"
    return txt


TIPOS_GDACS = {"EQ": "Terremoto", "TC": "Ciclone tropical", "FL": "Enchente", "VO": "Vulcão", "DR": "Seca", "WF": "Incêndio florestal"}


def bloco_mundo() -> dict:
    """Desastres do GDACS dos últimos 30 dias (o episódio mais recente de cada evento) e a temperatura
    média global diária do ano corrente, com os anos mais quentes, a média 1991–2020 e os dias recordes."""
    eventos = {}
    for arq in ("gdacs.json", "gdacs_tc.json"):
        caminho = RAW / "mundo" / arq
        if not caminho.exists():
            continue
        for f in ler_json(caminho).get("features", []):
            p = f["properties"]
            k = (p["eventtype"], p["eventid"])
            if k in eventos and eventos[k]["episodio"] >= p.get("episodeid", 0):
                continue
            if p.get("eventtype") not in TIPOS_GDACS or p.get("alertlevel") not in ("Green", "Orange", "Red"):
                continue   # só tipos e níveis conhecidos (os valores viram classes de estilo no site)
            lon, lat = f["geometry"]["coordinates"][:2]
            url = p.get("url") or {}
            eventos[k] = {"tipo": p["eventtype"], "tipo_pt": TIPOS_GDACS[p["eventtype"]],
                          "nome": p.get("name"), "alerta": p["alertlevel"], "pais": (p.get("country") or "").strip(" ,"),
                          "ini": p.get("fromdate"), "fim": p.get("todate"), "atual": str(p.get("iscurrent")).lower() == "true",
                          "lon": round(lon, 2), "lat": round(lat, 2), "episodio": p.get("episodeid", 0),
                          "severidade": severidade_pt(p["eventtype"], (p.get("severitydata") or {}).get("severitytext")),
                          "iso2": [c.get("iso2") for c in (p.get("affectedcountries") or []) if isinstance(c, dict) and c.get("iso2")],
                          "link": url_segura(url.get("report")) if isinstance(url, dict) else None}
    limite = (agora() - timedelta(days=30)).strftime("%Y-%m-%d")
    lista = [e for e in eventos.values() if e["atual"] or (e["fim"] or "") >= limite]
    lista.sort(key=lambda e: (e["alerta"] != "Red", -(datetime.fromisoformat(e["fim"]).timestamp() if e["fim"] else 0)))

    # Temperatura média global diária (ERA5, Copernicus C3S Climate Pulse), com a anomalia de 1991–2020 já calculada pelo C3S
    era = pd.read_csv(RAW / "mundo" / "era5_2t_global.csv", comment="#", parse_dates=["date"])
    era = era.rename(columns={"2t": "t", "clim_91-20": "clim", "ano_91-20": "anom"}).dropna(subset=["t"])
    era["ano"], era["md"] = era.date.dt.year, era.date.dt.strftime("%m-%d")
    ano = int(era.ano.max())
    cur = era[era.ano == ano]
    anteriores = era[era.ano < ano]
    maximo_md = anteriores.groupby("md").t.max()
    recordes = int((cur.t.values > cur.md.map(maximo_md).values).sum())
    completos = anteriores.groupby("ano").filter(lambda g: len(g) >= 365)
    media_ano = completos.groupby("ano").t.mean()
    quentes = [str(a) for a in media_ano.sort_values(ascending=False).index[:3]]
    serie_ano = lambda a: [r(v, 2) for v in era[era.ano == int(a)].t]  # noqa: E731 — dia 1 = 1º de janeiro
    bissexto = era[era.ano == era[era.date.dt.strftime("%m-%d") == "02-29"].ano.max()]
    anom = [r(v, 2) for v in cur.anom]
    return {
        "eventos": lista,
        "temp_global": {"ano": ano, "dias": len(cur), "ultimo": cur.date.max().date().isoformat(),
                        "preliminar": bool((cur.status == "PRELIMINARY").any()),
                        "atual": serie_ano(ano), "anom": anom, "clim": [r(v, 2) for v in bissexto.clim],
                        "anos_ref": {a: serie_ano(a) for a in sorted(set(quentes + [str(ano - 1)]))},
                        "dias_recorde": recordes, "anom_ultimo": anom[-1] if anom else None,
                        "anom_30d": r(cur.anom.tail(30).mean(), 2)},
    }


# ================================================================ avisos oficiais no mundo (OMM / SWIC)
def bloco_swic() -> dict:
    """Avisos meteorológicos oficiais em vigor, agregados por país. Severidade no padrão CAP usado pela OMM:
    4 = extremo, 3 = severo (2 = moderado e 1 = menor ficam de fora do mapa, para não poluir)."""
    d = ler_json(RAW / "mundo" / "swic_avisos.json")
    membros = {m["mid"]: m for g in ler_json(RAW / "mundo" / "swic_membros.json") for m in g.get("members", [])}
    agora_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    def data(txt):
        """Data do SWIC ("2026-11-11 15:30:00", em UTC) ou None se não houver."""
        try:
            return datetime.strptime(txt[:19], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return None

    # Alguns serviços publicam o mesmo aviso em dois idiomas (a AEMET, em espanhol e inglês): mesmo
    # identificador, área, nível e prazo — conta uma vez só
    vistos, ativos = set(), []
    for x in d.get("items", []):
        chave_aviso = (x.get("id"), x.get("areaDesc"), x.get("s"), x.get("expires"))
        if chave_aviso in vistos or (data(x.get("expires")) or agora_utc) < agora_utc:
            continue
        vistos.add(chave_aviso)
        ativos.append(x)
    paises, com_aviso = {}, set()
    for x in ativos:
        m = membros.get(x.get("mid"))
        if not m or not re.fullmatch(r"[A-Z]{3}", str(m.get("code") or "")):
            continue
        com_aviso.add(m["code"])
        s = x.get("s")
        if s not in (3, 4):
            continue
        site = m.get("url") and url_segura("https://" + m["url"].removeprefix("https://").removeprefix("http://"))
        p = paises.setdefault(m["code"], {
            "iso3": {"SSD": "SDS"}.get(m["code"], m["code"]),   # o mapa-múndi usa SDS para o Sudão do Sul
            "nome": m["name"], "servico": m.get("dept"), "url": site or None,
            "lonlat": [r(m.get("lng"), 2), r(m.get("lat"), 2)],   # para ilhas que não aparecem no mapa
            "max": 0, "n4": 0, "n3": 0, "eventos": {}, "expira": None})
        p["max"] = max(p["max"], s)
        p[f"n{s}"] += 1
        ev = " ".join(str(x.get("event") or "Aviso").split())[:80]
        p["eventos"][(ev, s)] = p["eventos"].get((ev, s), 0) + 1
        exp = (x.get("expires") or "")[:16]
        p["expira"] = max(p["expira"] or exp, exp)
    lista = []
    for p in paises.values():
        p["eventos"] = [[ev, s, n] for (ev, s), n in sorted(p["eventos"].items(), key=lambda kv: (-kv[0][1], -kv[1]))][:6]
        lista.append(p)
    lista.sort(key=lambda p: (-p["max"], -(p["n4"] * 100 + p["n3"])))
    return {"atualizado": d.get("lastUpdated"), "total_ativos": len(ativos), "paises_com_aviso": len(com_aviso),
            "paises": lista}


# ================================================================ notícias
# ---------- fontes e veículos
# RSS oficiais (arquivo em data/raw/noticias/<nome>.xml -> nome exibido). Os temáticos (todo item é sobre
# clima) entram inteiros; nos demais, só o que tiver algum tema na manchete.
NOME_FONTE = {"agencia_brasil": "Agência Brasil", "onu_news_clima": "ONU News", "cemaden": "Cemaden"}
FEEDS_TEMATICOS = {"onu_news_clima", "cemaden"}
FONTES_PERMITIDAS = set(NOME_FONTE.values())
# Cada fonte de RSS só vale com link para o próprio site (nada de links de agregadores)
DOMINIOS_FONTE = {"Agência Brasil": ("https://agenciabrasil.ebc.com.br/",), "ONU News": ("https://news.un.org/",),
                  "Cemaden": ("https://www.gov.br/cemaden/",)}
# Nomes de exibição dos veículos mais frequentes no GDELT (os demais aparecem pelo endereço do site)
VEICULOS = {"g1.globo.com": "g1", "oglobo.globo.com": "O Globo", "ge.globo.com": "ge", "valor.globo.com": "Valor",
            "agenciabrasil.ebc.com.br": "Agência Brasil", "correiobraziliense.com.br": "Correio Braziliense",
            "folha.uol.com.br": "Folha de S.Paulo", "estadao.com.br": "Estadão", "cnnbrasil.com.br": "CNN Brasil",
            "metropoles.com": "Metrópoles", "terra.com.br": "Terra", "uol.com.br": "UOL", "noticias.uol.com.br": "UOL",
            "jc.ne10.uol.com.br": "Jornal do Commercio", "diariodepernambuco.com.br": "Diario de Pernambuco",
            "diariodonordeste.verdesmares.com.br": "Diário do Nordeste", "opovo.com.br": "O Povo",
            "gauchazh.clicrbs.com.br": "GZH", "poder360.com.br": "Poder360", "istoe.com.br": "IstoÉ",
            "band.uol.com.br": "Band", "r7.com": "R7", "sbtnews.sbt.com.br": "SBT News", "exame.com": "Exame",
            "infomoney.com.br": "InfoMoney", "brasildefato.com.br": "Brasil de Fato", "cartacapital.com.br": "CartaCapital"}


def bloqueados() -> set[str]:
    """Domínios que não podem aparecer: agregadores (que não são a fonte original) e veículos que pedirem
    para sair. Edite data/ref/noticias_bloqueio.txt (um domínio por linha)."""
    arq = REF / "noticias_bloqueio.txt"
    linhas = arq.read_text(encoding="utf-8").splitlines() if arq.exists() else []
    return {x.strip().lower() for x in linhas if x.strip() and not x.startswith("#")}


def host(link: str) -> str:
    """Domínio de um link, sem "www." (ex.: "g1.globo.com")."""
    return (urlparse(link).hostname or "").lower().removeprefix("www.")


def nome_veiculo(dominio: str) -> str:
    """Nome de exibição do veículo; sem nome cadastrado, o próprio domínio."""
    d = dominio.lower().removeprefix("www.")
    return VEICULOS.get(d) or VEICULOS.get(".".join(d.split(".")[-3:])) or d


def link_da_fonte(fonte: str, link: str | None, origem: str = "rss", bloq: frozenset = frozenset()) -> bool:
    """O link é mesmo da fonte indicada? RSS: só o site oficial dela. GDELT: o domínio do link tem que
    corresponder ao veículo e não pode estar na lista de bloqueio."""
    if not link:
        return False
    if origem == "gdelt":
        h = host(link)
        return bool(h) and not any(h == b or h.endswith("." + b) for b in bloq) and nome_veiculo(h) == fonte
    return link.startswith(DOMINIOS_FONTE.get(fonte, ("\0",)))


# ---------- leitura dos feeds e limpeza das manchetes
def _local(tag: str) -> str:
    """Nome de uma tag XML sem o namespace ("{http://www.w3.org/2005/Atom}entry" -> "entry")."""
    return tag.rsplit("}", 1)[-1]


def _itens_feed(arq):
    """Itens de um feed RSS 2.0, RSS 1.0 (RDF) ou Atom. O XML é lido com o defusedxml (proteção
    contra XML malicioso, já que vem de fora)."""
    try:
        raiz = ET.parse(arq).getroot()
    except Exception:  # noqa: BLE001 — feed corrompido ou fora do ar: ignora este arquivo
        return
    for it in raiz.iter():
        if _local(it.tag) not in ("item", "entry"):
            continue
        filhos = {_local(c.tag): c for c in it}
        titulo = html.unescape((filhos.get("title").text if "title" in filhos else "") or "").strip()
        link_el = filhos.get("link")
        link = (link_el.get("href") or link_el.text or "") if link_el is not None else ""
        data_txt = next((filhos[k].text for k in ("pubDate", "date", "published", "updated")
                         if k in filhos and filhos[k].text), None)
        try:   # RSS usa "Tue, 10 Nov 2026 18:48:35 GMT"; Atom/RDF, "2026-11-10T18:48:35Z"
            if data_txt and "," in data_txt:
                quando = parsedate_to_datetime(data_txt)
            else:
                quando = datetime.fromisoformat(data_txt.replace("Z", "+00:00"))
            quando = quando.astimezone(BRT)
        except (TypeError, ValueError, AttributeError):
            continue
        link = url_segura(link)
        if titulo and link:
            yield {"titulo": " ".join(titulo.split()), "link": link, "data": quando}


def limpar_titulo(titulo: str, dominio: str) -> str:
    """Tira o nome do site que alguns veículos põem na manchete ("Diário do Amapá – ...", "... | MidiaNews")."""
    rotulo = dominio.split(".")[1] if dominio.startswith(("www.", "g1.")) else dominio.split(".")[0]
    base = re.sub(r"[^a-z0-9]", "", chave(rotulo))
    titulo = " ".join(titulo.split())
    # " | Seção ou Site" curto no fim quase sempre é o nome do programa/site (às vezes vêm dois:
    # "... | Repórter Brasil | TV Brasil")
    for _ in range(2):
        titulo = re.sub(r"\s+\|\s+[^|]{2,30}$", "", titulo)
    for sep in (" | ", " – ", " - "):
        partes = titulo.split(sep)
        if len(partes) > 1:
            fim, ini = re.sub(r"[^a-z0-9]", "", chave(partes[-1])), re.sub(r"[^a-z0-9]", "", chave(partes[0]))
            if len(partes[-1]) <= 45 and base and (base[:6] in fim or fim[:6] in base):
                titulo = sep.join(partes[:-1])
            elif len(partes[0]) <= 30 and base and (base[:6] in ini or ini[:6] in base):
                titulo = sep.join(partes[1:])
    return titulo.strip()


# ---------- estados, municípios e regiões citados nas manchetes
CAPITAIS = {"RO": "Porto Velho", "AC": "Rio Branco", "AM": "Manaus", "RR": "Boa Vista", "PA": "Belém", "AP": "Macapá",
            "TO": "Palmas", "MA": "São Luís", "PI": "Teresina", "CE": "Fortaleza", "RN": "Natal", "PB": "João Pessoa",
            "PE": "Recife", "AL": "Maceió", "SE": "Aracaju", "BA": "Salvador", "MG": "Belo Horizonte", "ES": "Vitória",
            "RJ": "Rio de Janeiro", "SP": "São Paulo", "PR": "Curitiba", "SC": "Florianópolis", "RS": "Porto Alegre",
            "MS": "Campo Grande", "MT": "Cuiabá", "GO": "Goiânia", "DF": "Brasília"}
# Capitais que também são palavras comuns só contam com contexto (evita "Natal" = festa, "Vitória" = vitória)
AMBIGUAS = {"RN", "ES", "TO", "BA"}
DEMONIMOS = {"PE": "pernambucan", "CE": "cearense", "BA": "baian", "PB": "paraiban", "RN": "potiguar", "AL": "alagoan",
             "PI": "piauiense", "MA": "maranhense", "SE": "sergipan", "AM": "amazonense", "PA": "paraense", "RS": "gaúch",
             "SC": "catarinense", "PR": "paranaense", "MG": "mineir", "SP": "paulista", "RJ": "fluminense", "ES": "capixaba",
             "GO": "goian", "MT": "mato-grossense", "MS": "sul-mato-grossense", "TO": "tocantinense", "RO": "rondoniense",
             "AC": "acrean", "AP": "amapaense", "RR": "roraimense", "DF": "brasiliense"}


def _padroes_uf() -> dict:
    """Expressões (sensíveis a acento e maiúsculas) que indicam que o título fala de um estado."""
    pad = {}
    for uf, nome in NOME_UF.items():
        nm = re.escape(nome) + (r"(?! do Sul)" if uf == "MT" else "")
        partes = [rf"\b{nm}\b", rf"\({uf}\)", rf"[-/]\s?{uf}\b", rf"\b(no|na|em|do|da|pelo|pela) {uf}\b", rf"^{uf} "]
        if uf == "MG":
            partes.append(r"\bBH\b")
        cap = CAPITAIS[uf]
        if uf not in AMBIGUAS:
            partes.append(rf"\b{re.escape(cap)}\b(?! do Sul)" if uf == "MS" else rf"\b{re.escape(cap)}\b")
        else:
            partes.append(rf"\b(em|de|para) {re.escape(cap)}\b(?! *[a-z])")
        partes.append(rf"(?i:(?<!sul-)\b{re.escape(DEMONIMOS[uf])})")
        pad[uf] = re.compile("|".join(partes))
    return pad


# Municípios citados na manchete. Só nomes que existem em um único estado; os de uma palavra precisam ter
# 5 letras ou mais e não podem ser palavras comuns (lista abaixo). Pode haver erro raro (ex.: "Campos Gerais",
# região do PR e município de MG) — por isso o painel avisa que a marcação é automática.
PALAVRAS_COMUNS = {"Brasil", "Bonito", "Formosa", "Esperança", "Vitória", "Paraíso", "Cruzeiro", "Liberdade", "Alegria",
                   "Saudade", "Harmonia", "Planalto", "Floresta", "Pontal", "Caridade", "Primavera", "Independência",
                   "União", "Progresso", "Triunfo", "Amparo", "Aurora", "Mirante", "Central", "General", "Presidente",
                   "Governador", "Fortuna", "Glória", "Vigia", "Socorro", "Salvaterra", "Coronel", "Pedreira", "Sertão",
                   "Paulista", "Tabuleiro", "Cachoeira", "Tapera", "Serrano", "Itapeva", "Pacatuba", "Palestina",
                   "Jardim", "Princesa", "Ouvidor", "Cristal", "Sapucaia", "Guarani", "Anchieta",
                   "Campos Gerais", "Mata", "Agreste", "Cariri", "Pantanal", "Serra"}   # também nomes de regiões


def _padrao_municipios() -> tuple[re.Pattern, dict]:
    """Expressão que acha nomes de municípios na manchete e o dicionário nome -> estado."""
    mun = pd.read_csv(REF / "municipios.csv", dtype=str)
    por_nome = mun.groupby("nome").uf.agg(lambda s: set(s))
    nomes = {n: next(iter(u)) for n, u in por_nome.items()
             if len(u) == 1 and n not in PALAVRAS_COMUNS and (" " in n or len(n) >= 5)}
    rx = re.compile(r"(?<![\w-])(" + "|".join(sorted(map(re.escape, nomes), key=len, reverse=True)) + r")(?![\w-])")
    return rx, nomes


SIGLAS_G1 = {uf.lower() for uf in NOME_UF}


def ufs_da_url(link: str) -> set[str]:
    """No g1, o estado vem no endereço (g1.globo.com/pe/pernambuco/...)."""
    m = re.match(r"https?://g1\.globo\.com/([a-z]{2})/", link)
    return {m.group(1).upper()} if m and m.group(1) in SIGLAS_G1 else set()


# Regiões citadas na manchete ("no Sul", "do Nordeste", "Centro-Oeste"...), com maiúscula para não pegar "sul" de direção
RX_REGIOES = {"Norte": re.compile(r"\b(no|do|na|o|ao|pelo) Norte\b(?! d[aoe])"),
              "Nordeste": re.compile(r"\bNordeste\b|\bSemiárido\b|\bSertão\b"),
              "Centro-Oeste": re.compile(r"\bCentro-Oeste\b|\bPantanal\b"),
              "Sudeste": re.compile(r"\bSudeste\b(?! (Asiático|da Ásia))"),
              "Sul": re.compile(r"\b(no|do|na|o|ao|pelo|e) Sul\b(?! d[aoe]|-)|\bSul do (país|Brasil)\b"),
              "Amazônia": re.compile(r"\bAmazônia\b|\bAmazonas\b|\bamazônic")}


# ---------- bloco
def bloco_noticias() -> dict:
    """Junta as manchetes novas às já publicadas (os feeds oficiais trazem só as mais recentes)
    e mantém os últimos 14 dias."""
    pasta = RAW / "noticias"
    limite = agora() - timedelta(days=14)
    padroes = _padroes_uf()
    rx_mun, uf_mun = _padrao_municipios()
    bloq = frozenset(bloqueados())
    itens = {}

    def add(titulo, link, quando, fonte, tematico, origem="rss"):
        """Inclui a manchete se for dos últimos 14 dias, de fonte autorizada e sobre clima; repetidas
        (o mesmo texto de agência em vários veículos) entram uma vez só."""
        if quando < limite or quando > agora() + timedelta(hours=1) or not link_da_fonte(fonte, link, origem, bloq):
            return
        temas = sorted(k for k, rx in RX_TEMAS.items() if rx.search(titulo))
        if not temas and not tematico:
            return
        if not temas:
            temas = ["clima"]   # feed temático (ONU News clima, Cemaden)
        k = chave(titulo)[:70]   # a mesma manchete em vários veículos (texto de agência) aparece uma vez só
        if k in itens:
            return
        # Estado só quando o próprio título indica (nome, capital, sigla ou gentílico); região pelo nome
        ufs = sorted({sg for sg, rx in padroes.items() if rx.search(titulo)} | ufs_da_url(link)
                     | {uf_mun[m] for m in rx_mun.findall(titulo)})
        regioes = sorted({reg for reg, rx in RX_REGIOES.items() if rx.search(titulo)})
        itens[k] = {"titulo": titulo, "fonte": fonte, "link": link, "data": quando, "temas": temas, "ufs": ufs,
                    "regioes": regioes, "origem": origem}

    # 1) RSS oficiais
    for arq in sorted(pasta.glob("*.xml")):
        fonte = next((v for k, v in NOME_FONTE.items() if arq.stem.startswith(k)), None)
        if not fonte:
            continue
        for it in _itens_feed(arq):
            add(it["titulo"], it["link"], it["data"], fonte, arq.stem in FEEDS_TEMATICOS)
    # 2) GDELT (manchetes de veículos brasileiros; a seleção por tema já veio da coleta e é refeita aqui)
    arq = pasta / "gdelt.json"
    for it in (ler_json(arq) if arq.exists() else []):
        link = url_segura(it.get("link"))
        if not link:
            continue
        quando = datetime.strptime(it["data"], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).astimezone(BRT)
        add(limpar_titulo(it["titulo"], host(link)), link, quando, nome_veiculo(host(link)), False, "gdelt")
    # 3) Manchetes publicadas antes, com as mesmas regras (descarta qualquer resto de fontes não autorizadas)
    anterior = SAIDA / "noticias.json"
    if anterior.exists():
        for x in ler_json(anterior).get("noticias", []):
            link = url_segura(x.get("link"))
            origem = x.get("origem", "rss")
            if link and (origem == "gdelt" or x.get("fonte") in FONTES_PERMITIDAS):
                add(x["titulo"], link, datetime.fromisoformat(x["data"]), x["fonte"],
                    origem == "rss" and x["fonte"] != "Agência Brasil", origem)
    # ~350 manchetes/dia do GDELT (medido em 11/2026) × 14 dias + RSS ≈ 5 mil: o teto de 6 mil cobre o período com folga
    lista = sorted(itens.values(), key=lambda x: x["data"], reverse=True)[:6000]
    return {"noticias": [{**x, "data": x["data"].isoformat(timespec="minutes")} for x in lista]}


# ================================================================ execução
# Bloco -> (função, fontes da coleta de que ele depende)
BLOCOS = {"enso": (bloco_enso, ["enso"]), "pacifico": (bloco_pacifico, ["pacifico"]),
          "clima": (bloco_clima, ["clima", "previsao"]),
          "focos": (bloco_focos, ["focos"]), "avisos": (bloco_avisos, ["avisos"]), "mundo": (bloco_mundo, ["mundo"]),
          "swic": (bloco_swic, ["swic"]), "noticias": (bloco_noticias, ["noticias"])}


def main(blocos: list[str]) -> None:
    """Gera o JSON de cada bloco pedido. Se a coleta de alguma fonte do bloco falhou, ou o bloco dá erro,
    mantém o JSON anterior e registra isso em docs/dados/atualizacao.json (o site mostra a data)."""
    arq_at = SAIDA / "atualizacao.json"
    at = ler_json(arq_at) if arq_at.exists() else {}
    coleta = ler_json(RAW / "status_coleta.json") if (RAW / "status_coleta.json").exists() else {}
    for nome in blocos:
        fn, fontes = BLOCOS[nome]
        print(f"== {nome}")
        if any(not coleta.get(f, {}).get("ok", False) for f in fontes):
            print("  coleta falhou hoje: mantendo os dados anteriores")
            at.setdefault(nome, {})["ok_hoje"] = False
            continue
        try:
            dados = fn()
            gravar_json(dados, SAIDA / f"{nome}.json")
            at[nome] = {"ok_hoje": True, "atualizado": agora().isoformat(timespec="minutes")}
            print(f"  ok ({(SAIDA / f'{nome}.json').stat().st_size / 1e3:.0f} kB)")
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            at.setdefault(nome, {})["ok_hoje"] = False
    at["gerado"] = agora().isoformat(timespec="minutes")
    gravar_json(at, arq_at, compacto=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Tratamento dos dados do Monitor El Niño.")
    ap.add_argument("--bloco", nargs="*", default=list(BLOCOS), choices=list(BLOCOS))
    main(ap.parse_args().bloco)
