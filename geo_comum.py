"""
geo_comum.py — Malhas compactas para o D3 (mesmas regras do painel Eleições 2026, 03_painel.py).
Só é usado localmente (03_painel.py e 00_referencias.py); o GitHub Actions não precisa do geopandas.
"""
from __future__ import annotations

import json

import geopandas as gpd
import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient


def sentido_d3(g):
    """O D3 (geometria esférica) espera o anel externo no sentido horário.
    Pedaços sem área (ilhas que colapsaram na simplificação) são descartados: o D3 os
    interpretaria como o globo inteiro."""
    partes = [g] if isinstance(g, Polygon) else list(g.geoms) if isinstance(g, MultiPolygon) else []
    partes = [orient(p, sign=-1.0) for p in partes if p.area > 0]
    if not partes:
        return g
    return partes[0] if len(partes) == 1 else MultiPolygon(partes)


def geo_compacto(gdf: gpd.GeoDataFrame, tolerancia: float, casas: int = 3) -> dict:
    gdf = gdf.copy()
    simpl = shapely.set_precision(gdf.geometry.simplify(tolerancia, preserve_topology=True).values, 10 ** -casas)
    gdf["geometry"] = gpd.GeoSeries(simpl, index=gdf.index, crs=gdf.crs).map(sentido_d3)
    gj = json.loads(gdf.to_json(drop_id=True))

    def arred(c):
        return [arred(x) for x in c] if isinstance(c[0], list) else [round(c[0], casas), round(c[1], casas)]

    for f in gj["features"]:
        f["geometry"]["coordinates"] = arred(f["geometry"]["coordinates"])
    return gj
