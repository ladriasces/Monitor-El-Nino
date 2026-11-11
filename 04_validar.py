"""
04_validar.py — Confere os dados e o site antes de publicar (roda no GitHub Actions depois do tratamento).

  python 04_validar.py

Erros (estrutura quebrada, valor impossível, link inseguro, fonte não autorizada, CSP inválida)
interrompem a publicação: o site continua na última versão boa. Avisos (dado atrasado porque uma
fonte ficou fora do ar) só aparecem no registro, já que o painel mostra a data de cada fonte.
"""
from __future__ import annotations

import base64
import hashlib
import re
import sys
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from clima_comum import RAIZ, SAIDA, UFS, ler_json

erros: list[str] = []
avisos: list[str] = []
FONTES_NOTICIAS = {"Agência Brasil": "https://agenciabrasil.ebc.com.br/", "ONU News": "https://news.un.org/",
                   "Cemaden": "https://www.gov.br/cemaden/"}


def erro(cond: bool, msg: str) -> None:
    if not cond:
        erros.append(msg)


def aviso(cond: bool, msg: str) -> None:
    if not cond:
        avisos.append(msg)


def recente(iso: str | None, dias: int) -> bool:
    return bool(iso) and date.fromisoformat(iso[:10]) >= date.today() - timedelta(days=dias)


def link_ok(u) -> bool:
    return isinstance(u, str) and u.startswith(("https://", "http://"))


def carregar(nome: str):
    try:
        return ler_json(SAIDA / f"{nome}.json")
    except Exception as e:  # noqa: BLE001
        erros.append(f"{nome}.json ausente ou inválido: {e}")
        return None


