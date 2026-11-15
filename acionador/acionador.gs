/**
 * Acionador do Monitor El Niño — Google Apps Script, na conta Google do LADRI.
 *
 * Por que existe: o GitHub não garante as execuções agendadas (neste repositório, descarta quase todas).
 * Este script chama a rotina "Atualizar dados e publicar" a cada 15 minutos pela API do GitHub, no modo
 * "agenda": a própria rotina decide o que está na hora de atualizar e, se não houver nada, termina sem
 * publicar. O agendamento do GitHub continua como reserva.
 *
 * Instalação (uma vez):
 *   1. Em script.google.com, logado na conta do LADRI: Novo projeto; cole este arquivo no lugar do código.
 *   2. Configurações do projeto (engrenagem) > Propriedades do script > Adicionar:
 *        nome GITHUB_TOKEN, valor = a chave de acesso criada no GitHub (fine-grained, só o repositório
 *        Monitor-El-Nino, permissão "Actions: Read and write").
 *      A chave fica só nas propriedades do script: nunca escreva a chave neste código.
 *   3. No editor, escolha a função "acionar" e clique em Executar (autorize o acesso pedido). Deve surgir
 *      uma execução nova em github.com/ladriasces/Monitor-El-Nino/actions, do tipo workflow_dispatch.
 *   4. Escolha a função "instalar" e clique em Executar: cria o gatilho de 15 em 15 minutos.
 *
 * Manutenção: a chave do GitHub expira (no máximo em 1 ano). Quando expirar, o Google envia por e-mail o
 * aviso de falha do gatilho; crie uma chave nova no GitHub e troque o valor de GITHUB_TOKEN no passo 2.
 */

const REPOSITORIO = "ladriasces/Monitor-El-Nino";
const ROTINA = "atualizar.yml";

/** Dispara a rotina no modo "agenda". Falha (e o Google avisa por e-mail) se o GitHub recusar. */
function acionar() {
  const chave = PropertiesService.getScriptProperties().getProperty("GITHUB_TOKEN");
  if (!chave) {
    throw new Error("Falta a propriedade GITHUB_TOKEN (Configurações do projeto > Propriedades do script).");
  }
  const resposta = UrlFetchApp.fetch(
    `https://api.github.com/repos/${REPOSITORIO}/actions/workflows/${ROTINA}/dispatches`,
    {
      method: "post",
      contentType: "application/json",
      headers: {
        Authorization: "Bearer " + chave,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      payload: JSON.stringify({ ref: "main", inputs: { modo: "agenda" } }),
      muteHttpExceptions: true,
    }
  );
  const codigo = resposta.getResponseCode();
  if (codigo !== 204) {
    // 401: chave inválida ou expirada; 403/404: chave sem a permissão "Actions: Read and write" neste repositório
    throw new Error(`O GitHub recusou o disparo (código ${codigo}): ${resposta.getContentText().slice(0, 300)}`);
  }
}

/** Cria (ou recria) o gatilho que roda acionar() a cada 15 minutos. */
function instalar() {
  ScriptApp.getProjectTriggers()
    .filter((g) => g.getHandlerFunction() === "acionar")
    .forEach((g) => ScriptApp.deleteTrigger(g));
  ScriptApp.newTrigger("acionar").timeBased().everyMinutes(15).create();
}
