# Monitor El Niño

**LADRI — Laboratório de Dados e Relações Internacionais · ASCES-UNITA**

🔗 **https://ladriasces.github.io/Monitor-El-Nino/**

## O que é

Uma plataforma aberta para qualquer pessoa acompanhar o El Niño e o clima: a situação do fenômeno no Oceano Pacífico, a chuva e a temperatura em cada região do Brasil, os avisos meteorológicos, as queimadas, os alertas no mundo e as notícias sobre o tema. Tudo vem de fontes públicas e oficiais e se atualiza sozinho, 4 vezes por dia.

## Como usar

Abra o site e, se quiser, escolha o seu município em **"Escolha seu município"** (digite o nome ou use a sua localização). A partir daí, o seu lugar aparece em destaque em todas as abas.

| Aba | O que mostra |
|---|---|
| **Agora** | Resumo do dia e o seu lugar: chuva e temperatura recentes, previsão de 7 dias, avisos e notícias |
| **O El Niño no oceano** | O que é o fenômeno, o índice desde 1950, a comparação com os maiores El Niños e o boletim do NOAA |
| **Chuva e temperatura** | Mapa das 510 regiões do país comparadas com a média de 1991–2020, e a previsão de 7 dias |
| **Alertas e queimadas** | Avisos do INMET em vigor e focos de queimada (últimas 48 horas e acumulado do ano) |
| **Mundo** | Temperatura do planeta, países com avisos meteorológicos graves e desastres em curso |
| **Notícias** | Manchetes dos últimos 14 dias, por estado, região e tema, com link para o veículo |

Em **Dados e método** estão as fontes e as explicações de cada número.

## Como funciona

Quatro vezes por dia (3h20, 9h20, 15h20 e 21h20, horário de Brasília), uma rotina automática no GitHub busca os dados nas fontes, calcula os indicadores, confere tudo e publica o site. Ninguém precisa deixar um computador ligado. Se uma fonte estiver fora do ar, o site mantém os últimos dados dela e mostra a data.

**Fontes:** NOAA (El Niño), NASA POWER e Open-Meteo (chuva, temperatura e previsão), INMET (avisos), INPE (queimadas), Organização Meteorológica Mundial e GDACS (alertas no mundo), Copernicus (temperatura global), GDELT, Agência Brasil, ONU News e Cemaden (notícias) e IBGE (mapas).

```
00_referencias.py   tabelas fixas (municípios, regiões, médias de 1991–2020, histórico de queimadas) — roda uma vez
01_coleta.py        baixa os dados das fontes
02_tratamento.py    calcula os indicadores e gera os arquivos lidos pelo site
03_painel.py        monta o site (só quando o visual muda)
04_validar.py       confere dados e segurança antes de publicar
clima_comum.py      funções e constantes usadas pelos scripts
painel/             modelo do site (template.html) e logo
docs/               o site publicado
data/ref/           tabelas de referência
.github/workflows/  a rotina automática
```

## Para a equipe do LADRI

- **Atualizar na hora:** em [Actions](https://github.com/ladriasces/Monitor-El-Nino/actions) → *Atualizar dados e publicar* → *Run workflow*.
- **Tirar um veículo das notícias** (a pedido dele): acrescente o domínio em `data/ref/noticias_bloqueio.txt`.
- **Rodar no computador:**

  ```bash
  pip install -r requirements.txt
  python 01_coleta.py
  python 02_tratamento.py
  python 04_validar.py
  python -m http.server 8770 --directory docs    # abra http://localhost:8770
  ```

  Para mudar o visual, edite `painel/template.html` e rode `python 03_painel.py` (precisa de `pip install geopandas`).

## Créditos

Desenvolvida pelo LADRI com o auxílio do Claude (Anthropic). Contato: [@ladri_asces](https://www.instagram.com/ladri_asces/) · ladri.lapri.asces@gmail.com
