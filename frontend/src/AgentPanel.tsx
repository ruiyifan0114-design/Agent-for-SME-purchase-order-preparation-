import { useEffect, useRef, useState } from 'react'
import { ArrowUp, Bot, History, Loader2, Plus, Sparkles, Trash2, X } from 'lucide-react'
import { api } from './api'
import type { AgentChatMessage, AgentConversation, AgentEvidence, AgentReply, ChatTurn } from './types'

const welcome = {
  role: 'agent' as const,
  text: 'Ask me anything about this procurement review. I can inspect live SKU evidence, compare suppliers, explain exceptions, and run read-only scenarios with DeepSeek.',
}

type UiMessage = { role: 'user' | 'agent' | 'error'; text: string; provider?: string; tools?: string[];
  evidence?: AgentEvidence[]; unresolved?: string[]; evidenceComplete?: boolean; interactionId?: string }

function storedMessages(items: AgentChatMessage[]): UiMessage[] {
  return items.map((item) => ({
    role: item.role === 'assistant' ? 'agent' : 'user', text: item.content,
    provider: item.message_metadata.provider, tools: item.message_metadata.tools_used,
    evidence: item.message_metadata.evidence, unresolved: item.message_metadata.unresolved,
    evidenceComplete: item.message_metadata.evidence_complete,
    interactionId: item.interaction_id || undefined,
  }))
}

