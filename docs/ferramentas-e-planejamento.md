# Ferramentas e planejamento do agente

O Google ADK oferece ao modelo 27 ferramentas de domínio. O rclone executa operações de arquivos; a API Google Drive resolve metadados e filhos por ID. As contas configuradas são reutilizadas e as credenciais ficam no backend. Os nomes das ferramentas abaixo são os nomes reais oferecidos ao modelo.

## Catálogo

| Ferramenta | Uso e operação correspondente |
|---|---|
| `environment` | Versão do rclone e presença das conexões, sem credenciais. |
| `request_setup` | Abre configuração protegida. Quando a conta já está configurada, orienta usá-la; reconexão só após falha registrada. |
| `test_connection` | Identifica a conta Google ou consulta capacidade MEGA (`about --json`). |
| `list_destinations` | Lista destinos cadastrados e preferências. |
| `save_destination` | Cadastra caminho local absoluto ou caminho relativo MEGA. Não cria arquivos nem transfere. |
| `set_preferences` | Salva destino, ação padrão, exportação Google, pastas vazias e reparo. |
| `source_metadata` | Consulta ID, nome, tipo, pais, tamanho e permissão via API Drive. |
| `list_source_children` | Lista filhos imediatos via API Drive, com IDs reais e referências utilizáveis. Retorna cursor de paginação. |
| `select_source_folders` | Resolve todas as páginas e seleciona pastas por intervalo numérico ou nomes exatos. Rejeita números ausentes ou ambíguos. |
| `search_source_entries` | Busca por nome; recursão opcional limitada a três níveis, 20 páginas e 100 resultados. Informa quando a busca foi cortada. |
| `list_mega_folders` | Lista pastas da conta MEGA existente (`lsjson --dirs-only`). |
| `resolve_mega_destination` | Confirma uma pasta existente (`lsjson --stat`) e cadastra seu caminho sem criar outra pasta. |
| `list_destination_entries` | Lista arquivos e subpastas dentro do destino cadastrado (`lsjson --max-depth 1`), com paginação dos resultados. |
| `destination_usage` | Conta arquivos e bytes de destino/subpasta (`size --json`). Pode levar tempo em árvores grandes. |
| `destination_capacity` | Consulta espaço disponível e suficiência (`about --json` no MEGA; disco local via sistema). |
| `create_destination_folder` | Cria uma subpasta validada (`mkdir`) e confirma sua existência. Bloqueada quando o pedido exige pasta já existente. |
| `prepared_queue` | Consulta a fila preparada e IDs estáveis. |
| `change_queue` | Adiciona, renomeia, reordena, remove, desfaz ou limpa itens da fila. Não copia. |
| `plan_transfer` | Salva plano com origens, nomes e destinos individuais, opções e etapas. Não copia nem inicia consulta recursiva. |
| `current_plan` | Recupera plano, intenção e seleção persistidos na conversa. |
| `preflight_transfer_plan` | Inicia consulta das origens e espaço para o plano (`lsjson`/`size`/`about`). Retorna tarefa de consulta; não copia. |
| `execute_transfer_plan` | Inicia execução idempotente do plano salvo. Respeita revisão e escopo da conversa. |
| `run_transfer` | Compatibilidade para consultar, copiar ou verificar. Cópia/verificação passam pelo planejador; seleção e revisão continuam obrigatórias. |
| `task_status` | Consulta tarefa ativa ou por ID, etapas e resultados reais. |
| `cancel_task` | Cancela tarefa e encerra sua árvore de subprocessos rclone. |
| `retry_task` | Cria nova tentativa com arquivos existentes e parâmetros anteriores, respeitando o escopo atual. |
| `task_log` | Retorna até 50 linhas de diagnóstico filtradas. |

