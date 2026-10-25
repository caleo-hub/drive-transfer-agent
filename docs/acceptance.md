# Aceite e demonstração

## Validações sem credenciais

Execute a suíte Python, testes da interface e build. A integração real local deve verificar cópia, hash, reparo e cancelamento com arquivos temporários. O CI repete os testes em Windows e Ubuntu.

## Validação manual com contas

Registre data, plataforma, versões e resultado, sem copiar chaves, senhas ou links privados.

| Cenário | Resultado esperado | Validação real |
|---|---|---|
| Instalar rclone pelo cartão | Executável oficial com checksum conferido | A registrar |
| Autorizar Google e recarregar página | Conta conectada, sem token no histórico | A registrar |
| Recusar/cancelar autorização | Estado correspondente, conexão anterior preservada | A registrar |
| Conectar MEGA | Conexão testada antes de salvar | A registrar |
| Copiar pasta Drive → PC | Estrutura preservada e auditoria final explícita | A registrar |
| Copiar arquivo compartilhado individualmente | Funciona sem listar pasta pai | A registrar |
| Copiar pasta e arquivo → MEGA | Cópia concluída e auditoria por tamanho identificada | A registrar |
| Documento Google | Exportação para formato configurado | A registrar |
| Espaço insuficiente | Nenhuma cópia iniciada; oferta de outro destino | A registrar |
| Acesso negado/cota | Explicação sem falso sucesso | A registrar |
| Cancelar e reabrir chat | Estado real e arquivos concluídos preservados | A registrar |
| Reiniciar aplicativo | Job interrompido; nenhuma duplicação automática | A registrar |
| Pedidos no OpenAI | Ferramentas escolhidas e resultados reais relatados | A registrar |

## Planejamento validado em 25/10/2026

No Windows, com rclone v1.71.0 e as contas já configuradas, foram consultados os filhos reais de uma pasta Google Drive e confirmada uma pasta MEGA existente. Um pedido pelo chat usando OpenAI e Google ADK selecionou somente as pastas 34 a 38 e criou plano persistente com cinco IDs reais e cinco destinos diretos, mantendo os nomes e sem uma camada adicional da pasta-pai. A revisão permaneceu pendente; nenhuma tarefa de cópia foi criada. O ciclo completo levou aproximadamente 71 segundos nesta instalação.

Os testes automatizados cobrem seleção paginada, números ausentes/duplicados, preservação de chaves de recurso fora das respostas públicas, aprovação, alteração de escopo/destino, execução idempotente, consulta sem cópia, inventário em lote e retomada de conversa anterior. A interface móvel foi validada para os cinco caminhos, consulta separada da aprovação e bloqueio de plano desatualizado. Esta validação comprova descoberta e planejamento com contas reais; a cópia dessas cinco pastas não foi executada.

## Roteiro do vídeo de portfólio

1. Apresente o problema: transferir pastas sem terminal e sem perder o acompanhamento.
2. Mostre os cartões de conexão usando uma conta de demonstração.
3. Envie um link de uma pasta de arquivos fictícios para o destino PC.
4. Mostre preparação, progresso e auditoria; abra o destino.
5. Demonstre fila e cópia para MEGA.
6. Mostre um erro controlado e o resultado correto no chat.
7. Feche com o desenho da arquitetura e a distinção entre agente e executor.

O vídeo final com contas reais é gravado depois desse aceite. Não apresente screenshots de testes ou dados simulados como prova de integração real.
