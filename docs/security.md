# Segurança e privacidade

- Senhas, tokens OAuth e a chave OpenAI não são argumentos das ferramentas do modelo.
- O arquivo `secrets.enc` é criptografado com Fernet. Sua chave é obtida no keyring do sistema; em Windows, no Gerenciador de Credenciais.
- Ambientes sem keyring devem fornecer explicitamente `DTA_MASTER_KEY`; não há fallback em texto puro.
- Backends e opções secretas são fornecidos no ambiente dos subprocessos e não em argumentos de linha de comando. O rclone usa configuração em memória (`--config` com valor vazio); uma renovação de token não grava um arquivo em texto puro.
- A chave OpenAI é passada diretamente ao cliente de API no backend, fora das mensagens e ferramentas. O endpoint OpenAI é fixo; chaves legadas Gemini não são reutilizadas. O ambiente do rclone exclui a chave OpenAI e a chave mestra do cofre.
- OAuth usa state aleatório, PKCE, prazo de expiração e troca de código no backend. Uma autorização cancelada não pode ser reaproveitada.
- Respostas de validação não ecoam o corpo enviado. Logs e respostas públicas são filtrados. Exceções brutas do provedor/modelo não são devolvidas à conversa.
- Texto do chat é enviado à OpenAI após filtragem de padrões conhecidos de segredos. Nomes de arquivos, caminhos, preferências e resultados resumidos podem compor o contexto do modelo. Padrões não substituem o uso dos campos protegidos.
- Caminhos de reparo rejeitam absolutos, travessia, unidades Windows e quebras de linha. A associação de destino e origem impede misturar fontes distintas no mesmo nome registrado.
- Nenhuma ferramenta genérica de shell é exposta. O catálogo contém somente ações de domínio.
- A API é local, sem CORS amplo. Escritas exigem cabeçalho específico e origem local reconhecida. Logs de acesso estão desativados para não registrar códigos OAuth em URLs.
- Atualizações do rclone baixam somente do domínio oficial e verificam SHA-256 antes de substituir a instalação gerenciada.

O aplicativo foi desenhado para um usuário no próprio computador. Compartilhar a API na LAN ou internet exige autenticação e revisão da arquitetura. Não copie os bancos, logs ou a pasta de dados para o repositório público.
