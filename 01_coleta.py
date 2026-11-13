"""
01_coleta.py — Baixa as fontes abertas para data/raw/ (roda no GitHub Actions a cada hora, ou à mão).

  python 01_coleta.py                      # todas as fontes
  python 01_coleta.py --fonte avisos focos # só algumas
  python 01_coleta.py --gdelt-horas 72     # carga inicial das notícias (padrão: 3 horas)

Fontes:
  enso      NOAA/CPC: índice ONI, regiões Niño semana a semana e boletim mensal (ENSO Diagnostic Discussion)
  pacifico  NOAA OISST (via PSL): mapa da anomalia da temperatura do mar no Pacífico (fundo do cabeçalho)
  clima     NASA POWER: chuva e temperatura diárias (últimos 125 dias) em cada região imediata do IBGE
  previsao  Open-Meteo: previsão de 7 dias nos mesmos pontos
  avisos    INMET: avisos meteorológicos em vigor (RSS oficial)
  focos     INPE: focos de queimada dos últimos 3 dias (todos os satélites)
  mundo     GDACS (desastres) e Copernicus Climate Pulse (temperatura média global diária, ERA5)
  swic      OMM, Severe Weather Information Centre: avisos meteorológicos oficiais de cada país
  noticias  GDELT (manchetes de veículos brasileiros) e RSS oficiais (Agência Brasil, ONU News, Cemaden)

Boas práticas com as fontes: identificação honesta (User-Agent do LADRI) e os intervalos que os
robots.txt pedem (GDACS: 1 acesso por minuto; Agência Brasil: 10 s). Uma fonte que falha não
interrompe as outras: o 02_tratamento.py mantém os dados anteriores dela.
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
INPE_DIARIO = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/diario/Brasil"
GDACS = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
GDELT = "https://data.gdeltproject.org/gdeltv2"
GDELT_HORAS = 3   # execuções a cada hora: 3 horas de janela cobrem atrasos e uma rodada perdida


def _regioes() -> pd.DataFrame:
    """As 510 regiões imediatas do IBGE, com o ponto usado nas consultas de clima."""
    return pd.read_csv(REF / "regioes_imediatas.csv", dtype={"id": str})


# ---------------------------------------------------------------- El Niño
def enso() -> None:
    """NOAA/CPC: índice ONI desde 1950, regiões Niño semana a semana e a página do boletim mensal."""
    baixar(f"{CPC}/data/indices/oni.ascii.txt", RAW / "enso" / "oni.txt")
    baixar(f"{CPC}/data/indices/wksst9120.for", RAW / "enso" / "semanal.txt")
    baixar(f"{CPC}/products/analysis_monitoring/enso_advisory/ensodisc.shtml", RAW / "enso" / "discussao.html")


def pacifico() -> None:
    """NOAA OISST (via NOAA PSL): anomalia da temperatura do mar do dia mais recente no Pacífico tropical,
    na grade original de 0,25° (40°S a 40°N, 100°E a 60°W; o tratamento tira a média de cada bloco de 1°).
    É o fundo do cabeçalho do site. Os arquivos do PSL são anuais; no começo de janeiro, antes do
    primeiro dia do ano novo, usa o arquivo do ano anterior."""
    for ano in (agora().year, agora().year - 1):
        base = f"https://psl.noaa.gov/thredds/dodsC/Datasets/noaa.oisst.v2.highres/sst.day.anom.{ano}.nc"
        try:
            n = int(re.search(r"time = (\d+)", baixar(f"{base}.dds", timeout=60).decode()).group(1))
        except (RuntimeError, AttributeError):
            continue
        if n:
            # Índices da grade de 0,25°: latitude 200..519 (40°S a 40°N), longitude 400..1199 (100°E a 300°E)
            baixar(f"{base}.ascii?anom[{n - 1}][200:1:519][400:1:1199],time[{n - 1}]", RAW / "pacifico.txt", timeout=300)
            return
    raise RuntimeError("OISST: nenhum arquivo com dados")


# ---------------------------------------------------------------- Brasil: clima, previsão, avisos, queimadas
def clima() -> None:
    """NASA POWER, últimos 125 dias de chuva e temperatura por região imediata (mesmo produto, MERRA-2,
    das normais 1991–2020 em data/ref/normais_power.csv). Quem falhar é tentado de novo, mais devagar,
    porque o NASA POWER limita acessos simultâneos."""
    hoje = agora().date()
    ini, fim = (hoje - timedelta(days=125)).strftime("%Y%m%d"), hoje.strftime("%Y%m%d")
    destino = RAW / "power"

    def baixar_regiao(reg):
        """Série diária de uma região imediata (no ponto representativo dela)."""
        p = {"parameters": "PRECTOTCORR,T2M", "community": "AG", "longitude": reg.lon, "latitude": reg.lat,
             "start": ini, "end": fim, "format": "JSON"}
        baixar("https://power.larc.nasa.gov/api/temporal/daily/point", destino / f"{reg.id}.json", params=p, timeout=120)

    regioes = list(_regioes().itertuples())
    for velho in destino.glob("*.json"):   # uma região que falhar hoje não pode ficar com dados de outro dia
        velho.unlink()
    falhas = regioes
    for rodada in range(4):
        with ThreadPoolExecutor(max_workers=max(1, 4 - rodada)) as pool:
            tarefas = {pool.submit(baixar_regiao, reg): reg for reg in falhas}
            falhas = []
            for tarefa, reg in tarefas.items():
                try:
                    tarefa.result()
                except RuntimeError:
                    falhas.append(reg)
        if not falhas:
            break
        print(f"  NASA POWER: {len(falhas)} regiões para tentar de novo")
        time.sleep(20 * (rodada + 1))
    if len(falhas) > len(regioes) * 0.1:
        raise RuntimeError(f"NASA POWER: {len(falhas)} de {len(regioes)} regiões falharam")
    print(f"  NASA POWER: {len(regioes) - len(falhas)} regiões")


def previsao() -> None:
    """Open-Meteo: previsão de 7 dias (chuva, máxima e mínima) por região imediata, em lotes de 100 pontos."""
    ri = _regioes()
    for i in range(0, len(ri), 100):
        lote = ri.iloc[i:i + 100]
        p = {"latitude": ",".join(map(str, lote.lat)), "longitude": ",".join(map(str, lote.lon)),
             "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min", "timezone": "America/Sao_Paulo",
             "forecast_days": 7}
        dados = json.loads(baixar("https://api.open-meteo.com/v1/forecast", params=p, timeout=120))
        gravar_json({"ids": lote.id.tolist(), "dados": dados}, RAW / "previsao" / f"lote_{i // 100:02d}.json")


def avisos() -> None:
    """INMET: avisos meteorológicos em vigor (RSS oficial)."""
    baixar("https://apiprevmet3.inmet.gov.br/avisos/rss", RAW / "avisos.xml", timeout=120)


def focos() -> None:
    """INPE: arquivos diários de focos de queimada de hoje e dos 2 dias anteriores (todos os satélites)."""
    pasta = RAW / "focos"
    hoje = agora().date()
    dias = [hoje - timedelta(days=i) for i in range(3)]
    for d in dias:
        nome = f"focos_diario_br_{d:%Y%m%d}.csv"
        try:
            baixar(f"{INPE_DIARIO}/{nome}", pasta / nome, timeout=180)
        except RuntimeError as erro:
            if d != hoje:   # o arquivo do dia pode ainda não existir de madrugada; os anteriores, sim
                raise
            print("  ", erro)
    for velho in pasta.glob("focos_diario_br_*.csv"):
        if velho.name < f"focos_diario_br_{dias[-1]:%Y%m%d}.csv":
            velho.unlink()


# ---------------------------------------------------------------- mundo
def mundo() -> None:
    """GDACS (eventos laranja e vermelhos dos últimos 45 dias, mais ciclones de qualquer nível) e a
    temperatura média global diária do Copernicus. O robots.txt do GDACS pede 1 acesso por minuto."""
    ini = (agora() - timedelta(days=45)).strftime("%Y-%m-%d")
    baixar(GDACS, RAW / "mundo" / "gdacs.json", timeout=120, tentativas=2,
           params={"eventlist": "EQ;TC;FL;VO;DR;WF", "alertlevel": "Orange;Red", "fromdate": ini})
    time.sleep(61)
    baixar(GDACS, RAW / "mundo" / "gdacs_tc.json", timeout=120, tentativas=2,
           params={"eventlist": "TC", "alertlevel": "Green;Orange;Red", "fromdate": ini})
    baixar("https://sites.ecmwf.int/data/climatepulse/data/series/era5_daily_series_2t_global.csv",
           RAW / "mundo" / "era5_2t_global.csv", timeout=180)


def swic() -> None:
    """OMM, Severe Weather Information Centre: avisos oficiais (padrão CAP) de mais de 130 serviços
    meteorológicos nacionais num arquivo só, e a lista de países. Livre para reutilização por outros
    sites, creditando o serviço de cada país."""
    base = "https://severeweather.wmo.int/json"
    baixar(f"{base}/wmo_all.json", RAW / "mundo" / "swic_avisos.json", timeout=120)
    time.sleep(2)
    baixar(f"{base}/wmo_member.json", RAW / "mundo" / "swic_membros.json", timeout=60)


# ---------------------------------------------------------------- notícias
# RSS oficiais de publicadores que autorizam a reprodução com indicação da fonte. (O Google Notícias
# não é usado: os termos dele proíbem exibir o conteúdo publicamente e o robots.txt bloqueia o RSS.)
FEEDS = {
    # Agência Brasil (EBC): "Reprodução autorizada mediante indicação da fonte"; robots.txt pede 10 s entre acessos
    "agencia_brasil_ultimas": "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml",
    "agencia_brasil_meio_ambiente": "https://agenciabrasil.ebc.com.br/rss/meio-ambiente/feed.xml",
    "agencia_brasil_geral": "https://agenciabrasil.ebc.com.br/rss/geral/feed.xml",
    # ONU News em português, tema mudança climática (atribuição e link para a notícia original)
    "onu_news_clima": "https://news.un.org/feed/subscribe/pt/news/topic/climate-change/feed/rss.xml",
    # Cemaden (gov.br, licença CC BY-ND 3.0)
    "cemaden": "https://www.gov.br/cemaden/pt-br/assuntos/noticias-cemaden/RSS",
}
DOMINIOS_FORA = (".pt", ".ao", ".mz", ".cv", ".gw", ".st", ".tl", ".mo")   # países lusófonos fora do Brasil


def _gdelt_arquivo(url: str) -> list[dict]:
    """Lê um arquivo GKG "translingual" de 15 minutos do GDELT e devolve só as notícias em português,
    de veículos brasileiros (ou que citam o Brasil), cuja manchete trata de clima ou desastres."""
    z = zipfile.ZipFile(io.BytesIO(baixar(url, timeout=180, tentativas=2)))
    saida = []
    with z.open(z.namelist()[0]) as f:
        for row in csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="\t"):
            # Colunas do GKG 2.1: 1 data, 3 domínio, 4 link, 9/10 locais, 25 idioma de origem, 26 extras (título)
            if len(row) < 27 or "srclc:por" not in (row[25] or ""):
                continue
            dominio, link, locais = row[3].lower(), row[4], row[10] or row[9]
            if dominio.endswith(DOMINIOS_FORA) or not (dominio.endswith(".br") or "#BR" in locais):
                continue
            m = re.search(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", row[26] or "")
            titulo = " ".join(html.unescape(m.group(1)).split()) if m else ""
            if titulo and any(rx.search(titulo) for rx in RX_TEMAS.values()):
                saida.append({"titulo": titulo, "link": link, "dominio": dominio, "data": row[1]})
    return saida


def gdelt(horas: int) -> list[dict]:
    """GDELT Project (uso livre, com citação e link): lê os arquivos de 15 minutos das últimas `horas`,
    como o GDELT recomenda para uso automatizado (a API dele aceita só 1 consulta a cada 5 s)."""
    ultimo = baixar(f"{GDELT}/lastupdate-translation.txt", timeout=60).decode()
    fim = datetime.strptime(re.search(r"/(\d{14})\.translation\.gkg", ultimo).group(1), "%Y%m%d%H%M%S")
    itens, falhas, n = [], 0, horas * 4 + 1
    for i in range(n):
        t = fim - timedelta(minutes=15 * i)
        try:
            itens += _gdelt_arquivo(f"{GDELT}/{t:%Y%m%d%H%M%S}.translation.gkg.csv.zip")
        except (RuntimeError, zipfile.BadZipFile):
            falhas += 1   # o índice anuncia arquivos alguns minutos antes de eles existirem
        time.sleep(1)
        if i and i % 48 == 0:
            print(f"  GDELT: {i}/{n} arquivos lidos, {len(itens)} manchetes até agora")
    print(f"  GDELT: {len(itens)} manchetes em {horas} h ({falhas} arquivos indisponíveis)")
    if falhas > n // 2:
        raise RuntimeError(f"GDELT: {falhas} arquivos indisponíveis")
    return itens


def noticias(horas: int = GDELT_HORAS) -> None:
    """Manchetes do GDELT e dos RSS oficiais. Sem o GDELT, seguem os RSS; só falha se tudo falhar."""
    pasta = RAW / "noticias"
    for velho in [*pasta.glob("*.xml"), *pasta.glob("*.json")]:   # não deixa arquivos antigos para o tratamento
        velho.unlink()
    try:
        gravar_json(gdelt(horas), pasta / "gdelt.json")
    except Exception as erro:  # noqa: BLE001
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


# ---------------------------------------------------------------- execução
FONTES = {"enso": enso, "pacifico": pacifico, "clima": clima, "previsao": previsao, "avisos": avisos, "focos": focos, "mundo": mundo,
          "swic": swic, "noticias": noticias}


def main(fontes: list[str], gdelt_horas: int = GDELT_HORAS) -> None:
    """Coleta cada fonte pedida e registra em data/raw/status_coleta.json se ela funcionou.
    Uma fonte fora do ar não interrompe as outras."""
    arq = RAW / "status_coleta.json"
    status = ler_json(arq) if arq.exists() else {}
    for nome in fontes:
        print(f"== {nome}")
        try:
            FONTES[nome](gdelt_horas) if nome == "noticias" else FONTES[nome]()
            status[nome] = {"ok": True, "quando": agora().isoformat(timespec="minutes")}
        except Exception as erro:  # noqa: BLE001
            traceback.print_exc()
            status[nome] = {"ok": False, "quando": agora().isoformat(timespec="minutes"), "erro": str(erro)[:300]}
    gravar_json(status, arq, compacto=False)
    falhas = [k for k in fontes if not status[k]["ok"]]
    print("Coleta concluída." + (f" Falharam: {', '.join(falhas)}" if falhas else ""))


def _horas_validas(v: str) -> int:
    """Aceita só um número inteiro de 1 a 336 (14 dias) no --gdelt-horas."""
    if not v.isdigit() or not 1 <= int(v) <= 336:
        raise argparse.ArgumentTypeError("use um número inteiro de 1 a 336")
    return int(v)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Coleta das fontes do Monitor El Niño.")
    ap.add_argument("--fonte", nargs="*", default=list(FONTES), choices=list(FONTES))
    ap.add_argument("--gdelt-horas", type=_horas_validas, default=GDELT_HORAS, metavar="1-336",
                    help="horas de notícias do GDELT a ler (padrão 3; na carga inicial, 72)")
    args = ap.parse_args()
    main(args.fonte, args.gdelt_horas)