def validar() -> None:
    E = carregar("enso")
    if E:
        erro(len(E["oni"]) > 900, "ONI com poucos registros")
        erro(-4 < E["atual"]["oni"] < 4, f"ONI fora do possível: {E['atual']['oni']}")
        erro(E["atual"]["fase"] in ("el_nino", "la_nina", "neutro"), "fase do ENSO inválida")
        erro(all(-6 < s[3] < 6 for s in E["semanal"]), "Niño 3.4 semanal fora do possível")
        aviso(recente(E["atual"]["nino34_semana"], 21), "Niño semanal com mais de 3 semanas")

    C = carregar("clima")
    if C:
        reg = C["regioes"]
        erro(len(reg) >= 459, f"clima: só {len(reg)} de 510 regiões")
        for rid, v in reg.items():
            p30, n30, a30, t30, ta30 = v[:5]
            erro(p30 is None or 0 <= p30 < 3000, f"clima {rid}: chuva impossível {p30}")
            erro(t30 is None or -10 < t30 < 45, f"clima {rid}: temperatura impossível {t30}")
            erro(ta30 is None or -12 < ta30 < 12, f"clima {rid}: anomalia de temperatura impossível {ta30}")
        aviso(recente(C["fim"], 10), f"clima: último dado em {C['fim']}")
        erro(len(C["previsao"]["datas"] or []) == 7, "previsão sem 7 dias")
        series = list((SAIDA / "serie").glob("*.json"))
        erro(len(series) == 27, f"séries diárias: {len(series)} de 27 estados")

    F = carregar("focos")
    if F:
        a = F["ano"]
        erro(str(a["ano"]) in a["curvas"], "focos: falta a curva do ano")
        erro(set(F["ufs"]) == set(UFS), "focos: estados incompletos")
        erro(all(-75 <= p[1] <= 35 and -75 <= p[0] <= -28 for p in F["h48"]["pontos"]), "focos: ponto fora da América do Sul")
        aviso(recente(F["ultimo_dado"], 3), f"focos: último dado em {F['ultimo_dado']}")

    A = carregar("avisos")
    if A:
        for x in A["avisos"]:
            erro(x["sev"] in (1, 2, 3), f"aviso {x['id']}: severidade inválida")
            erro(x["link"] is None or link_ok(x["link"]), f"aviso {x['id']}: link inseguro")

    M = carregar("mundo")
    if M:
        t = M["temp_global"]
        erro(-3 < (t["anom_ultimo"] or 0) < 4, f"temperatura global: anomalia impossível {t['anom_ultimo']}")
        erro(10 < min(v for v in t["atual"] if v is not None) and max(v for v in t["atual"] if v is not None) < 20,
             "temperatura global fora do possível")
        aviso(recente(t["ultimo"], 10), f"temperatura global: último dado em {t['ultimo']}")
        for e in M["eventos"]:
            erro(e["alerta"] in ("Green", "Orange", "Red"), f"GDACS: nível inválido {e['alerta']}")
            erro(e["link"] is None or link_ok(e["link"]), "GDACS: link inseguro")

    S = carregar("swic")
    if S:
        for p in S["paises"]:
            erro(p["max"] in (3, 4), f"OMM: nível inválido em {p['iso3']}")
            erro(bool(re.fullmatch(r"[A-Z]{3}", p["iso3"])), f"OMM: código de país inválido {p['iso3']}")
            erro(p["url"] is None or link_ok(p["url"]), f"OMM: link inseguro em {p['iso3']}")
            erro(all(s in (3, 4) for _, s, _ in p["eventos"]), f"OMM: nível de evento inválido em {p['iso3']}")
        aviso(recente(S["atualizado"], 2), f"OMM: avisos atualizados em {S['atualizado']}")

    N = carregar("noticias")
    if N:
        bloq = {x.strip().lower() for x in (RAIZ / "data" / "ref" / "noticias_bloqueio.txt").read_text(encoding="utf-8").splitlines()
                if x.strip() and not x.startswith("#")}
        for n in N["noticias"]:
            erro(link_ok(n["link"]), f"notícia com link inseguro: {n['link'][:60]}")
            h = (urlparse(n["link"]).hostname or "").lower()
            erro(not any(h == b or h.endswith("." + b) for b in bloq), f"notícia de domínio bloqueado: {h}")
            if n.get("origem") == "gdelt":
                erro(bool(h), "notícia do GDELT sem endereço")
            else:
                erro(n["fonte"] in FONTES_NOTICIAS, f"notícia de fonte não autorizada: {n['fonte']}")
                erro(n["link"].startswith(FONTES_NOTICIAS.get(n["fonte"], "\0")), f"notícia com link fora do site da fonte: {n['link'][:60]}")
            erro(datetime.fromisoformat(n["data"]).date() >= date.today() - timedelta(days=15), "notícia com mais de 14 dias")
        aviso(len(N["noticias"]) > 0, "nenhuma notícia")

    # Site: a CSP autoriza o script do painel pelo hash exato; se o arquivo mudar (ex.: \r\n), o site para de funcionar
    html = (RAIZ / "docs" / "index.html").read_bytes()
    erro(b"\r\n" not in html, "docs/index.html com fim de linha \\r\\n (quebra o hash da CSP)")
    texto = html.decode("utf-8")
    m = re.search(r"script-src 'sha256-([^']+)'", texto)
    scripts = re.findall(r"<script>(.*?)</script>", texto, flags=re.S)
    erro(bool(m) and len(scripts) == 1, "CSP ou script do painel não encontrados")
    if m and len(scripts) == 1:
        h = base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode("ascii")
        erro(h == m.group(1), "o hash da CSP não corresponde ao script do painel")
    erro('integrity="sha512-' in texto, "D3 sem verificação de integridade (SRI)")
    erro(" onclick=" not in texto and " onerror=" not in texto, "atributo de evento embutido no HTML (bloqueado pela CSP)")


if __name__ == "__main__":
    validar()
    for a in avisos:
        print("AVISO:", a)
    for e in erros[:40]:
        print("ERRO:", e)
    print(f"Validação: {len(erros)} erro(s), {len(avisos)} aviso(s).")
    sys.exit(1 if erros else 0)
