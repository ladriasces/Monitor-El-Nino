# Monitor El Niño · clima no Brasil e no mundo

**LADRI — Laboratório de Dados e Relações Internacionais · ASCES-UNITA**

Plataforma cidadã para acompanhar o El Niño e seus efeitos: a situação do fenômeno no Oceano Pacífico, a chuva e a temperatura em todo o Brasil, os avisos meteorológicos, as queimadas, os desastres no mundo e as notícias sobre o clima. Tudo com dados abertos, atualizados automaticamente 4 vezes por dia.

🔗 **Site:** https://ladriasces.github.io/Monitor-El-Nino/

## O que tem aqui

| Aba | Conteúdo | Fonte |
|---|---|---|
| **Agora** | Resumo do dia, "Meu lugar" (município escolhido por quem acessa), mapa de chuva, notícias | todas |
| **O El Niño no oceano** | Índice ONI desde 1950, comparação com os maiores El Niños, regiões Niño semana a semana, boletim do NOAA | NOAA/CPC |
| **Chuva e temperatura** | Mapa das 510 regiões imediatas do IBGE (30 e 90 dias contra 1991–2020; previsão de 7 dias), série diária, estados e rankings | NASA POWER, Open-Meteo |
| **Alertas e queimadas** | Avisos do INMET por mesorregião; focos de queimada (48 h, acumulado do ano contra 2003–2025, estados, biomas, municípios) | INMET, INPE |
| **Mundo** | Temperatura média global diária (recordes); países com avisos meteorológicos oficiais graves; desastres | Copernicus C3S (ERA5), OMM (SWIC), GDACS |
| **Notícias** | Manchetes dos últimos 14 dias, por estado, região e tema (título, veículo, data e link) | GDELT Project, Agência Brasil, ONU News, Cemaden |

**Meu lugar:** quem acessa escolhe o município, e a região dele aparece em destaque em todas as abas. A escolha fica só no navegador da pessoa.

## Como funciona

```
00_referencias.py   uma vez, no computador do LADRI: malhas e divisões do IBGE, normais 1991–2020
                    (NASA POWER) e histórico de queimadas 2003–2025 (INPE)            -> data/ref/
01_coleta.py        todo dia (GitHub Actions): baixa as fontes                        -> data/raw/
02_tratamento.py    todo dia (GitHub Actions): calcula os indicadores                 -> docs/dados/*.json
03_painel.py        quando o visual muda: monta o site com as malhas embutidas        -> docs/index.html
04_validar.py       antes de cada publicação: confere dados, links e a segurança do site
```

O site (`docs/index.html`) é fixo. Ao abrir, ele lê os dados do dia (`docs/dados/*.json`). A rotina `.github/workflows/atualizar.yml` roda às 3h20 (completa), 9h20, 15h20 e 21h20 (só avisos, focos e notícias), horário de Brasília. Ela publica direto no GitHub Pages e grava no repositório só a série de focos de queimada, que cresce dia a dia. Assim o repositório não acumula os JSON de cada dia. Se a validação reprovar, nada é publicado e o site continua na última versão boa.

Se uma fonte estiver fora do ar, as outras seguem normalmente: a plataforma mantém os últimos dados daquela fonte e mostra a data deles na aba *Agora*.

## Como reproduzir no computador

```bash
pip install -r requirements.txt
python 00_referencias.py      # só na primeira vez (~10 min; baixa o histórico do INPE)
python 01_coleta.py           # ~4 min (inclui as pausas pedidas pelo GDACS e pela Agência Brasil)
python 02_tratamento.py
python 03_painel.py
python 04_validar.py
python -m http.server 8770 --directory docs   # abra http://localhost:8770
```

## Publicar no GitHub (uma vez)

1. Criar o repositório `Monitor-El-Nino` na conta `ladriasces` e enviar esta pasta.
2. Em **Settings → Pages**, escolher **Source: GitHub Actions**.
3. Em **Actions**, rodar *Atualizar dados e publicar* uma vez à mão (*Run workflow*), com **72** no campo de horas do GDELT. Essa carga inicial traz as notícias dos últimos 3 dias (cerca de 850 manchetes; medido: ~290 por dia) e leva uns 15 minutos. Depois disso, as execuções automáticas leem 7 horas por vez, e a aba acumula 14 dias.

