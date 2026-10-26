import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ArrowUp,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronDown,
  Cloud,
  Download,
  ExternalLink,
  FileText,
  Folder,
  HardDrive,
  LoaderCircle,
  MessageSquare,
  Plus,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  X,
  ArrowRightLeft,
  PanelLeftClose,
  Menu,
  AlertCircle,
  Archive,
  ArchiveRestore,
  MoreHorizontal,
  Trash2,
} from 'lucide-react';
import { api, bytes, finalStates, stageLabel, statusLabel } from './api';
import './style.css';

type Message = {
  id: string;
  role: string;
  text: string;
  actions?: { type: string; provider: string }[];
  job_ids?: string[];
  job_id?: string;
  plan?: TransferPlan;
  task_id?: string;
  status?: string;
};
type Conversation = { id: string; title: string; archived?: boolean };
type Destination = { id: string; name: string; kind: string; path: string };
type TransferPlan = {
  id: string;
  status: string;
  stale?: boolean;
  requires_approval: boolean;
  approved: boolean;
  destination: Destination;
  items: { name: string; source_id: string; target: string }[];
  steps: string[];
  note: string;
};
type Job = {
  id: string;
  status: string;
  stage: string;
  message: string;
  revision: number;
  current: number;
  items: any[];
  spec: any;
  stats: any;
  cancel_requested: boolean;
};
const capacityLabels: Record<string, string> = {
  sufficient: 'suficiente',
  insufficient: 'insuficiente',
  estimated: 'estimado',
  unknown: 'não informado',
};
const flowLabels: Record<string, string> = {
  pending: 'aguardando',
  exchanging: 'validando',
  success: 'conectada',
  refused: 'recusada',
  expired: 'expirada',
  cancelled: 'cancelada',
  failed: 'falhou',
};

