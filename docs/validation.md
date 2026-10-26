# Registro de validação da implementação

Validação automatizada sem credenciais de nuvem. Nenhum token ou arquivo privado foi utilizado.

## Atualização de publicação — 2026-10-26

- Windows / Python 3.12.10: 114 testes de backend aprovados; Ruff aprovado. Há um aviso da dependência Pydantic sobre `ReadOnly` em um TypedDict do cliente de modelo.
- Frontend: 2 testes unitários e 6 cenários Playwright aprovados; TypeScript, Prettier e build Vite aprovados.
- Pacotes Python sdist e wheel construídos após compilar a interface.
- README principal em inglês com 19 links locais verificados; capturas desktop e móvel atualizadas pelos testes.
- Demo promocional em inglês: 45 segundos exatos, 1080 × 1350, 30 fps, H.264 e sem áudio. Os 1.350 quadros foram decodificados sem erros; vídeo original preservado por SHA-256. Veja [validação da demo](linkedin-demo/validation/REVIEW.md).
- As conexões Google/MEGA e chamadas do modelo continuam simuladas nos testes. Esta atualização não representa aceite com contas reais.

## Registro anterior

- Python: suíte ampliada de 69 para 81 testes, aprovada no Ubuntu 24.04 / Python 3.12; o CI também executa a suíte no Windows. A versão inicial teve 69 testes aprovados localmente no Windows 11.
- Integração com rclone 1.75.2 real: instalação com checksum, cópia local, preservação de extras, auditoria, reparo e arquivo individual com staging.
- Cancelamento de subprocessos silenciosos e antes do início, prevenção de duplicidade e reconciliação após reinício.
- Preparação com espaço suficiente, insuficiente, desconhecido e staging em outro volume.
- ADK 2.13: Runner real com modelo de teste, chamada de ferramenta, callback e persistência de sessão SQLite.
- OpenAI: conector LiteLLM real com transporte simulado, chamada de ferramenta pelo ADK, precedência ambiente/cofre, isolamento da chave e rejeição de credenciais coladas no chat. Nenhuma chamada paga foi feita.
- Frontend: dois testes de apresentação e três cenários Playwright aprovados, incluindo configuração sem modelo, destino/preferências, conversa persistida e layout móvel.
- TypeScript e build de produção aprovados; pacote Python construído com interface compilada.
- Auditoria npm: zero vulnerabilidades na resolução utilizada.
- Vídeo de interface gravado com respostas e progresso simulados e identificação visível; exportado para H.264 por NVENC.

## Ainda exige contas reais

O fluxo real Google OAuth, o login MEGA, uma resposta da OpenAI com chave real e transferências Drive → PC/MEGA não foram executados nesta validação. São o próximo aceite descrito em [acceptance.md](acceptance.md).

Testes locais comprovam o executor e seus contratos, não as permissões, cotas, política OAuth ou compatibilidade 2FA de uma conta específica. Consulte também as limitações do backend MEGA no README.