## Fontes, licenças e condições de uso

Todas as fontes são públicas e gratuitas. A plataforma não tem fins comerciais, cita cada fonte como ela pede e mostra das notícias só a manchete, o veículo, a data e o link (sem textos nem fotos).

| Fonte | O que usamos | Condição de uso (verificada em 11/2026) |
|---|---|---|
| **NOAA / Climate Prediction Center** | `oni.ascii.txt`, `wksst9120.for`, *ENSO Diagnostic Discussion* | Obra do governo dos EUA, de domínio público |
| **NASA POWER** (LaRC) | Chuva e temperatura diárias e normais 1991–2020 (MERRA-2) por região imediata | Uso livre; crédito pedido: "dados obtidos do projeto POWER do Langley Research Center da NASA, financiado pela NASA Earth Science Division" |
| **Open-Meteo** | Previsão de 7 dias | CC BY 4.0; uso não comercial sem chave; link "Open-Meteo.com" junto dos dados |
| **INMET** | Avisos meteorológicos (RSS oficial) | Reprodução permitida citando a fonte (aviso de licença do próprio RSS) |
| **INPE / Programa Queimadas** | Focos diários e anuais (satélite de referência AQUA_M-T, desde 2003) | Dados abertos do governo federal, citando o Programa Queimadas/INPE |
| **IBGE** | Malhas e divisões territoriais | Dados abertos do governo federal |
| **OMM — WMO Severe Weather Information Centre** | Avisos meteorológicos oficiais (severos e extremos) em vigor, dos serviços nacionais de mais de 130 países, num arquivo só (`severeweather.wmo.int/json/wmo_all.json`) | "Livre para reutilização por veículos de mídia e outros sites", creditando o serviço de cada país (nota de uso do SWIC). O nome do serviço aparece em cada país do mapa |
| **GDACS** (ONU e Comissão Europeia) | Eventos com alerta laranja ou vermelho e ciclones | API pública e gratuita, com crédito "Global Disaster Alert and Coordination System, GDACS"; no máximo 1 acesso por minuto |
| **Copernicus C3S / ECMWF** (Climate Pulse) | Temperatura média global diária do ERA5 | Licença Copernicus (uso livre com atribuição: "contém informações modificadas do Copernicus Climate Change Service") |
| **GDELT Project** | Manchetes em português de veículos brasileiros sobre clima e desastres (arquivos "translingual" de 15 minutos) | Uso livre, acadêmico e comercial, com citação e link para gdeltproject.org. Usamos os arquivos em lote, como o GDELT recomenda (a API tem limite de 1 consulta a cada 5 s) |
| **Agência Brasil (EBC)** | Manchetes (RSS oficial, filtradas por tema) | "Reprodução autorizada mediante indicação da fonte", uso não comercial; acessos a cada 10 s, como pede o robots.txt |
| **ONU News** (português) | Manchetes do tema mudança climática (RSS oficial) | Atribuição à ONU News com link para a notícia |
| **Cemaden** (gov.br) | Manchetes (RSS oficial) | Conteúdo do gov.br sob CC BY-ND 3.0 |
| **Natural Earth** | Mapa-múndi | Domínio público |

**Manchetes de veículos (via GDELT):** o GDELT só indica onde a notícia saiu; o conteúdo é de cada veículo. A plataforma mostra a manchete com o nome do veículo e o link para o site dele, sem texto nem foto (citação com indicação da fonte, art. 46, I, "a", da Lei 9.610/98). Agregadores e redes sociais ficam de fora (`data/ref/noticias_bloqueio.txt`). Um veículo que pedir para sair é incluído nesse arquivo.

**O que foi descartado e por quê:** o Google Notícias. Os termos dele proíbem exibir o conteúdo publicamente e o `robots.txt` bloqueia o acesso automatizado ao RSS. O Climate Reanalyzer também saiu: o `robots.txt` dele bloqueia acessos automatizados, e a mesma série vem agora direto da fonte primária (Copernicus).

