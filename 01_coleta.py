"""
01_coleta.py — Coleta diária das fontes abertas (roda no GitHub Actions todo dia, ou à mão).

  python 01_coleta.py                    # todas as fontes
  python 01_coleta.py --fonte enso focos # só algumas

Fontes (tudo em data/raw/, que não vai para o repositório):
  enso      NOAA CPC: ONI (oni.ascii.txt), Niño semanal (wksst9120.for) e ENSO Diagnostic Discussion
  clima     NASA POWER (chuva e temperatura diárias, últimos 125 dias) por região imediata do IBGE
  previsao  Open-Meteo (previsão de 7 dias) por região imediata
  avisos    INMET, avisos meteorológicos ativos (RSS)
  focos     INPE, focos de queimada dos últimos 3 dias (todos os satélites)
  mundo     GDACS (alertas de desastres) e Copernicus C3S Climate Pulse (temperatura média global diária, ERA5)
  swic      OMM, Severe Weather Information Centre: avisos meteorológicos oficiais de cada país
  noticias  GDELT Project (manchetes de veículos brasileiros sobre clima, últimas 7 horas) e
            RSS oficiais: Agência Brasil, ONU News (português) e Cemaden

Boas práticas com as fontes: identificação honesta (User-Agent do LADRI), intervalos entre acessos
como pedem os robots.txt (GDACS: 1 por minuto; Agência Brasil: 10 s) e as fontes pesadas só uma vez
por dia (o GitHub Actions roda as leves — avisos, focos e notícias — nas demais execuções).

Uma fonte que falha não interrompe as outras: o 02_tratamento.py mantém os dados anteriores dela.
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import time
import traceback
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pandas as pd

from clima_comum import RAW, REF, RX_TEMAS, agora, baixar, gravar_json, ler_json

csv.field_size_limit(2**31 - 1)   # campos do GDELT podem ser muito longos

CPC = "https://www.cpc.ncep.noaa.gov"


def enso() -> None:
    baixar(f"{CPC}/data/indices/oni.ascii.txt", RAW / "enso" / "oni.txt")
    baixar(f"{CPC}/data/indices/wksst9120.for", RAW / "enso" / "semanal.txt")
    baixar(f"{CPC}/products/analysis_monitoring/enso_advisory/ensodisc.shtml", RAW / "enso" / "discussao.html")


def _regioes() -> pd.DataFrame:
    return pd.read_csv(REF / "regioes_imediatas.csv", dtype={"id": str})


def clima() -> None:
    """NASA POWER, o mesmo produto (MERRA-2) das normais 1991–2020 de data/ref/normais_power.csv."""
    hoje = agora().date()
    ini, fim = (hoje - timedelta(days=125)).strftime("%Y%m%d"), hoje.strftime("%Y%m%d")
    destino = RAW / "power"

    def um(linha):
        p = {"parameters": "PRECTOTCORR,T2M", "community": "AG", "longitude": linha.lon, "latitude": linha.lat,
             "start": ini, "end": fim, "format": "JSON"}
        baixar("https://power.larc.nasa.gov/api/temporal/daily/point", destino / f"{linha.id}.json", params=p, timeout=120)

    linhas = list(_regioes().itertuples())
    # Apaga os arquivos antigos: uma região que falhar hoje não pode ficar com dados de outro dia
    for velho in destino.glob("*.json"):
        velho.unlink()
    falhas = linhas
    for rodada in range(4):   # o NASA POWER limita os acessos simultâneos: quem falhar tenta de novo, mais devagar
        with ThreadPoolExecutor(max_workers=max(1, 4 - rodada)) as pool:
            futs = {pool.submit(um, l): l for l in falhas}
            falhas = []
            for fut, l in futs.items():
                try:
                    fut.result()
                except RuntimeError:
                    falhas.append(l)
        if not falhas:
            break
        print(f"  NASA POWER: {len(falhas)} regiões para tentar de novo")
        time.sleep(20 * (rodada + 1))
    if len(falhas) > len(linhas) * 0.1:
        raise RuntimeError(f"NASA POWER: {len(falhas)} de {len(linhas)} regiões falharam")
    print(f"  NASA POWER: {len(linhas) - len(falhas)} regiões")


def previsao() -> None:
    ri = _regioes()
    for i in range(0, len(ri), 100):
        lote = ri.iloc[i:i + 100]
        p = {"latitude": ",".join(map(str, lote.lat)), "longitude": ",".join(map(str, lote.lon)),
             "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min", "timezone": "America/Sao_Paulo",
             "forecast_days": 7}
        dados = json.loads(baixar("https://api.open-meteo.com/v1/forecast", params=p, timeout=120))
        gravar_json({"ids": lote.id.tolist(), "dados": dados}, RAW / "previsao" / f"lote_{i // 100:02d}.json")


def avisos() -> None:
    baixar("https://apiprevmet3.inmet.gov.br/avisos/rss", RAW / "avisos.xml", timeout=120)


def focos() -> None:
    pasta = RAW / "focos"
    hoje = agora().date()
    dias = [hoje - timedelta(days=i) for i in range(3)]
    for d in dias:
        nome = f"focos_diario_br_{d:%Y%m%d}.csv"
        try:
            baixar(f"https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/diario/Brasil/{nome}", pasta / nome, timeout=180)
        except RuntimeError as erro:
            if d == hoje:   # o arquivo do dia pode ainda não existir de madrugada
                print("  ", erro)
            else:
                raise
    for velho in pasta.glob("focos_diario_br_*.csv"):
        if velho.name < f"focos_diario_br_{dias[-1]:%Y%m%d}.csv":
            velho.unlink()


def mundo() -> None:
    # GDACS: API pública; o robots.txt do site pede no máximo 1 acesso por minuto
    gd = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
    ini = (agora() - timedelta(days=45)).strftime("%Y-%m-%d")
    baixar(gd, RAW / "mundo" / "gdacs.json", params={"eventlist": "EQ;TC;FL;VO;DR;WF", "alertlevel": "Orange;Red",
                                                       "fromdate": ini}, timeout=120, tentativas=2)
    time.sleep(61)
    # Ciclones tropicais em curso, de qualquer nível de alerta (têm trajetória prevista)
    baixar(gd, RAW / "mundo" / "gdacs_tc.json", params={"eventlist": "TC", "alertlevel": "Green;Orange;Red",
                                                          "fromdate": ini}, timeout=120, tentativas=2)
    # Temperatura média global diária: Copernicus Climate Change Service (C3S), Climate Pulse (ERA5)
    baixar("https://sites.ecmwf.int/data/climatepulse/data/series/era5_daily_series_2t_global.csv",
           RAW / "mundo" / "era5_2t_global.csv", timeout=180)


def swic() -> None:
    """WMO Severe Weather Information Centre (OMM): avisos oficiais (CAP) de mais de 130 serviços
    meteorológicos nacionais num arquivo só. A nota de uso diz que a informação é livre para
    reutilização por outros sites, creditando o serviço de cada país."""
    base = "https://severeweather.wmo.int/json"
    baixar(f"{base}/wmo_all.json", RAW / "mundo" / "swic_avisos.json", timeout=120)
    time.sleep(2)
    baixar(f"{base}/wmo_member.json", RAW / "mundo" / "swic_membros.json", timeout=60)


# ---------------------------------------------------------------- notícias
# Só feeds RSS oficiais de publicadores que autorizam a reprodução com indicação da fonte.
# (O Google Notícias foi descartado: os termos dele proíbem exibir o conteúdo publicamente e o
# robots.txt bloqueia o acesso automatizado ao RSS.)
FEEDS = {
    # Agência Brasil (EBC): "Reprodução autorizada mediante indicação da fonte"; robots.txt pede 10 s entre acessos
    "agencia_brasil_ultimas": "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml",
    "agencia_brasil_meio_ambiente": "https://agenciabrasil.ebc.com.br/rss/meio-ambiente/feed.xml",
    "agencia_brasil_geral": "https://agenciabrasil.ebc.com.br/rss/geral/feed.xml",
    # ONU News em português, tema mudança climática (pede atribuição e link para a notícia original)
    "onu_news_clima": "https://news.un.org/feed/subscribe/pt/news/topic/climate-change/feed/rss.xml",
    # Cemaden (gov.br, licença CC BY-ND 3.0)
    "cemaden": "https://www.gov.br/cemaden/pt-br/assuntos/noticias-cemaden/RSS",
}


GDELT = "https://data.gdeltproject.org/gdeltv2"
GDELT_JANELA_H = 7          # cada execução lê as últimas 7 horas (as execuções são de 6 em 6 horas);
                            # na carga inicial, use --gdelt-horas 72 (ou até 336 = 14 dias) para encher a aba de notícias
DOMINIOS_FORA = (".pt", ".ao", ".mz", ".cv", ".gw", ".st", ".tl", ".mo")   # países lusófonos fora do Brasil


def _gdelt_arquivo(url: str) -> list[dict]:
    """Lê um arquivo GKG "translingual" de 15 minutos do GDELT e devolve só as notícias em português,
    de veículos brasileiros (ou que citam o Brasil), cuja manchete trata de clima ou desastres."""
    conteudo = baixar(url, timeout=180, tentativas=2)
    z = zipfile.ZipFile(io.BytesIO(conteudo))
    saida = []
    with z.open(z.namelist()[0]) as f:
        for row in csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="\t"):
            if len(row) < 27 or "srclc:por" not in (row[25] or ""):
                continue
            dominio, link, locs = row[3].lower(), row[4], row[10] or row[9]
            if dominio.endswith(DOMINIOS_FORA) or not (dominio.endswith(".br") or "#BR" in locs):
                continue
            m = re.search(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", row[26] or "")
            titulo = " ".join(html.unescape(m.group(1)).split()) if m else ""
            if not titulo or not any(rx.search(titulo) for rx in RX_TEMAS.values()):
                continue
            saida.append({"titulo": titulo, "link": link, "dominio": dominio, "data": row[1]})
    return saida


def gdelt() -> list[dict]:
    """GDELT Project: base aberta que monitora notícias do mundo todo (uso livre, com citação e link).
    Usa os arquivos de 15 minutos, como o GDELT recomenda para uso automatizado (a API tem limite de
    1 consulta a cada 5 s)."""
    ultimo = baixar(f"{GDELT}/lastupdate-translation.txt", timeout=60).decode()
    m = re.search(r"/(\d{14})\.translation\.gkg", ultimo)
    fim = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    itens, falhas = [], 0
    n = GDELT_JANELA_H * 4 + 1
    for i in range(n):
        t = fim - timedelta(minutes=15 * i)
        try:
            itens += _gdelt_arquivo(f"{GDELT}/{t:%Y%m%d%H%M%S}.translation.gkg.csv.zip")
        except (RuntimeError, zipfile.BadZipFile):
            falhas += 1   # o índice anuncia arquivos alguns minutos antes de eles existirem
        time.sleep(1)
        if i and i % 48 == 0:
            print(f"  GDELT: {i}/{n} arquivos lidos, {len(itens)} manchetes até agora")
    print(f"  GDELT: {len(itens)} manchetes em {GDELT_JANELA_H} h ({falhas} arquivos indisponíveis)")
    if falhas > n // 2:
        raise RuntimeError(f"GDELT: {falhas} arquivos indisponíveis")
    return itens


def noticias() -> None:
    pasta = RAW / "noticias"
    for velho in [*pasta.glob("*.xml"), *pasta.glob("*.json")]:   # não deixa arquivos antigos para o tratamento
        velho.unlink()
    try:
        gravar_json(gdelt(), pasta / "gdelt.json")
    except Exception as erro:  # noqa: BLE001 — sem o GDELT, seguem os RSS oficiais
        print("  GDELT indisponível:", erro)
    erros = []
    for i, (nome, url) in enumerate(FEEDS.items()):
        if i:
            time.sleep(11)
        try:
            baixar(url, pasta / f"{nome}.xml", timeout=60, tentativas=2)
        except RuntimeError as erro:
            erros.append(str(erro))
    if len(erros) == len(FEEDS):
        raise RuntimeError("; ".join(erros))
    for e in erros:
        print("  ", e)


FONTES = {"enso": enso, "clima": clima, "previsao": previsao, "avisos": avisos, "focos": focos, "mundo": mundo,
          "swic": swic, "noticias": noticias}


def main(fontes: list[str]) -> None:
    arq = RAW / "status_coleta.json"
    status = ler_json(arq) if arq.exists() else {}
    for nome in fontes:
        print(f"== {nome}")
        try:
            FONTES[nome]()
            status[nome] = {"ok": True, "quando": agora().isoformat(timespec="minutes")}
        except Exception as erro:  # noqa: BLE001 — uma fonte fora do ar não pode parar as outras
            traceback.print_exc()
            status[nome] = {"ok": False, "quando": agora().isoformat(timespec="minutes"), "erro": str(erro)[:300]}
    gravar_json(status, arq, compacto=False)
    falhas = [k for k in fontes if not status[k]["ok"]]
    print("Coleta concluída." + (f" Falharam: {', '.join(falhas)}" if falhas else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Coleta diária da plataforma El Niño.")
    ap.add_argument("--fonte", nargs="*", default=list(FONTES), choices=list(FONTES))
    def horas(v: str) -> int:
        if not v.isdigit() or not 1 <= int(v) <= 336:
            raise argparse.ArgumentTypeError("use um número inteiro de 1 a 336")
        return int(v)

    ap.add_argument("--gdelt-horas", type=horas, default=GDELT_JANELA_H, metavar="1-336",
                    help="horas de notícias do GDELT a ler (padrão 7; na carga inicial, 72)")
    args = ap.parse_args()
    GDELT_JANELA_H = args.gdelt_horas
    main(args.fonte)
