"""
03_painel.py — Gera o site (docs/index.html) a partir de painel/template.html.

  python 03_painel.py

O HTML leva embutido só o que é fixo: as malhas dos mapas (estados, regiões imediatas, mesorregiões e
mundo), a lista de municípios (para a busca do "Meu lugar") e o logo. Os dados de cada dia ficam em
docs/dados/*.json, que o site lê ao abrir. Por isso este script só precisa rodar quando o visual
(template) mudar. Gera também a imagem de prévia para as redes sociais (docs/img/previa.jpg).
Precisa de geopandas, pillow, fonttools e brotli; o GitHub Actions não usa este script.
"""
from __future__ import annotations

import base64
import hashlib
import io
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
# Versão fixa do script do GoatCounter, com o hash publicado (SRI): se o arquivo mudar, o navegador não o executa
SRI_GOATCOUNTER = "sha384-nRw6qfbWyJha9LhsOtSb2YJDyZdKvvCFh0fJYlkquSFjUxp9FVNugbfy8q1jdxI+"
GOATCOUNTER = "ladri"   # contador anônimo de acessos (o mesmo do painel Eleições 2026; o endereço do site separa os dois)
REPO = "https://github.com/ladriasces/Monitor-El-Nino"
SITE = "https://ladriasces.github.io/Monitor-El-Nino/"
DESCRICAO = ("Acompanhe o El Niño, a chuva, o calor, as queimadas, os alertas e as notícias sobre o clima no "
             "Brasil e no mundo, com dados abertos de fontes oficiais. LADRI · ASCES-UNITA.")


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
    pelo hash exato do conteúdo), o D3 do cdnjs e o contador anônimo (os dois com verificação de
    integridade, SRI). Fontes e imagens vêm só do próprio site. Qualquer script injetado é bloqueado."""
    hash_script = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
    gc = f"https://{GOATCOUNTER}.goatcounter.com"
    return ("default-src 'self'; "
            f"script-src 'sha256-{hash_script}' https://cdnjs.cloudflare.com https://gc.zgo.at; "
            "style-src 'self' 'unsafe-inline'; font-src 'self'; "
            f"img-src 'self' data: {gc}; connect-src 'self' {gc}; "
            "object-src 'none'; base-uri 'none'; form-action 'none'")


# ---------------------------------------------------------------- imagem de prévia (redes sociais)
# Imagem que WhatsApp, LinkedIn, Facebook etc. mostram quando alguém compartilha o link: 1200 × 630, com
# o mapa do Pacífico do cabeçalho (mesma escala de cores), o nome da plataforma e o endereço. Ela não traz
# números do dia, para não ficar desatualizada (as redes guardam a imagem por muito tempo).
PREVIA_W, PREVIA_H, PREVIA_TOPO = 1200, 630, 270   # o mapa ocupa os 360 px de baixo (60 linhas de 1° × 6 px)
COR = {"fundo": "#f3efe6", "texto": "#1f2b23", "texto2": "#4a5a4e", "destaque": "#2f6b45", "terra": "#7d9a68"}
ESCALA_MAR = [(-30, "#2f8a7e"), (-5, "#e8dfcc"), (5, "#e8dfcc"), (25, "#c4511f"), (45, "#7e2a0e")]   # = template


def _rgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _lab(c: tuple[int, int, int]) -> tuple[float, float, float]:
    """sRGB -> CIE Lab (D65), para interpolar as cores como o d3.interpolateLab do site."""
    def lin(u):
        u /= 255
        return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(x) for x in c)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    f = lambda v: v ** (1 / 3) if v > 216 / 24389 else (24389 / 27 * v + 16) / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _de_lab(L: float, a: float, b: float) -> tuple[int, int, int]:
    """CIE Lab (D65) -> sRGB."""
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    inv = lambda v: v ** 3 if v ** 3 > 216 / 24389 else (116 * v - 16) / (24389 / 27)
    x, y, z = inv(fx) * 0.95047, inv(fy), inv(fz) * 1.08883
    lin = (3.2406 * x - 1.5372 * y - 0.4986 * z, -0.9689 * x + 1.8758 * y + 0.0415 * z,
           0.0557 * x - 0.2040 * y + 1.0570 * z)
    gama = lambda u: 255 * (12.92 * u if u <= 0.0031308 else 1.055 * u ** (1 / 2.4) - 0.055)
    return tuple(max(0, min(255, round(gama(v)))) for v in lin)


_PONTOS_MAR = [(v, _lab(_rgb(c))) for v, c in ESCALA_MAR]


def cor_mar(v: float) -> tuple[int, int, int]:
    """Cor da anomalia (décimos de °C) na escala do cabeçalho do site."""
    if v <= _PONTOS_MAR[0][0]:
        return _de_lab(*_PONTOS_MAR[0][1])
    for (v0, c0), (v1, c1) in zip(_PONTOS_MAR, _PONTOS_MAR[1:]):
        if v <= v1:
            t = (v - v0) / (v1 - v0)
            return _de_lab(*(a + (b - a) * t for a, b in zip(c0, c1)))
    return _de_lab(*_PONTOS_MAR[-1][1])


def _fonte(arquivo: str, tamanho: int, eixos: dict):
    """Abre uma das fontes do site (woff2 variável, em docs/fontes/) no peso e tamanho óptico pedidos."""
    from fontTools.ttLib import TTFont
    from PIL import ImageFont
    tt = TTFont(RAIZ / "docs" / "fontes" / arquivo)
    tags = [a.axisTag for a in tt["fvar"].axes]
    tt.flavor = None   # woff2 -> ttf em memória (o Pillow não lê woff2)
    buf = io.BytesIO()
    tt.save(buf)
    buf.seek(0)
    f = ImageFont.truetype(buf, tamanho)
    f.set_variation_by_axes([eixos[t] for t in tags])
    return f


def previa() -> None:
    """Gera docs/img/previa.jpg a partir do mapa do Pacífico mais recente (docs/dados/pacifico.json)."""
    from PIL import Image, ImageDraw, ImageFilter
    arq = RAIZ / "docs" / "dados" / "pacifico.json"
    if not arq.exists():
        print("imagem de prévia mantida: falta docs/dados/pacifico.json (rode 01_coleta.py e 02_tratamento.py)")
        return
    W, H, TOPO = PREVIA_W, PREVIA_H, PREVIA_TOPO
    linhas = json.loads(arq.read_text(encoding="utf-8"))["linhas"][10:70]   # 30°S a 30°N (linha 0 = sul)
    mapa = Image.new("RGB", (len(linhas[0]), len(linhas)))
    mapa.putdata([_rgb(COR["terra"]) if v is None else cor_mar(v) for linha in reversed(linhas) for v in linha])
    mapa = mapa.resize((W, H - TOPO), Image.BICUBIC).filter(ImageFilter.GaussianBlur(2.2))
    im = Image.new("RGB", (W, H), _rgb(COR["fundo"]))
    im.paste(mapa, (0, TOPO))
    d = ImageDraw.Draw(im, "RGBA")
    sans = "public-sans-latin-wght-normal.woff2"

    # Caixa tracejada da região Niño 3.4 (5°S–5°N, 170°O–120°O); o mapa vai de 100°L a 300°L
    x0, x1 = (190 - 100) / 200 * W, (240 - 100) / 200 * W
    y0, y1 = TOPO + 25 / 60 * (H - TOPO), TOPO + 35 / 60 * (H - TOPO)
    for x in range(int(x0), int(x1), 14):
        for y in (y0, y1):
            d.line([(x, y), (min(x + 8, x1), y)], fill=COR["texto"], width=2)
    for y in range(int(y0), int(y1), 14):
        for x in (x0, x1):
            d.line([(x, y), (x, min(y + 8, y1))], fill=COR["texto"], width=2)
    d.text((x0 + 2, y0 - 8), "Niño 3.4", font=_fonte(sans, 20, {"wght": 600}), fill=COR["texto"], anchor="ld")

    # Logo do LADRI (na cor do texto, como no site) e identificação, centralizados
    logo = Image.open(PAINEL / "logo_ladri.png").convert("LA").getchannel("A")
    logo = logo.resize((84, round(84 * logo.height / logo.width)), Image.LANCZOS)
    f_id = _fonte(sans, 18, {"wght": 650})
    ident = "LADRI · ASCES-UNITA"
    bx = (W - (logo.width + 14 + d.textlength(ident, font=f_id))) / 2
    im.paste(Image.new("RGB", logo.size, _rgb(COR["texto"])), (round(bx), 30), logo)
    d.text((bx + logo.width + 14, 30 + logo.height / 2), ident, font=f_id, fill=COR["texto2"], anchor="lm")

    # Título e subtítulo centralizados (as miniaturas quadradas cortam as laterais)
    d.text((W / 2, 150), "Monitor El Niño", font=_fonte("fraunces-latin-opsz-normal.woff2", 82, {"opsz": 144, "wght": 650}),
           fill=COR["texto"], anchor="mm")
    d.text((W / 2, 226), "Chuva, calor, queimadas, alertas e notícias no Brasil e no mundo",
           font=_fonte(sans, 27, {"wght": 450}), fill=COR["texto2"], anchor="mm")

    # Legenda do mapa e endereço do site
    f_leg = _fonte(sans, 19, {"wght": 550})
    leg = "Temperatura do mar no Pacífico comparada à média"
    lw = d.textlength(leg, font=f_leg)
    d.rounded_rectangle((40, H - 64, 40 + lw + 196, H - 24), radius=20, fill=(*_rgb(COR["fundo"]), 225))
    d.text((58, H - 44), leg, font=f_leg, fill=COR["texto"], anchor="lm")
    for i in range(120):
        d.line([(58 + lw + 16 + i, H - 50), (58 + lw + 16 + i, H - 38)], fill=cor_mar(-30 + 75 * i / 119))
    f_url = _fonte(sans, 22, {"wght": 650})
    url = SITE.removeprefix("https://").rstrip("/")
    uw = d.textlength(url, font=f_url)
    d.rounded_rectangle((W - 84 - uw, H - 66, W - 40, H - 22), radius=22, fill=COR["destaque"])
    d.text((W - 62, H - 44), url, font=f_url, fill="#ffffff", anchor="rm")

    destino = RAIZ / "docs" / "img" / "previa.jpg"
    im.save(destino, quality=88, optimize=True, progressive=True)
    print(f"docs/img/previa.jpg gerada: {destino.stat().st_size / 1e3:.0f} kB")


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
<meta name="description" content="{DESCRICAO}">
<link rel="canonical" href="{SITE}">
<meta property="og:type" content="website">
<meta property="og:locale" content="pt_BR">
<meta property="og:site_name" content="Monitor El Niño · LADRI">
<meta property="og:title" content="Monitor El Niño">
<meta property="og:description" content="{DESCRICAO}">
<meta property="og:url" content="{SITE}">
<meta property="og:image" content="{SITE}img/previa.jpg">
<meta property="og:image:type" content="image/jpeg">
<meta property="og:image:width" content="{PREVIA_W}">
<meta property="og:image:height" content="{PREVIA_H}">
<meta property="og:image:alt" content="Monitor El Niño: mapa da temperatura do mar no Pacífico, com o aquecimento do El Niño ao longo do equador">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%232f6b45'/%3E%3Cpath d='M5 19c3-6 6-6 9 0s6 6 9 0 4-4 4-4' stroke='white' stroke-width='3' fill='none' stroke-linecap='round'/%3E%3C/svg%3E">
<style>[hidden] {{ display: none !important; }} img {{ max-width: 100%; }}</style>
<script data-goatcounter="https://{GOATCOUNTER}.goatcounter.com/count" async src="https://gc.zgo.at/count.v4.js" integrity="{SRI_GOATCOUNTER}" crossorigin="anonymous"></script>
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
    previa()


if __name__ == "__main__":
    main()