function App() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversation, setConversation] = useState(localStorage.getItem('dta-conversation') || '');
  const [messages, setMessages] = useState<Message[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [destinations, setDestinations] = useState<Destination[]>([]);
  const [queue, setQueue] = useState<any[]>([]);

  const [health, setHealth] = useState<any>(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [setup, setSetup] = useState('');
  const [sidebar, setSidebar] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [conversationMenu, setConversationMenu] = useState('');
  const [deleting, setDeleting] = useState<Conversation | null>(null);
  const [managing, setManaging] = useState(false);
  const deleteDialog = useRef<HTMLDialogElement>(null);
  const menuRoot = useRef<HTMLElement>(null);
  const selectedId = useRef(conversation);
  selectedId.current = conversation;
  const end = useRef<HTMLDivElement>(null);
  const pending = useRef<{ text: string; id: string } | null>(null);

  async function refresh() {
    const [cs, archived, js, ds, h] = await Promise.all([
      api('/conversations'),
      api('/conversations?archived=true'),
      api('/jobs'),
      api('/destinations'),
      api('/health'),
    ]);
    setConversations([...cs, ...archived]);
    setJobs(js);
    setDestinations(ds);
    setHealth(h);
  }
  async function load(id: string) {
    const [ms, q] = await Promise.all([
      api(`/conversations/${id}/messages`),
      api(`/conversations/${id}/queue`),
    ]);
    if (selectedId.current !== id) return;
    setMessages(ms);
    setQueue(q.items);
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        newChat();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);
  useEffect(() => {
    if (conversation) {
      localStorage.setItem('dta-conversation', conversation);
      load(conversation).catch((e) => setError(e.message));
    } else localStorage.removeItem('dta-conversation');
  }, [conversation]);
  useEffect(() => {
    if (!conversationMenu) return;
    menuRoot.current?.querySelector<HTMLButtonElement>('[role="menu"] button')?.focus();
    function outside(event: PointerEvent) {
      if (!menuRoot.current?.contains(event.target as Node)) setConversationMenu('');
    }
    function escape(event: KeyboardEvent) {
      if (event.key === 'Escape') setConversationMenu('');
    }
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('keydown', escape);
    };
  }, [conversationMenu]);
  useEffect(() => {
    if (deleting) deleteDialog.current?.showModal();
  }, [deleting]);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, busy]);

  const activeJob = jobs.find((j) => !finalStates.includes(j.status));
  useEffect(() => {
    if (!activeJob) return;
    const events = new EventSource(`/api/jobs/${activeJob.id}/events`);
    events.addEventListener('snapshot', (event) => {
      const job = JSON.parse((event as MessageEvent).data);
      setJobs((old) => old.map((j) => (j.id === job.id ? job : j)));
    });
    events.addEventListener('done', () => {
      events.close();
      refresh().catch(() => {});
      if (conversation) load(conversation).catch(() => {});
    });
    return () => events.close();
  }, [activeJob?.id, conversation]);

  async function newChat() {
    try {
      const c = await api('/conversations', 'POST');
      setConversations((old) => [...old, c]);
      setConversation(c.id);
      selectedId.current = c.id;
      setMessages([]);
      setQueue([]);

      setText('');
      setShowArchived(false);
      setConversationMenu('');
      setSidebar(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function clearSelected(id: string) {
    if (conversation !== id) return;
    setConversation('');
    selectedId.current = '';
    setMessages([]);
    setQueue([]);

    setText('');
    pending.current = null;
  }
  async function archiveChat(chat: Conversation, archived: boolean) {
    setManaging(true);
    setConversationMenu('');
    setError('');
    try {
      const updated = await api<Conversation>(`/conversations/${chat.id}`, 'PATCH', { archived });
      setConversations((old) => old.map((c) => (c.id === chat.id ? updated : c)));
      if (archived) clearSelected(chat.id);
      else {
        setShowArchived(false);
        setConversation(chat.id);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setManaging(false);
    }
  }
  async function deleteChat() {
    if (!deleting || managing) return;
    const chat = deleting;
    setManaging(true);
    setError('');
    try {
      await api(`/conversations/${chat.id}`, 'DELETE');
      setConversations((old) => old.filter((c) => c.id !== chat.id));
      clearSelected(chat.id);
      deleteDialog.current?.close();
      setDeleting(null);
    } catch (e) {
      setError((e as Error).message);
      deleteDialog.current?.close();
      setDeleting(null);
    } finally {
      setManaging(false);
    }
  }
  const selectedChat = conversations.find((c) => c.id === conversation);
  const archivedChat = !!selectedChat?.archived;
  const listedChats = conversations.filter((c) => !!c.archived === showArchived);
  async function executePlan(plan: TransferPlan, action: 'execute' | 'preflight' = 'execute') {
    if (!plan || busy || archivedChat) return;
    setBusy(true);
    setError('');
    try {
      await api(`/conversations/${conversation}/plans/${plan.id}/${action}`, 'POST');
      await Promise.all([load(conversation), refresh()]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function renderPlan(plan: TransferPlan) {
    return (
      <section className="transfer-plan" aria-label="Plano de transferência">
        <div className="plan-heading">
          <FileText size={18} />
          <strong>Plano de transferência · {plan.items.length} origens</strong>
        </div>
        <p>
          Destino: <strong>{plan.destination.name}</strong>
        </p>
        <ol className="plan-origins">
          {plan.items.map((item) => (
            <li key={item.source_id}>
              <strong>{item.name}</strong>
              <span>{item.target}</span>
            </li>
          ))}
        </ol>
        <p className="small muted">{plan.note}</p>
        <details>
          <summary>Etapas planejadas</summary>
          <ol>
            {plan.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </details>
        {plan.stale ? (
          <p role="status">O pedido mudou. Prepare um novo plano antes de iniciar.</p>
        ) : plan.status === 'ready' ? (
          <div className="plan-actions">
            <button disabled={busy || archivedChat} onClick={() => executePlan(plan, 'preflight')}>
              Consultar tamanho e espaço
            </button>
            <button
              className="primary"
              disabled={busy || archivedChat}
              onClick={() => executePlan(plan)}
            >
              {plan.requires_approval && !plan.approved
                ? 'Aprovar plano e iniciar'
                : 'Iniciar plano'}
            </button>
          </div>
        ) : (
          <p role="status">Plano enviado ao executor. Acompanhe o resultado na tarefa.</p>
        )}
      </section>
    );
  }
  async function send(value = text) {
    if (!value.trim() || busy || archivedChat || managing) return;
    setBusy(true);
    setError('');
    const operation =
      pending.current?.text === value ? pending.current : { text: value, id: crypto.randomUUID() };
    pending.current = operation;
    try {
      let id = conversation;
      if (!id) {
        const c = await api('/conversations', 'POST');
        id = c.id;
        setConversation(id);
      }
      setText('');
      await api(`/conversations/${id}/messages`, 'POST', { text: value, request_id: operation.id });
      pending.current = null;
      await Promise.all([load(id), refresh()]);
    } catch (e) {
      setError(
        (e as Error).message + ' Se repetir o mesmo pedido, usaremos o mesmo identificador.',
      );
      setText(value);
    } finally {
      setBusy(false);
    }
  }
  const visibleJobs = jobs.filter((j) => j.spec.conversation_id === conversation);
  return (
    <div className="app-shell">
      <aside inert={!!setup} aria-hidden={!!setup} className={`sidebar ${sidebar ? 'shown' : ''}`}>
        <div className="brand">
          <div className="brand-icon">
            <ArrowRightLeft size={21} />
          </div>
          <span>
            drive<span className="brand-light">transfer</span>
          </span>
          <button
            className="icon mobile-only"
            aria-label="Fechar menu"
            onClick={() => setSidebar(false)}
          >
            <PanelLeftClose size={18} />
          </button>
        </div>
        <button className="new-chat" onClick={newChat}>
          <Plus size={17} />
          Nova conversa<span>⌘ K</span>
        </button>
        <div className="conversation-heading">
          <span className="side-label">{showArchived ? 'ARQUIVADAS' : 'SUAS CONVERSAS'}</span>
          <button
            className="icon archive-toggle"
            aria-label={showArchived ? 'Ver conversas ativas' : 'Ver conversas arquivadas'}
            title={showArchived ? 'Conversas ativas' : 'Conversas arquivadas'}
            aria-pressed={showArchived}
            onClick={() => {
              setShowArchived(!showArchived);
              setConversationMenu('');
            }}
          >
            {showArchived ? <MessageSquare size={16} /> : <Archive size={16} />}
          </button>
        </div>
        <nav
          className="conversation-list"
          aria-label={showArchived ? 'Conversas arquivadas' : 'Conversas ativas'}
          ref={menuRoot}
        >
          {listedChats
            .slice()
            .reverse()
            .map((c) => (
              <div
                key={c.id}
                className={`conversation-row${conversation === c.id ? ' selected' : ''}`}
              >
                <button
                  className="conversation-open"
                  aria-current={conversation === c.id ? 'page' : undefined}
                  onClick={() => {
                    setConversation(c.id);
                    selectedId.current = c.id;
                    setConversationMenu('');
                    setSidebar(false);
                  }}
                >
                  <MessageSquare size={15} />
                  <span>{c.title}</span>
                </button>
                <button
                  className="conversation-more"
                  aria-label={`Opções de ${c.title}`}
                  aria-haspopup="menu"
                  aria-expanded={conversationMenu === c.id}
                  disabled={busy || managing}
                  onClick={() => setConversationMenu(conversationMenu === c.id ? '' : c.id)}
                >
                  <MoreHorizontal size={18} />
                </button>
                {conversationMenu === c.id && (
                  <div
                    className="conversation-menu"
                    role="menu"
                    aria-label={`Ações de ${c.title}`}
                    onKeyDown={(event) => {
                      const buttons = [...event.currentTarget.querySelectorAll('button')];
                      const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
                      if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
                        event.preventDefault();
                        const next =
                          event.key === 'Home'
                            ? 0
                            : event.key === 'End'
                              ? buttons.length - 1
                              : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) %
                                buttons.length;
                        buttons[next]?.focus();
                      } else if (event.key === 'Escape') {
                        event.stopPropagation();
                        setConversationMenu('');
                        event.currentTarget
                          .closest('.conversation-row')
                          ?.querySelector<HTMLButtonElement>('.conversation-more')
                          ?.focus();
                      }
                    }}
                  >
                    <button role="menuitem" onClick={() => archiveChat(c, !c.archived)}>
                      {c.archived ? <ArchiveRestore size={15} /> : <Archive size={15} />}
                      {c.archived ? 'Restaurar conversa' : 'Arquivar conversa'}
                    </button>
                    <button
                      role="menuitem"
                      className="delete-action"
                      onClick={() => {
                        setConversationMenu('');
                        setDeleting(c);
                      }}
                    >
                      <Trash2 size={15} /> Excluir conversa
                    </button>
                  </div>
                )}
              </div>
            ))}
          {!listedChats.length && (
            <p className="muted small">
              {showArchived ? 'Nenhuma conversa arquivada.' : 'Seus pedidos ficam guardados aqui.'}
            </p>
          )}
        </nav>
        <div className="sidebar-bottom">
          <div className="side-label">SUAS CONEXÕES</div>
          <button className="connection" onClick={() => setSetup('google')}>
            <Cloud size={17} />
            <span>Google Drive</span>
            <i className={health?.connections.google ? 'online' : ''} />
          </button>
          <button className="connection" onClick={() => setSetup('mega')}>
            <div className="mega-icon">M</div>
            <span>MEGA</span>
            <i className={health?.connections.mega ? 'online' : ''} />
          </button>
          <div className="local-badge">
            <ShieldCheck size={15} />
            <span>Executado neste computador</span>
          </div>
          <button className="settings-button" onClick={() => setSetup('overview')}>
            <Settings2 size={17} />
            Configuração
          </button>
          <div className="profile">
            <div className="avatar">V</div>
            <div>
              <strong>Seu espaço pessoal</strong>
              <small>Arquivos sob seu controle</small>
            </div>
          </div>
        </div>
      </aside>
      <main inert={!!setup} aria-hidden={!!setup}>
        <header>
          <div>
            <button
              className="icon mobile-only"
              aria-label="Abrir menu"
              onClick={() => setSidebar(true)}
            >
              <Menu size={20} />
            </button>
            <span>Assistente de arquivos</span>
            <ChevronDown size={14} />
          </div>
          <span className="model-badge">
            <span />
            Modo pessoal
          </span>
        </header>
        <div className="chat-scroll">
          {messages.length === 0 ? (
            <section className="welcome">
              <div className="hero-mark">
                <ArrowRightLeft size={31} />
                <span>
                  <Sparkles size={13} />
                </span>
              </div>
              <div className="eyebrow">MENOS CLIQUES. MAIS TEMPO PARA VOCÊ.</div>
              <h1>
                Seus arquivos,
                <br />
                <em>no lugar certo.</em>
              </h1>
              <p>
                Cole um link do Google Drive e me diga para onde levar.
                <br />
                Eu preparo, transfiro e acompanho tudo com você.
              </p>
              <div className="suggestions">
                <button onClick={() => setText('Baixe esta pasta para meu computador: ')}>
                  <div className="suggestion-icon green">
                    <Download size={20} />
                  </div>
                  <strong>Baixar para o PC</strong>
                  <span>Arquivos e pastas, organizados.</span>
                  <ArrowUpRight size={16} />
                </button>
                <button onClick={() => setText('Copie esta pasta para o MEGA: ')}>
                  <div className="suggestion-icon blue">
                    <Cloud size={20} />
                  </div>
                  <strong>Levar para o MEGA</strong>
                  <span>Uma cópia na sua nuvem.</span>
                  <ArrowUpRight size={16} />
                </button>
                <button onClick={() => setSetup('overview')}>
                  <div className="suggestion-icon amber">
                    <Settings2 size={20} />
                  </div>
                  <strong>Preparar meu espaço</strong>
                  <span>Conecte contas e destinos.</span>
                  <ArrowUpRight size={16} />
                </button>
              </div>
              <div className="welcome-note">
                <ShieldCheck size={15} />
                Você acompanha cada etapa. Seus arquivos originais ficam preservados.
              </div>
            </section>
          ) : (
            <section className="messages">
              {messages.map((m) => (
                <article key={m.id} className={`message ${m.role}`}>
                  {m.role !== 'user' && (
                    <div className="message-icon">
                      {m.role === 'system' ? (
                        <CheckCircle2 size={18} />
                      ) : (
                        <ArrowRightLeft size={18} />
                      )}
                    </div>
                  )}
                  <div className="message-content">
                    {m.role === 'system' && (
                      <div className="notification-label">
                        ATUALIZAÇÃO DA TAREFA · {statusLabel[m.status || '']}
                      </div>
                    )}
                    {m.text && <div className="message-text">{m.text}</div>}
                    {m.plan && renderPlan(m.plan)}
                    {m.task_id &&
                      jobs
                        .filter((j) => j.id === m.task_id)
                        .map((job) => (
                          <JobCard
                            key={job.id}
                            job={job}
                            destination={destinations.find((d) => d.id === job.spec.destination_id)}
                            onChange={() => {
                              refresh();
                              load(conversation);
                            }}
                          />
                        ))}
                    {m.actions?.map((a, n) => (
                      <button
                        className="inline-action"
                        key={n}
                        onClick={() => setSetup(a.provider)}
                      >
                        <Settings2 size={15} />
                        Abrir configuração
                        <ArrowUpRight size={14} />
                      </button>
                    ))}
                  </div>
                </article>
              ))}
              {busy && (
                <div className="message assistant">
                  <div className="message-icon">
                    <ArrowRightLeft size={18} />
                  </div>
                  <div className="thinking">
                    <span />
                    <span />
                    <span />
                    Preparando sua resposta
                  </div>
                </div>
              )}
            </section>
          )}
          {queue.length > 0 && (
            <div className="queue-preview">
              <strong>
                <Folder size={16} />
                Fila preparada · {queue.length} itens
              </strong>
              {queue.map((q, n) => (
                <div key={q.item_id}>
                  {n + 1}. {q.folder_label || 'Origem ' + q.source_ref.slice(0, 8)}
                </div>
              ))}
              <button
                className="inline-action"
                disabled={archivedChat || busy}
                onClick={() => send('Comece a fila com minhas preferências.')}
              >
                Começar a fila
                <ArrowUpRight size={14} />
              </button>
            </div>
          )}
          <div ref={end} />
        </div>
        <div className="composer-area">
          {error && (
            <div role="alert" className="error">
              <AlertCircle size={16} />
              <span>{error}</span>
              <button className="icon" onClick={() => setError('')} aria-label="Fechar erro">
                <X size={14} />
              </button>
            </div>
          )}
          {archivedChat && selectedChat && (
            <div className="archived-notice" role="status">
              <span>Esta conversa está arquivada.</span>
              <button
                type="button"
                disabled={managing}
                onClick={() => archiveChat(selectedChat, false)}
              >
                Restaurar conversa
              </button>
            </div>
          )}
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <textarea
              aria-label="Mensagem"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Cole um link ou peça o que você precisa…"
              rows={2}
              disabled={archivedChat || managing}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <div className="composer-toolbar">
              <button type="button" onClick={() => setSetup('destination')}>
                <Plus size={18} />
                <span>Destino</span>
              </button>
              <div>
                <span className="composer-hint">Enter para enviar</span>
                <button
                  aria-label="Enviar mensagem"
                  className="send"
                  disabled={busy || !text.trim() || archivedChat || managing}
                >
                  {busy ? <LoaderCircle className="spin" size={19} /> : <ArrowUp size={20} />}
                </button>
              </div>
            </div>
          </form>
          <p className="footer-note">
            O progresso vem das transferências reais. Credenciais são preenchidas em campos
            protegidos.
          </p>
        </div>
      </main>
      {setup && (
        <SetupPanel
          section={setup}
          close={() => setSetup('')}
          health={health}
          destinations={destinations}
          refresh={refresh}
        />
      )}
      <dialog
        ref={deleteDialog}
        className="delete-dialog"
        aria-labelledby="delete-chat-title"
        aria-describedby="delete-chat-description"
        onCancel={(event) => {
          if (managing) event.preventDefault();
          else setDeleting(null);
        }}
        onClose={() => setDeleting(null)}
      >
        <h2 id="delete-chat-title">Excluir conversa?</h2>
        <p className="delete-chat-name">{deleting?.title}</p>
        <p id="delete-chat-description">
          As mensagens e a fila desta conversa serão excluídas permanentemente. Arquivos
          transferidos e o histórico de tarefas serão preservados.
        </p>
        <div className="delete-dialog-actions">
          <button disabled={managing} onClick={() => deleteDialog.current?.close()}>
            Cancelar
          </button>
          <button className="delete-confirm" disabled={managing} onClick={deleteChat}>
            {managing ? 'Excluindo…' : 'Excluir permanentemente'}
          </button>
        </div>
      </dialog>
    </div>
  );
}

function JobCard({
  job,
  destination,
  onChange,
}: {
  job: Job;
  destination?: Destination;
  onChange: () => void;
}) {
  const active = !finalStates.includes(job.status);
  const percent =
    job.stats?.totalBytes > 0
      ? Math.min(100, Math.round((job.stats.bytes / job.stats.totalBytes) * 100))
      : null;
  const transferring = ['copy', 'repair'].includes(job.stage) && active;
  const [error, setError] = useState('');
  return (
    <section className="job-card">
      <div className="job-head">
        <div className={`job-symbol ${job.status === 'success' ? 'complete' : ''}`}>
          {active ? (
            <LoaderCircle className="spin" size={19} />
          ) : job.status === 'success' ? (
            <Check size={19} />
          ) : (
            <AlertCircle size={19} />
          )}
        </div>
        <div>
          <strong>
            {job.spec.mode === 'inspect'
              ? 'Consulta de origem'
              : job.spec.mode === 'verify'
                ? 'Verificação de arquivos'
                : 'Transferência de arquivos'}
          </strong>
          <span>
            {stageLabel[job.stage]} · {statusLabel[job.status]}
          </span>
        </div>
        <code>{job.id.slice(0, 8)}</code>
      </div>
      {transferring && (
        <div className="progress-track">
          <div
            className={percent === null ? 'indeterminate' : ''}
            style={percent !== null ? { width: percent + '%' } : {}}
          />
        </div>
      )}
      <div className="job-stats">
        {transferring ? (
          <>
            <span>
              {bytes(job.stats.bytes)}
              {job.stats.totalBytes > 0 ? ' de ' + bytes(job.stats.totalBytes) : ''}
            </span>
            <span>
              {job.stats.speed > 0 ? bytes(job.stats.speed) + '/s' : 'Medindo velocidade'}
              {percent !== null ? ' · ' + percent + '%' : ''}
            </span>
          </>
        ) : (
          <span>{job.message}</span>
        )}
      </div>
      {job.items.map((item, n) => (
        <div className="job-item" key={n}>
          <FileText size={15} />
          <div>
            <strong>{item.name || 'Consultando origem…'}</strong>
            <small>{item.destination || ''}</small>
            <small>
              {item.count !== undefined
                ? `${item.count} arquivos · ${bytes(item.bytes)}${item.unknown_size ? ' + tamanho desconhecido' : ''}`
                : ''}
            </small>
            {item.audit && (
              <small>
                Auditoria:{' '}
                {item.audit.coverage === 'hash'
                  ? 'hash'
                  : item.audit.coverage === 'size'
                    ? 'tamanho'
                    : 'hash ou tamanho'}{' '}
                · {item.audit.ok ? 'compatível' : 'diferenças ou leitura inconclusiva'}
              </small>
            )}
            {item.message && <small>{item.message}</small>}
            {item.capacity && (
              <small>
                Espaço: {capacityLabels[item.capacity.status] || item.capacity.status} · livre{' '}
                {bytes(item.capacity.remote_free_bytes ?? item.capacity.local_free_bytes)}
              </small>
            )}
          </div>
          <span className={`status-dot state-${item.status}`} />
        </div>
      ))}
      {error && <p className="error">{error}</p>}
      <div className="job-actions">
        <a href={`/api/jobs/${job.id}/log`} target="_blank" rel="noreferrer">
          <FileText size={14} />
          Relatório
        </a>
        {destination?.kind === 'local' && (
          <button
            onClick={() =>
              api(`/destinations/${job.spec.destination_id}/open`, 'POST').catch((e) =>
                setError(e.message),
              )
            }
          >
            <Folder size={14} />
            Abrir destino local
          </button>
        )}
        {destination?.kind === 'mega' && (
          <a href="https://mega.nz/fm" target="_blank" rel="noreferrer">
            <Cloud size={14} />
            Abrir MEGA
          </a>
        )}
        {active && (
          <button
            onClick={async () => {
              try {
                await api(`/jobs/${job.id}/stop`, 'POST');
                onChange();
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            <Square size={13} />
            {job.cancel_requested ? 'Cancelamento solicitado' : 'Cancelar'}
          </button>
        )}
      </div>
    </section>
  );
}

function SetupPanel({
  section,
  close,
  health,
  destinations,
  refresh,
}: {
  section: string;
  close: () => void;
  health: any;
  destinations: Destination[];
  refresh: () => Promise<void>;
}) {
  const [tab, setTab] = useState(section === 'overview' ? 'rclone' : section);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [flow, setFlow] = useState<any>(null);
  const [folders, setFolders] = useState<any[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [prefs, setPrefs] = useState<any>({
    destination_id: '',
    default_action: 'download',
    export_gdocs: true,
    create_empty: true,
    auto_repair: true,
    reserve_bytes: 1024 ** 3,
  });
  const tabs = [
    ['rclone', 'Aplicativo'],
    ['model', 'OpenAI'],
    ['google', 'Google Drive'],
    ['mega', 'MEGA'],
    ['destination', 'Destinos'],
    ['preferences', 'Preferências'],
  ];
  const activeFlow = useRef<any>(null);
  useEffect(() => {
    api('/preferences')
      .then(setPrefs)
      .catch(() => {});
  }, []);
  useEffect(() => {
    setValues({});
    setError('');
    setNotice('');
  }, [tab]);
  useEffect(
    () => () => {
      if (activeFlow.current?.status === 'pending')
        api(`/setup/${activeFlow.current.id}`, 'DELETE').catch(() => {});
    },
    [],
  );
  useEffect(() => {
    activeFlow.current = flow;
    if (!flow || !['pending', 'exchanging'].includes(flow.status)) return;
    const timer = setInterval(
      () =>
        api(`/setup/${flow.id}`)
          .then((f) => {
            setFlow(f);
            if (f.status === 'success') {
              setNotice('Google Drive conectado.');
              refresh().catch(() => {});
            }
          })
          .catch((e) => setError(e.message)),
      2000,
    );
    return () => clearInterval(timer);
  }, [flow?.id, flow?.status]);
  const field = (key: string) => ({
    value: values[key] || '',
    onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
      setValues((v) => ({ ...v, [key]: e.target.value })),
  });
  async function action(work: () => Promise<any>, message = 'Configuração salva.') {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await work();
      if (message) setNotice(message);
      await refresh();
      return result;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function browseMega(path = '') {
    await action(async () => {
      const result = await api('/destinations/mega/folders?path=' + encodeURIComponent(path));
      setFolders(result.folders);
      setValues((v) => ({ ...v, path: result.path }));
    }, '');
  }
  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <section role="dialog" aria-modal="true" aria-label="Configuração" className="setup-panel">
        <div className="setup-title">
          <div>
            <Settings2 size={20} />
            <h2>Prepare seu espaço</h2>
          </div>
          <button className="icon" aria-label="Fechar configuração" onClick={close}>
            <X size={20} />
          </button>
        </div>
        <div className="setup-tabs">
          {tabs.map(([id, title]) => (
            <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
              {title}
            </button>
          ))}
        </div>
        <div className="setup-content">
          {tab === 'rclone' && (
            <>
              <span className="form-kicker">PRIMEIRO PASSO</span>
              <h3>Seu motor de transferências</h3>
              <p>
                O rclone faz as cópias e verificações. Vamos mantê-lo em uma instalação própria do
                aplicativo.
              </p>
              <div className="setup-status">
                <HardDrive size={24} />
                <div>
                  <strong>
                    {health?.rclone.installed
                      ? health.rclone.version
                      : 'rclone ainda não instalado'}
                  </strong>
                  <span>
                    {health?.rclone.installed
                      ? 'Pronto para conectar suas contas.'
                      : 'Instalação oficial com verificação de checksum.'}
                  </span>
                </div>
              </div>
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  action(() => api('/setup/install', 'POST'), 'rclone instalado e validado.')
                }
              >
                {busy ? <LoaderCircle size={17} className="spin" /> : <Download size={17} />}{' '}
                {health?.rclone.installed ? 'Atualizar instalação própria' : 'Instalar rclone'}
              </button>
              <p className="small muted">
                Atualizações só são feitas por este botão, quando não há tarefa ativa.
              </p>
            </>
          )}
          {tab === 'model' && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                action(async () => {
                  const result = await api('/setup', 'POST', { kind: 'model', values });
                  setValues({});
                  return result;
                }, 'Chave OpenAI salva com proteção local.');
              }}
            >
              <span className="form-kicker">SUA CONVERSA</span>
              <h3>Conecte o OpenAI</h3>
              <p>
                Informe a chave da API neste campo protegido. Ela não será enviada como mensagem ao
                assistente.
              </p>
              <label>
                Chave da API
                <input type="password" autoComplete="off" required {...field('api_key')} />
              </label>
              <button className="primary" disabled={busy}>
                Salvar chave
              </button>
              <a
                className="help-link"
                href="https://platform.openai.com/api-keys"
                target="_blank"
                rel="noreferrer"
              >
                Obter chave na OpenAI
                <ExternalLink size={13} />
              </a>
            </form>
          )}
          {tab === 'google' && (
            <>
              <span className="form-kicker">ORIGEM DOS ARQUIVOS</span>
              <h3>Seu Google Drive</h3>
              <p>
                Autorize a leitura e o download na página oficial do Google. Seus arquivos originais
                ficam preservados.
              </p>
              {health?.connections.google && (
                <div className="success">
                  <CheckCircle2 size={17} />
                  Conta conectada
                </div>
              )}
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  action(async () => {
                    const f = await api('/setup', 'POST', { kind: 'google', values });
                    setFlow(f);
                    setValues({});
                  }, 'Abra o botão abaixo para autorizar.');
                }}
              >
                <label>
                  ID OAuth do projeto <span className="muted">(se ainda não configurado)</span>
                  <input autoComplete="off" {...field('client_id')} />
                </label>
                <label>
                  Segredo OAuth <span className="muted">(quando exigido pelo cliente)</span>
                  <input type="password" autoComplete="off" {...field('client_secret')} />
                </label>
                <button className="primary" disabled={busy}>
                  {health?.connections.google ? 'Reconectar conta' : 'Preparar conexão Google'}
                </button>
              </form>
              {flow && (
                <div className="oauth-card">
                  <strong>Autorização: {flowLabels[flow.status] || flow.status}</strong>
                  {flow.status === 'pending' && (
                    <>
                      <a
                        className="primary"
                        href={flow.authorization_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Autorizar no Google
                        <ExternalLink size={15} />
                      </a>
                      <button
                        className="secondary"
                        onClick={() =>
                          action(
                            async () => setFlow(await api(`/setup/${flow.id}`, 'DELETE')),
                            'Autorização cancelada.',
                          )
                        }
                      >
                        Cancelar autorização
                      </button>
                    </>
                  )}
                </div>
              )}
              <p className="small muted">
                O cliente OAuth é provisionado uma vez pelo desenvolvedor. A conexão usa acesso de
                leitura.
              </p>
            </>
          )}
          {tab === 'mega' && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                action(async () => {
                  const result = await api('/setup', 'POST', { kind: 'mega', values });
                  setValues({});
                  return result;
                }, 'Conta MEGA conectada.');
              }}
            >
              <span className="form-kicker">DESTINO NA NUVEM</span>
              <h3>Conecte seu MEGA</h3>
              <p>
                O aplicativo valida a conexão antes de salvar. Use uma conta já acessada pelo
                navegador.
              </p>
              {health?.connections.mega && (
                <div className="success">
                  <CheckCircle2 size={17} />
                  Conta conectada
                </div>
              )}
              <label>
                E-mail
                <input type="email" autoComplete="username" required {...field('email')} />
              </label>
              <label>
                Senha
                <input
                  type="password"
                  autoComplete="current-password"
                  required
                  {...field('password')}
                />
              </label>
              <label>
                Código temporário <span className="muted">(se sua conta usa 2FA)</span>
                <input autoComplete="one-time-code" {...field('otp')} />
              </label>
              <button className="primary" disabled={busy}>
                {busy ? 'Validando conexão…' : 'Conectar MEGA'}
              </button>
              <p className="small muted">
                A disponibilidade do acesso com 2FA depende da sessão do provedor. Se um novo código
                for exigido, reconecte por aqui.
              </p>
            </form>
          )}
          {tab === 'destination' && (
            <>
              <span className="form-kicker">ONDE GUARDAR</span>
              <h3>Dê um nome aos seus destinos</h3>
              <p>Depois você pode pedir “salve em Cursos” ou usar seu destino padrão.</p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  action(async () => {
                    const d = await api('/destinations', 'POST', {
                      name: values.name,
                      kind: values.kind || 'local',
                      path: values.path || '',
                    });
                    setValues({});
                    return d;
                  }, 'Destino cadastrado. Escolha-o nas preferências.');
                }}
              >
                <label>
                  Nome amigável
                  <input required placeholder="Meus cursos" {...field('name')} />
                </label>
                <label>
                  Tipo
                  <select
                    value={values.kind || 'local'}
                    onChange={(e) => {
                      setValues((v) => ({ ...v, kind: e.target.value, path: '' }));
                      setFolders([]);
                    }}
                  >
                    <option value="local">Pasta neste computador</option>
                    <option value="mega">Pasta no MEGA</option>
                  </select>
                </label>
                <label>
                  Caminho
                  <input
                    required={values.kind !== 'mega'}
                    placeholder={values.kind === 'mega' ? 'Cursos/2026' : 'D:\Downloads'}
                    {...field('path')}
                  />
                </label>
                {values.kind === 'mega' ? (
                  <>
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy}
                      onClick={() => browseMega(values.path || '')}
                    >
                      <Folder size={15} />
                      Navegar no MEGA
                    </button>
                    <div className="folder-browser">
                      {folders.map((f) => (
                        <button key={f.path} type="button" onClick={() => browseMega(f.path)}>
                          <Folder size={14} />
                          {f.name}
                        </button>
                      ))}
                      <button type="button" onClick={() => browseMega('')}>
                        Voltar à raiz
                      </button>
                    </div>
                  </>
                ) : (
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      action(async () => {
                        const result = await api('/destinations/select-local', 'POST');
                        if (result.path) setValues((v) => ({ ...v, path: result.path }));
                      }, '')
                    }
                  >
                    <Folder size={15} />
                    Escolher pasta
                  </button>
                )}
                <button className="primary" disabled={busy}>
                  Cadastrar destino
                </button>
              </form>
              <div className="destination-list">
                {destinations.map((d) => (
                  <div key={d.id}>
                    <Folder size={16} />
                    <div>
                      <strong>{d.name}</strong>
                      <small>
                        {d.kind === 'mega' ? 'MEGA: ' : ''}
                        {d.path || 'Raiz'}
                      </small>
                    </div>
                    <button
                      className="icon"
                      aria-label={'Consultar espaço em ' + d.name}
                      onClick={() =>
                        action(async () => {
                          const c = await api(`/destinations/${d.id}/capacity`);
                          setNotice(
                            `Espaço livre: ${bytes(c.remote_free_bytes ?? c.local_free_bytes)}. Reserva local: ${bytes(c.reserve_bytes)}.`,
                          );
                        }, '')
                      }
                    >
                      <HardDrive size={17} />
                    </button>
                  </div>
                ))}
              </div>
            </>
          )}
          {tab === 'preferences' && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                action(
                  () => api('/preferences', 'PUT', prefs),
                  'Preferências salvas. Links isolados usarão este padrão.',
                );
              }}
            >
              <span className="form-kicker">DO SEU JEITO</span>
              <h3>Defina uma vez. Use sempre.</h3>
              <label>
                Destino padrão
                <select
                  aria-label="Destino padrão"
                  required
                  value={prefs.destination_id || ''}
                  onChange={(e) => setPrefs((p: any) => ({ ...p, destination_id: e.target.value }))}
                >
                  <option value="">Escolha um destino</option>
                  {destinations.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Ao enviar apenas um link
                <select
                  aria-label="Ação padrão"
                  value={prefs.default_action}
                  onChange={(e) => setPrefs((p: any) => ({ ...p, default_action: e.target.value }))}
                >
                  <option value="download">Iniciar cópia para o destino padrão</option>
                  <option value="inspect">Consultar tamanho e conteúdo</option>
                </select>
              </label>
              {[
                ['export_gdocs', 'Exportar documentos Google'],
                ['create_empty', 'Preservar subpastas vazias'],
                ['auto_repair', 'Reparar diferenças após a auditoria'],
              ].map(([key, title]) => (
                <label className="checkbox" key={key}>
                  <input
                    type="checkbox"
                    checked={prefs[key]}
                    onChange={(e) => setPrefs((p: any) => ({ ...p, [key]: e.target.checked }))}
                  />
                  {title}
                </label>
              ))}
              <label>
                Reserva de espaço local (GiB)
                <input
                  type="number"
                  min="0"
                  step="0.25"
                  value={prefs.reserve_bytes / 1024 ** 3}
                  onChange={(e) =>
                    setPrefs((p: any) => ({
                      ...p,
                      reserve_bytes: Math.round(Number(e.target.value) * 1024 ** 3),
                    }))
                  }
                />
              </label>
              <div className="info-note">
                Arquivos iguais são reaproveitados. Arquivos diferentes podem ser substituídos.
                Arquivos extras e originais são preservados.
              </div>
              <button className="primary" disabled={busy}>
                Salvar preferências
              </button>
            </form>
          )}
          {['google', 'mega'].includes(tab) && health?.connections[tab] && (
            <div className="connection-actions">
              <button
                className="secondary"
                disabled={busy}
                onClick={() =>
                  action(() => api(`/connections/${tab}/test`, 'POST'), 'Conexão validada.')
                }
              >
                Testar conexão
              </button>
              <button
                className="text-button"
                disabled={busy}
                onClick={() =>
                  action(
                    () => api(`/connections/${tab}`, 'DELETE'),
                    'Conexão removida do aplicativo.',
                  )
                }
              >
                Desconectar
              </button>
            </div>
          )}
          {busy && (
            <div className="working">
              <LoaderCircle size={16} className="spin" />
              Processando…
            </div>
          )}
          {notice && (
            <div role="status" className="success">
              <CheckCircle2 size={16} />
              {notice}
            </div>
          )}
          {error && (
            <div role="alert" className="error">
              <AlertCircle size={16} />
              {error}
            </div>
          )}
        </div>
        <footer className="setup-footer">
          <ShieldCheck size={14} />
          Credenciais protegidas no computador. Fora do histórico do chat.
        </footer>
      </section>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
