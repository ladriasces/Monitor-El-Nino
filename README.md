# Monitor El Niño

**LADRI — Laboratório de Dados e Relações Internacionais · ASCES-UNITA**

🔗 **https://ladriasces.github.io/Monitor-El-Nino/**

## O que é

Uma plataforma aberta para qualquer pessoa acompanhar o El Niño e o clima: a situação do fenômeno no Oceano Pacífico, a chuva e a temperatura em cada região do Brasil, os avisos meteorológicos, as queimadas, os alertas no mundo e as notícias sobre o tema. Tudo vem de fontes públicas e oficiais e se atualiza sozinho: avisos e notícias a cada hora.

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

Uma rotina automática no GitHub busca os dados nas fontes, calcula os indicadores, confere tudo e publica o site. Avisos e notícias são atualizados a cada hora; os focos de queimada, quatro vezes por dia (3h20, 9h20, 15h20 e 21h20, horário de Brasília); e as fontes que publicam dados novos no máximo uma vez por dia (El Niño, temperatura do mar, chuva, temperatura, previsão e desastres no mundo), às 3h20. Ninguém precisa deixar um computador ligado. Se uma fonte estiver fora do ar, o site mantém os últimos dados dela e mostra a data.

**Fontes:** NOAA (El Niño e temperatura do mar), NASA POWER e Open-Meteo (chuva, temperatura e previsão), INMET (avisos), INPE (queimadas), Organização Meteorológica Mundial e GDACS (alertas no mundo), Copernicus (temperatura global), GDELT, Agência Brasil, ONU News e Cemaden (notícias) e IBGE (mapas).

```
00_referencias.py   tabelas fixas (municípios, regiões, médias de 1991–2020, histórico de queimadas) — roda uma vez
01_coleta.py        baixa os dados das fontes
02_tratamento.py    calcula os indicadores e gera os arquivos lidos pelo site
03_painel.py        monta o site (só quando o visual muda)
04_validar.py       confere dados e segurança antes de publicar
clima_comum.py      funções e constantes usadas pelos scripts
painel/             modelo do site (template.html) e logo
docs/               o site publicado (img/: fotos com licença livre)
data/ref/           tabelas de referência
.github/workflows/  a rotina automática
```

## Créditos

Desenvolvida pelo LADRI com o auxílio do Claude (Anthropic). As fotos vêm do Wikimedia Commons, com licenças CC BY, e os créditos completos estão em **Dados e método**; a ilustração dos biomas foi feita para o site. Contato: [@ladri_asces](https://www.instagram.com/ladri_asces/) · ladri.lapri.asces@gmail.com