## Segurança

- **Site estático**, sem servidor, banco de dados, login ou formulário. Não coleta dados pessoais; o "Meu lugar" fica só no navegador de quem acessa.
- **Política de segurança de conteúdo (CSP):** o navegador só executa o script do painel (autorizado pelo hash exato), o D3 do cdnjs e o contador anônimo. Scripts injetados são bloqueados (testado).
- **Integridade (SRI)** no D3: se o arquivo do CDN for alterado, o navegador não o executa.
- **Conteúdo externo tratado como não confiável:** textos sempre escapados; links só `http(s)` (um `javascript:` vira `#`); XML lido com o `defusedxml`; níveis de alerta conferidos por lista fechada.
- **Automação:** ações do GitHub fixadas pelo SHA do commit; permissões mínimas; sem segredos; `04_validar.py` impede publicar dados quebrados ou inseguros.
- **Contagem de acessos** com o GoatCounter: sem cookies e sem dados pessoais.

## Notas de método

- **Anomalia** = diferença em relação à média de 1991–2020 do mesmo produto (NASA POWER), somando as normais mensais dia a dia no período. Chuva em %, temperatura em °C.
- Onde a chuva normal do período é muito baixa (menos de 1/3 de mm por dia), a diferença em % não é calculada.
- O NASA POWER tem cerca de 3 dias de atraso. O painel usa o último dia com dados em pelo menos 95% das regiões.
- **Conferência com fonte independente:** os 90 dias até 07/11/2026 foram comparados com o ERA5 (Open-Meteo). Rio de Janeiro: 558 mm (POWER) contra 521 mm (ERA5), com normal de 292 mm. Caruaru: 124 contra 89 mm (normal de 174). Porto Alegre: 464 contra 407 mm (normal de 377). Teresina: 7 contra 13 mm (normal de 47). As duas fontes concordam na direção das anomalias.
- **Queimadas:** o acumulado do ano usa o satélite de referência do INPE, como nas séries oficiais. Os pontos das últimas 48 horas usam todos os satélites. Para estados e biomas, a média do mesmo período considera os meses completos mais a fração do mês corrente.
- **Classificação do ONI** (NOAA): El Niño a partir de +0,5 °C; fraco < 1,0; moderado < 1,5; forte < 2,0; muito forte ≥ 2,0.
- **Notícias:** o estado é marcado quando a manchete cita o estado, a capital (com contexto, nos nomes ambíguos), a sigla, o gentílico ou um município que só existe naquele estado; no g1, também pelo endereço da notícia. A região é marcada quando é citada pelo nome. Manchetes iguais em vários veículos (texto de agência) aparecem uma vez. A cada execução, o GDELT é lido nas últimas 7 horas (cerca de 30 arquivos de 15 minutos). Como os feeds oficiais trazem só as notícias mais recentes, cada atualização soma as novas às já publicadas, até 14 dias.
- **Avisos no mundo (OMM):** entram os avisos em vigor de nível severo (3) ou extremo (4) no padrão CAP. Avisos publicados em dois idiomas (mesmo identificador, área, nível e prazo) contam uma vez. Ilhas que não aparecem no mapa-múndi ganham um círculo na posição informada pela OMM. O GDACS não cobre tempestades fora dos trópicos (como as de inverno na Europa); por isso o mapa usa as duas fontes.
- **Virada do ano (queimadas):** em 1º de janeiro, até sair o primeiro dado do ano novo, o painel mostra o ano que terminou, completo.
- A plataforma **não substitui os alertas oficiais** da Defesa Civil e do INMET.

## Como esta plataforma foi feita

Desenvolvida pelo LADRI com o auxílio do **Claude**, assistente de inteligência artificial da Anthropic, que ajudou a escrever o código de coleta, tratamento e visualização. A definição dos recortes e a revisão do conteúdo são da equipe do LADRI. O visual e parte do código vêm do painel [Eleições 2026](https://ladriasces.github.io/Elei-es-2026---LADRI/).
