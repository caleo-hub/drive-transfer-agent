# Drive Transfer Agent

**Um assistente de arquivos feito para uma pessoa real.** Cole um link do Google Drive, peça uma cópia para o PC ou MEGA e acompanhe consulta, transferência e auditoria no chat.

Built with Google ADK, OpenAI, FastAPI, React and rclone. Developed on Ubuntu; designed to run locally on Windows. The language model plans operations through typed tools; a persistent executor performs and verifies the work.

![Interface do Drive Transfer Agent](docs/images/overview.png)

[Vídeo demonstrativo da interface](docs/demo.mp4) — dados e progresso simulados, identificados no próprio vídeo. A demonstração não representa validação com contas reais.

## O que está incluído

- Chat em português, ferramentas ADK e preferências persistentes.
- 27 ferramentas para descobrir pastas/IDs, buscar, medir, planejar, copiar e verificar: [catálogo completo e exemplos](docs/ferramentas-e-planejamento.md).
- Seleção por nomes ou intervalos como “pastas 34 a 38”, com plano persistente, caminhos exatos e aprovação quando solicitada.
- Menu por conversa para arquivar, restaurar e excluir, com confirmação antes da exclusão.
- Arquivos individuais e pastas do Google Drive → PC ou MEGA; nenhuma exclusão na origem.
- Instalação oficial do rclone com SHA-256, conexão Google OAuth e formulário protegido MEGA.
- Destinos favoritos, consulta de espaço e preparação antes da cópia.
- Fila de até 100 itens com nomes, reordenação, remoção e desfazer.
- Consulta, cópia, verificação, reparo limitado, cancelamento e eventos de progresso.
- SQLite, idempotência e identificação de tarefas interrompidas após reinício.
- Credenciais criptografadas com chave no armazenamento seguro do sistema; não passam pelo modelo.

## Desenvolvimento no Ubuntu

Requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22+ e npm.

```bash
git clone https://github.com/caleo-hub/drive-transfer-agent.git
cd drive-transfer-agent
uv sync --locked
cd web
npm ci
npm run build
cd ..
uv run drive-transfer-agent --no-browser
```

Abra `http://127.0.0.1:8765`. Para desenvolvimento com hot reload, execute `npm run dev` em `web/`; o Vite encaminha `/api` para o backend local.

O Ubuntu é o workspace de desenvolvimento. Quando o aplicativo roda no Windows, os caminhos e as transferências pertencem ao Windows. Não existe ponte de controle remoto entre as duas máquinas.

### Ambiente sem armazenamento seguro

No desktop Windows, o keyring usa o Gerenciador de Credenciais. No Ubuntu com interface gráfica, use Secret Service. Em SSH/CI sem keyring, forneça `DTA_MASTER_KEY` pelo seu gerenciador de segredos; uma chave pode ser gerada com:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Não versione nem perca essa chave. O aplicativo não cria um fallback em texto puro.

## Uso no Windows

Instale Python 3.12+, uv e Node 22 para a instalação a partir do código. Clone o repositório e execute `instalar.ps1` uma vez. Depois use `iniciar.bat` para abrir o aplicativo. A instalação do rclone e a conexão das contas são feitas nos cartões de Configuração.

1. Instale o rclone pelo cartão **Aplicativo**.
2. Informe sua chave OpenAI no cartão **OpenAI**.
3. Conecte Google Drive e, se desejado, MEGA.
4. Cadastre um destino e selecione-o nas preferências.
5. Envie um link ou um pedido como “adicione estas pastas à fila”.

O instalador de desenvolvimento ainda exige os runtimes acima. Esta versão não é um executável autossuficiente.

## Provisionamento Google OAuth

O dono da instalação cria um projeto Google Cloud, habilita **Google Drive API** e configura a tela de consentimento. Crie um cliente OAuth para **aplicativo de computador**; enquanto o projeto estiver em testes, cadastre o e-mail autorizado como usuário de teste.

Configure `GOOGLE_CLIENT_ID` e, quando fornecido pelo Google, `GOOGLE_CLIENT_SECRET` no ambiente ou nos campos protegidos do cartão Google Drive. Para clientes web, autorize exatamente `http://127.0.0.1:8765/api/setup/oauth/callback`. O fluxo usa PKCE e acesso `drive.readonly`; o usuário concede acesso na página oficial Google.