Na cópia, o executor usa `copy`/`copyto`, exporta documentos Google suportados e aplica as opções persistidas. Na auditoria, usa `check` e repara somente arquivos ausentes ou diferentes, com limite de rodadas e nova verificação. MEGA é auditado por tamanho; isso não comprova igualdade byte a byte. Espaço temporário de arquivos individuais também entra na preparação.

O modelo recebe resultados estruturados. Não há ferramenta para executar comandos arbitrários. `sync`, `delete`, `purge`, `move`, mudanças de permissão e publicação de links não estão expostos: não são necessários ao fluxo de cópia Drive → PC/MEGA. Novos provedores exigem integração de autenticação e testes próprios.

## Exemplo: somente as pastas 34 a 38

Pedido sugerido:

> Faça um plano primeiro, sem iniciar a cópia. Use este link do Drive: LINK. Selecione somente as pastas 34 a 38 e copie cada uma diretamente para a pasta existente /ANEST REVIEW 2026 no MEGA, mantendo seus nomes, sem criar a pasta-pai dentro do destino.

Fluxo esperado:

1. Registrar o link e reconhecer intervalo, destino e revisão solicitada.
2. Listar filhos da pasta-pai e selecionar os cinco IDs reais, lendo todas as páginas. Um arquivo chamado “34” ou uma pasta “340” não substitui a pasta “34”.
3. Confirmar o caminho MEGA usando a conta já conectada. Um link `mega.nz/fm/...` é navegação; não significa que a conta precisa ser reconectada. A resolução automática desse tipo de link cobre pastas da raiz; quando não for possível, usar listagem e caminho.
4. Criar plano com cinco destinos como `mega:ANEST REVIEW 2026/34 – Anestesia para Otorrinolaringologia`. A pasta “Anest-Review Extensive 2026” não vira uma camada adicional.
5. Mostrar o plano no chat e no cartão persistente. “Consultar tamanho e espaço” executa somente a preparação. “Aprovar plano e iniciar” autoriza a cópia; também é possível responder “pode executar” no chat.
6. Consultar tamanho/espaço para o conjunto, copiar cada origem e auditar. Identificador de tarefa significa início; conclusão depende do resultado do executor.

## Garantias e limites

- Seleção, intenção e plano ficam no SQLite por conversa e sobrevivem ao reinício. Conversas anteriores recuperam a intenção a partir das mensagens humanas.
- O executor bloqueia substituir a seleção pela pasta-pai, trocar o destino ou as opções de um plano, usar plano de outra conversa ou executar plano sujeito a revisão sem aprovação humana.
- Mudanças reconhecidas de intervalo, nomes, pasta-pai ou destino invalidam a revisão anterior. É necessário preparar novo plano.
- Enviar um link isolado depois de um pedido de seleção/revisão não aciona a cópia automática da pasta inteira.
- O plano guarda uma cópia dos parâmetros; não congela o conteúdo remoto. Alterações posteriores nos arquivos podem mudar contagens e tamanhos na execução.
- A interpretação do texto livre usa o modelo com reconhecimento adicional de expressões comuns em português. Confira os caminhos apresentados, especialmente em pedidos com múltiplos destinos ou correções complexas.
- Listagem de filhos e consulta recursiva de tamanho são operações diferentes. O agente deve listar para descobrir IDs, sem confundir contagem de arquivos com inventário de subpastas.
- Consultas rclone de inventário e manutenção compartilham o bloqueio de execução; uma tarefa longa ativa deve ser acompanhada ou cancelada antes dessas operações.
- Atalhos do Drive precisam do link original. Busca limitada sinaliza resultados incompletos. Seleção que exceda 20 páginas falha sem usar resultado parcial.

Referências: [Drive files.list](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list), [rclone lsjson](https://rclone.org/commands/rclone_lsjson/), [size](https://rclone.org/commands/rclone_size/), [about](https://rclone.org/commands/rclone_about/), [copy](https://rclone.org/commands/rclone_copy/), [check](https://rclone.org/commands/rclone_check/).
