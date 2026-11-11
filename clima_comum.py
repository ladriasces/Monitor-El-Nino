"""
clima_comum.py — Constantes e funções compartilhadas pelos scripts do Monitor El Niño (LADRI).

Pastas do projeto:
  data/raw/    arquivos brutos baixados a cada coleta (não vão para o repositório)
  data/ref/    tabelas de referência (municípios, regiões, normais, histórico de queimadas) — versionadas
  docs/dados/  JSON lidos pelo site (gerados a cada atualização e publicados direto no GitHub Pages)
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------- pastas e horário
RAIZ = Path(__file__).resolve().parent
RAW = RAIZ / "data" / "raw"
REF = RAIZ / "data" / "ref"
SAIDA = RAIZ / "docs" / "dados"

BRT = timezone(timedelta(hours=-3))   # horário de Brasília (sem horário de verão desde 2019)

# ---------------------------------------------------------------- estados
NOME_UF = {
    "RO": "Rondônia", "AC": "Acre", "AM": "Amazonas", "RR": "Roraima", "PA": "Pará", "AP": "Amapá", "TO": "Tocantins",
    "MA": "Maranhão", "PI": "Piauí", "CE": "Ceará", "RN": "Rio Grande do Norte", "PB": "Paraíba", "PE": "Pernambuco",
    "AL": "Alagoas", "SE": "Sergipe", "BA": "Bahia", "MG": "Minas Gerais", "ES": "Espírito Santo",
    "RJ": "Rio de Janeiro", "SP": "São Paulo", "PR": "Paraná", "SC": "Santa Catarina", "RS": "Rio Grande do Sul",
    "MS": "Mato Grosso do Sul", "MT": "Mato Grosso", "GO": "Goiás", "DF": "Distrito Federal",
}
# Código IBGE do estado -> sigla (as malhas do IBGE identificam os estados pelo código)
COD_UF = {11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO", 21: "MA", 22: "PI", 23: "CE", 24: "RN",
          25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA", 31: "MG", 32: "ES", 33: "RJ", 35: "SP", 41: "PR", 42: "SC",
          43: "RS", 50: "MS", 51: "MT", 52: "GO", 53: "DF"}

# ---------------------------------------------------------------- acesso às fontes
# Identificação honesta em todas as requisições (boa prática com servidores públicos)
sessao = requests.Session()
sessao.headers["User-Agent"] = "LADRI-ASCES plataforma El Nino (pesquisa academica)"


def agora() -> datetime:
    """Data e hora atuais no horário de Brasília."""
    return datetime.now(BRT)


def baixar(url: str, destino: Path | None = None, tentativas: int = 4, timeout: int = 60, cache: bool = False,
           params: dict | None = None) -> bytes:
    """Baixa `url` e devolve o conteúdo, tentando de novo (com espera crescente) se a fonte falhar.

    destino: se informado, grava o conteúdo nesse arquivo.
    cache:   se True e o arquivo já existir, não baixa de novo (usado nas referências fixas).
    Levanta RuntimeError depois da última tentativa.
    """
    if cache and destino is not None and destino.exists() and destino.stat().st_size > 0:
        return destino.read_bytes()
    for i in range(tentativas):
        try:
            resp = sessao.get(url, timeout=timeout, params=params)
            resp.raise_for_status()
            if destino is not None:
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(resp.content)
            return resp.content
        except requests.RequestException as erro:
            if i == tentativas - 1:
                raise RuntimeError(f"Falha ao baixar {url}: {erro}") from erro
            time.sleep(3 * (i + 1))
    return b""


def ler_json(caminho: Path):
    """Lê um arquivo JSON em UTF-8."""
    return json.loads(caminho.read_text(encoding="utf-8"))


def gravar_json(obj, caminho: Path, compacto: bool = True) -> None:
    """Grava `obj` em JSON (UTF-8, fim de linha LF). `compacto=False` deixa o arquivo legível."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(obj, ensure_ascii=False, separators=(",", ":") if compacto else None, indent=None if compacto else 1)
    caminho.write_text(texto, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- texto e números
def chave(nome: str) -> str:
    """Normaliza um nome para comparação: sem acentos, minúsculas, sem hífens nem espaços extras."""
    s = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.lower().replace("-", " ").replace("'", " ").split())


# Estado por extenso (como vem nos arquivos do INPE, ex.: "PARÁ") -> sigla
UF_POR_NOME = {chave(nome): sg for sg, nome in NOME_UF.items()}


def url_segura(u) -> str | None:
    """Devolve o link só se for http(s). Um link 'javascript:' vindo de uma fonte externa viraria código no site."""
    u = str(u or "").strip()
    return u if u.lower().startswith(("https://", "http://")) else None


def r(x, n: int = 2):
    """Arredonda para `n` casas, devolvendo None para valores ausentes (None ou NaN)."""
    try:
        if x is None or x != x:
            return None
        return round(float(x), n)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- temas das notícias
# Classificação pela manchete (usada na coleta do GDELT e no tratamento). Expressões com limites de
# palavra para evitar falsos positivos como "cessar-fogo" ou "clima político".
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