Tokens de aplicativos em modo de teste podem expirar conforme a política Google. Reconecte pelo mesmo cartão. Uma falha de login não concede acesso a arquivos sem permissão.

## Configuração

Consulte `.env.example`. Variáveis opcionais:

| Variável | Função |
|---|---|
| `DTA_DATA_DIR` | Diretório privado do aplicativo; padrão do sistema operacional |
| `DTA_PORT` | Porta local, padrão 8765 |
| `AGENT_MODEL` | Modelo OpenAI via LiteLLM, padrão `openai/gpt-5.4-mini` |
| `OPENAI_API_KEY` | Chave OpenAI opcional, alternativa ao cartão protegido |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Cliente OAuth provisionado pelo desenvolvedor |
| `RCLONE_BIN` | Executável explicitamente escolhido; precede instalação gerenciada e PATH |
| `DTA_MASTER_KEY` | Alternativa explícita ao keyring para desenvolvimento sem desktop |

O agente usa [OpenAI pelo conector LiteLLM do ADK](https://adk.dev/agents/models/litellm/). Cadastre a chave em **Configuração → OpenAI** ou use `OPENAI_API_KEY` no ambiente/`.env` (o ambiente tem precedência). Ela fica no backend; o navegador não chama a API OpenAI diretamente. `AGENT_MODEL` aceita o nome puro ou o prefixo `openai/`. A configuração Google OAuth continua sendo necessária apenas para acessar o Drive.

Ao atualizar de uma instalação Gemini, cadastre uma chave OpenAI nova e ajuste qualquer `AGENT_MODEL` antigo. Chaves legadas não são reaproveitadas nem enviadas à OpenAI.

Dados operacionais ficam em `jobs.sqlite3`, sessões ADK em `sessions.sqlite3`, credenciais em `secrets.enc`. Backends e credenciais são injetados no ambiente privado dos subprocessos. O rclone usa configuração em memória (`--config` com valor vazio), impedindo que uma renovação de token grave um arquivo de credenciais em texto puro. Não copiamos a configuração global do rclone.

## Comportamento e limites

- Uma operação longa por executor. Fechar a aba não para a transferência; encerrar o aplicativo interrompe o trabalho.
- Conversas arquivadas ficam na lista de arquivadas e podem ser restauradas para continuar. Excluir remove mensagens, fila preparada e sessão do agente, preservando arquivos e histórico de tarefas. Uma conversa com tarefa ativa só pode ser excluída depois de concluir ou cancelar a tarefa.
- Reinício reconcilia tarefas como interrompidas. Nova tentativa é uma nova operação; não prometemos retomada parcial de cada arquivo.
- Arquivos diferentes podem ser substituídos. Extras no destino e originais na origem são preservados.
- Auditoria de MEGA é por tamanho. A interface mostra o alcance; isso não comprova igualdade byte a byte.
- Arquivos individuais usam staging temporário para funcionar sem acesso à pasta pai; a preparação considera esse espaço.
- Google Docs/Sheets/Slides são exportados para DOCX/XLSX/PPTX. Tamanhos desconhecidos são sinalizados.
- Zero arquivos visíveis gera atenção; uma origem inteiramente vazia não é replicada automaticamente.
- Atalhos do Drive devem ser substituídos pelo link do original. Documentos Google sem formato suportado geram mensagem específica.
- O MEGA pode exigir novo código 2FA e limitar logins; reconecte quando solicitado. Evite testes repetidos de conexão durante uma tarefa.
- A implementação atual do MEGA usa subprocessos separados por etapa. Contas que exigem um novo código 2FA em cada login podem precisar de nova autorização entre etapas; sessões MEGA persistentes ainda não são implementadas.
- Vídeos seletivos, transcrição, agendamento, sincronização destrutiva e múltiplos usuários não integram esta versão.

## Testes

```bash
uv run pytest -q
uv run ruff check .
cd web
npm test
npm run test:e2e
npm run build
```

A integração local usa rclone com diretórios temporários e não exige contas. Testes com Google/MEGA e a chave real do modelo são manuais e separados: veja [aceite](docs/acceptance.md). O CI executa testes em Ubuntu e Windows e compila a interface.

Veja [arquitetura](docs/architecture.md) e [segurança e privacidade](docs/security.md). O conteúdo demonstrativo usa dados fictícios. A condição de cada validação real deve ser registrada no aceite; testes sem credenciais não certificam login nem transferências em provedores.

## Licença

MIT. Consulte [LICENSE](LICENSE).
