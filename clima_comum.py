"""
clima_comum.py — Constantes e funções usadas por todos os scripts da plataforma El Niño (LADRI).

Pastas:
  data/raw/    arquivos brutos baixados a cada coleta (fora do repositório)
  data/ref/    tabelas de referência fixas (regiões imediatas, normais climatológicas) — versionadas
  docs/dados/  JSON lidos pelo painel (regravados todo dia pelo GitHub Actions)
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent
RAW = RAIZ / "data" / "raw"
REF = RAIZ / "data" / "ref"
SAIDA = RAIZ / "docs" / "dados"

# Horário de Brasília (sem horário de verão desde 2019)
BRT = timezone(timedelta(hours=-3))

UFS = {
    "RO": ("Rondônia", "Norte"), "AC": ("Acre", "Norte"), "AM": ("Amazonas", "Norte"), "RR": ("Roraima", "Norte"),
    "PA": ("Pará", "Norte"), "AP": ("Amapá", "Norte"), "TO": ("Tocantins", "Norte"),
    "MA": ("Maranhão", "Nordeste"), "PI": ("Piauí", "Nordeste"), "CE": ("Ceará", "Nordeste"),
    "RN": ("Rio Grande do Norte", "Nordeste"), "PB": ("Paraíba", "Nordeste"), "PE": ("Pernambuco", "Nordeste"),
    "AL": ("Alagoas", "Nordeste"), "SE": ("Sergipe", "Nordeste"), "BA": ("Bahia", "Nordeste"),
    "MG": ("Minas Gerais", "Sudeste"), "ES": ("Espírito Santo", "Sudeste"), "RJ": ("Rio de Janeiro", "Sudeste"),
    "SP": ("São Paulo", "Sudeste"), "PR": ("Paraná", "Sul"), "SC": ("Santa Catarina", "Sul"),
    "RS": ("Rio Grande do Sul", "Sul"), "MS": ("Mato Grosso do Sul", "Centro-Oeste"),
    "MT": ("Mato Grosso", "Centro-Oeste"), "GO": ("Goiás", "Centro-Oeste"), "DF": ("Distrito Federal", "Centro-Oeste"),
}
COD_UF = {11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO", 21: "MA", 22: "PI", 23: "CE", 24: "RN",
          25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA", 31: "MG", 32: "ES", 33: "RJ", 35: "SP", 41: "PR", 42: "SC",
          43: "RS", 50: "MS", 51: "MT", 52: "GO", 53: "DF"}
NOME_UF = {sg: nome for sg, (nome, _) in UFS.items()}
REGIOES = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]

sessao = requests.Session()
sessao.headers["User-Agent"] = "LADRI-ASCES plataforma El Nino (pesquisa academica)"


def agora() -> datetime:
    return datetime.now(BRT)


def baixar(url: str, destino: Path | None = None, tentativas: int = 4, timeout: int = 60, cache: bool = False,
           params: dict | None = None) -> bytes:
    """Baixa `url` (com novas tentativas). Se `destino` for dado, grava o arquivo; com `cache=True`,
    reaproveita o arquivo já baixado."""
    if cache and destino is not None and destino.exists() and destino.stat().st_size > 0:
        return destino.read_bytes()
    for i in range(tentativas):
        try:
            r = sessao.get(url, timeout=timeout, params=params)
            r.raise_for_status()
            if destino is not None:
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(r.content)
            return r.content
        except requests.RequestException as erro:
            if i == tentativas - 1:
                raise RuntimeError(f"Falha ao baixar {url}: {erro}") from erro
            time.sleep(3 * (i + 1))
    return b""


def ler_json(caminho: Path):
    return json.loads(caminho.read_text(encoding="utf-8"))


def gravar_json(obj, caminho: Path, compacto: bool = True) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(obj, ensure_ascii=False, separators=(",", ":") if compacto else None, indent=None if compacto else 1)
    caminho.write_text(texto, encoding="utf-8", newline="\n")


def chave(nome: str) -> str:
    """Normaliza nomes para comparação: sem acentos, minúsculas, sem hífens/espaços extras."""
    s = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.lower().replace("-", " ").replace("'", " ").split())


# Estado por extenso (como vem nos arquivos do INPE, ex.: "PARÁ") -> sigla
UF_POR_NOME = {chave(nome): sg for sg, nome in NOME_UF.items()}


# Temas das notícias, classificados pela manchete. Expressões com limites de palavra para evitar falsos
# positivos como "cessar-fogo" ou "clima político". Usadas na coleta (GDELT) e no tratamento.
TEMAS = {
    "el-nino": r"\bel ni[nñ]o\b|\bla ni[nñ]a\b|\bsuper el ni",
    "clima": r"mudanças? climátic|crise climátic|aquecimento global|emissões|\bcop ?\d|\bcop\b|carbono|climátic",
    # "seca" só com contexto de estiagem (e em minúscula no meio da frase): evita "pele seca", "Taxa de Seca", "lei seca"
    "extremos": r"\bchuvas?\b|(?-i:\b(?:a|à|da|na|pela|contra a|com a|de|por) secas?\b|\bsecas\b|^Secas?\b"
                r"|\b[Ss]eca (?:extrema|severa|histórica|prolongada|no|na|em|atinge|afeta)\b)"
                r"|estiagem|onda de calor|calor (extremo|intenso)|temperaturas? (alta|recorde|máxima|acima)"
                r"|enchentes?|inundaç|alagament|tempestade|temporal|ciclone|granizo|vendaval|deslizamento|desastre"
                r"|defesa civil|situação de emergência|calamidade|racionamento|crise hídrica|reservatório|açude|falta d[ea] água",
    "queimadas": r"queimadas?|incêndios? (florest|em veget|no pantanal|na amazônia|no cerrado)|focos? de (calor|incêndio)",
}
RX_TEMAS = {k: re.compile(v, flags=re.I) for k, v in TEMAS.items()}


def url_segura(u) -> str | None:
    """Só aceita links http(s): um link 'javascript:' vindo de uma fonte externa viraria código no site."""
    u = str(u or "").strip()
    return u if u.lower().startswith(("https://", "http://")) else None


def r(x, n: int = 2):
    """Arredonda, devolvendo None para valores ausentes (NaN/None)."""
    try:
        if x is None or x != x:
            return None
        return round(float(x), n)
    except (TypeError, ValueError):
        return None