function inlineMarkup(text: string) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**'))
      return <strong key={index}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`'))
      return <code key={index}>{part.slice(1, -1)}</code>
    return part
  })
}

function MessageBody({ text }: { text: string }) {
  return (
    <div className="chat-message-body">
      {text.split('\n').map((line, index) => {
        const heading = line.match(/^#{1,3}\s+(.+)/)
        const bullet = line.match(/^[-*]\s+(.+)/)
        const numbered = line.match(/^(\d+)\.\s+(.+)/)
        if (!line.trim()) return <span className="chat-line-break" key={index} />
        if (heading) return <h4 key={index}>{inlineMarkup(heading[1])}</h4>
        if (bullet)
          return (
            <div className="chat-list-item" key={index}>
              • {inlineMarkup(bullet[1])}
            </div>
          )
        if (numbered)
          return (
            <div className="chat-list-item" key={index}>
              {numbered[1]}. {inlineMarkup(numbered[2])}
            </div>
          )
        return <p key={index}>{inlineMarkup(line)}</p>
      })}
    </div>
  )
}

export default function AgentPanel({
  runId,
  onClose,
  onAction,
}: {
  runId?: string
  onClose: () => void
  onAction: (r: AgentReply) => void
}) {
  const [messages, setMessages] = useState<UiMessage[]>([welcome])
  const [input, setInput] = useState(''),
    [busy, setBusy] = useState(false),
    [sku, setSku] = useState<string>(),
    [conversations, setConversations] = useState<AgentConversation[]>([]),
    [conversationId, setConversationId] = useState(''),
    [historyOpen, setHistoryOpen] = useState(false),
    [oldestMessageId, setOldestMessageId] = useState<string>(),
    [hasOlder, setHasOlder] = useState(false),
    [historyReady, setHistoryReady] = useState(false)
  const alive = useRef(true),
    list = useRef<HTMLDivElement>(null)
  useEffect(() => {
    alive.current = true
    void loadConversations()
    return () => {
      alive.current = false
    }
  }, [])
  useEffect(() => {
    if (list.current) list.current.scrollTop = list.current.scrollHeight
  }, [messages, busy])
  async function loadConversations(preferred?: string) {
    try {
      const rows = await api.agentConversations()
      if (!alive.current) return
      setConversations(rows)
      const requested = preferred || conversationId
      const selected = rows.some((row) => row.id === requested) ? requested : rows[0]?.id
      if (selected) await openConversation(selected)
      else {
        setConversationId('')
        setMessages([welcome])
      }
    } catch (error) {
      if (alive.current) setMessages([{ role: 'error', text: error instanceof Error ? error.message : 'Unable to load chat history.' }])
    } finally {
      if (alive.current) setHistoryReady(true)
    }
  }
  async function openConversation(id: string) {
    const detail = await api.agentConversation(id)
    if (!alive.current) return
    setConversationId(id)
    setSku(undefined)
    setMessages(detail.messages.length ? storedMessages(detail.messages) : [welcome])
    setOldestMessageId(detail.oldest_message_id || undefined)
    setHasOlder(detail.has_more)
    setHistoryOpen(false)
  }
  async function loadOlderMessages() {
    if (!conversationId || !oldestMessageId || busy) return
    setBusy(true)
    try {
      const detail = await api.agentConversation(conversationId, oldestMessageId)
      if (!alive.current) return
      setMessages((current) => [...storedMessages(detail.messages), ...current])
      setOldestMessageId(detail.oldest_message_id || undefined)
      setHasOlder(detail.has_more)
    } catch (error) {
      if (alive.current) setMessages((current) => [{ role: 'error', text: error instanceof Error ? error.message : 'Unable to load older messages.' }, ...current])
    } finally {
      if (alive.current) setBusy(false)
    }
  }
  async function newConversation(title = 'New procurement chat', reset = true) {
    const created = await api.createAgentConversation(title, runId)
    if (!alive.current) return created.id
    setConversationId(created.id)
    if (reset) {
      setMessages([welcome])
      setSku(undefined)
      setHasOlder(false)
      setOldestMessageId(undefined)
    }
    setHistoryOpen(false)
    setConversations((old) => [{ ...created, message_count: 0, last_message: '' }, ...old])
    return created.id
  }
  async function deleteConversation() {
    if (!conversationId || busy) return
    if (!window.confirm('Delete this chat and its saved messages? This cannot be undone.')) return
    setBusy(true)
    try {
      await api.deleteAgentConversation(conversationId)
      setConversationId('')
      setMessages([welcome])
      await loadConversations()
    } catch (error) {
      setMessages((old) => [...old, { role: 'error', text: error instanceof Error ? error.message : 'Unable to delete chat.' }])
    } finally {
      if (alive.current) setBusy(false)
    }
  }
  async function send(text: string) {
    if (!text.trim() || busy || !historyReady) return
    const history: ChatTurn[] = messages
      .filter((message, index) => index > 0 && message.role !== 'error')
      .map((message): ChatTurn => ({
        role: message.role === 'agent' ? 'assistant' : 'user',
        content: message.text.slice(0, 4000),
      }))
      .slice(-10)
    setInput('')
    setMessages((old) => [...old, { role: 'user', text }])
    setBusy(true)
    try {
      const activeConversation = conversationId || await newConversation(text.trim().slice(0, 120), false)
      const response = await api.message(text, runId, sku, activeConversation ? [] : history, activeConversation)
      if (!alive.current) return
      if (response.sku_id) setSku(response.sku_id)
      setMessages((old) => [
        ...old,
        {
          role: 'agent',
          text: response.message,
          provider: response.provider,
          tools: response.tools_used,
          evidence: response.evidence,
          unresolved: response.unresolved,
          evidenceComplete: response.evidence_complete,
          interactionId: response.interaction_id,
        },
      ])
      onAction(response)
      const rows = await api.agentConversations()
      if (alive.current) setConversations(rows)
    } catch (e) {
      if (!alive.current) return
      setMessages((old) => [
        ...old,
        {
          role: 'error',
          text: e instanceof Error ? e.message : 'Message failed. No action confirmed.',
        },
      ])
    } finally {
      if (alive.current) setBusy(false)
    }
  }
  return (
    <aside className="agent-panel" aria-label="Procurement agent">
      <header>
        <span className="agent-avatar">
          <Bot size={22} />
        </span>
        <div>
          <strong>Procurement agent</strong>
          <small>DeepSeek · workspace evidence</small>
        </div>
        <button
          className="icon-button"
          disabled={busy || !historyReady}
          onClick={() => setHistoryOpen((value) => !value)}
          aria-label="Chat history"
          title="Chat history"
        >
          <History size={16} />
        </button>
        <button className="icon-button" onClick={onClose} aria-label="Close agent">
          <X size={18} />
        </button>
      </header>
      <div className="chat-session-bar">
        <button disabled={busy || !historyReady} onClick={() => void newConversation()} title="Start a new chat">
          <Plus size={15} /> New chat
        </button>
        <span>{conversations.find((item) => item.id === conversationId)?.title || 'Unsaved chat'}</span>
        <button className="session-delete" disabled={busy || !conversationId} onClick={() => void deleteConversation()} title="Delete this chat">
          <Trash2 size={14} />
        </button>
      </div>
      {historyOpen && (
        <div className="chat-history" aria-label="Saved chats">
          <strong>Chat history</strong>
          {conversations.length ? conversations.map((item) => (
            <button className={item.id === conversationId ? 'active' : ''} key={item.id}
              onClick={() => void openConversation(item.id)} disabled={busy}>
              <span>{item.title}</span>
              <small>{item.message_count} messages</small>
            </button>
          )) : <small>No saved chats yet.</small>}
        </div>
      )}
      <div ref={list} className="chat-messages" aria-live="polite">
        {hasOlder && (
          <button className="load-older-chat" disabled={busy} onClick={() => void loadOlderMessages()}>
            Load older messages
          </button>
        )}
        {messages.map((m, i) => (
          <div className={`message ${m.role}`} key={i}>
            <MessageBody text={m.text} />
            {m.provider && (
              <small>
                {m.provider === 'DeepSeek ReAct'
                  ? `DeepSeek analysis · ${m.tools?.length || 0} verified workspace tool${m.tools?.length === 1 ? '' : 's'}`
                  : m.provider}
              </small>
            )}
            {!!m.evidence?.length && (
              <details className="agent-evidence">
                <summary>{m.evidence.length} evidence field{m.evidence.length === 1 ? '' : 's'}</summary>
                {m.evidence.slice(0, 12).map((item, index) => (
                  <div key={`${item.record_id}-${item.field}-${index}`}>
                    <strong>{item.field}</strong> · {item.source} · {item.record_id} · v{item.version}
                  </div>
                ))}
                {m.evidence.length > 12 && <div>Open the audit view for the remaining evidence.</div>}
                {m.evidenceComplete === false && <div>Evidence list continues; no completeness claim was made.</div>}
              </details>
            )}
            {!!m.unresolved?.length && (
              <div className="agent-unresolved"><strong>Unresolved</strong>: {m.unresolved.join('; ')}</div>
            )}
            {m.interactionId && <small>Audit run {m.interactionId}</small>}
          </div>
        ))}
        {busy && (
          <div className="message agent">
            <Loader2 className="spin" size={17} /> Checking…
          </div>
        )}
      </div>
      <div className="chat-suggestions">
        {[
          "Give me today's daily brief.",
          'Which supplier has the highest recommended spend, and what should I review first?',
          'What changed since the last review?',
          'Compare blocked SKUs with the previous review.',
        ].map((s) => (
          <button disabled={busy || !historyReady} onClick={() => void send(s)} key={s}>
            <Sparkles size={12} />
            {s}
          </button>
        ))}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void send(input)
        }}
      >
        <input
          aria-label="Message the procurement agent"
          placeholder="Ask anything about this review…"
          value={input}
          maxLength={2000}
          disabled={!historyReady}
          onChange={(e) => setInput(e.target.value)}
        />
        <button disabled={busy || !historyReady || !input.trim()} aria-label="Send message">
          <ArrowUp size={19} />
        </button>
      </form>
      <footer>Edits open a review form. Approval is always yours.</footer>
    </aside>
  )
}
