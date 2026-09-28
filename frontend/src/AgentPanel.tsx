import { useEffect, useRef, useState } from 'react'
import { ArrowUp, Bot, Loader2, RotateCcw, Sparkles, X } from 'lucide-react'
import { api } from './api'
import type { AgentReply, ChatTurn } from './types'

const welcome = {
  role: 'agent' as const,
  text: 'Ask me anything about this procurement review. I can inspect live SKU evidence, compare suppliers, explain exceptions, and run read-only scenarios with DeepSeek.',
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
  const [messages, setMessages] = useState<
    { role: 'user' | 'agent' | 'error'; text: string; provider?: string; tools?: string[] }[]
  >([welcome])
  const [input, setInput] = useState(''),
    [busy, setBusy] = useState(false),
    [sku, setSku] = useState<string>()
  const alive = useRef(true),
    list = useRef<HTMLDivElement>(null)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  useEffect(() => {
    if (list.current) list.current.scrollTop = list.current.scrollHeight
  }, [messages, busy])
  async function send(text: string) {
    if (!text.trim() || busy) return
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
      const response = await api.message(text, runId, sku, history)
      if (!alive.current) return
      if (response.sku_id) setSku(response.sku_id)
      setMessages((old) => [
        ...old,
        {
          role: 'agent',
          text: response.message,
          provider: response.provider,
          tools: response.tools_used,
        },
      ])
      onAction(response)
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
          disabled={busy}
          onClick={() => {
            setMessages([welcome])
            setSku(undefined)
          }}
          aria-label="Clear conversation"
          title="Clear conversation"
        >
          <RotateCcw size={16} />
        </button>
        <button className="icon-button" onClick={onClose} aria-label="Close agent">
          <X size={18} />
        </button>
      </header>
      <div ref={list} className="chat-messages" aria-live="polite">
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
          <button disabled={busy} onClick={() => void send(s)} key={s}>
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
          onChange={(e) => setInput(e.target.value)}
        />
        <button disabled={busy || !input.trim()} aria-label="Send message">
          <ArrowUp size={19} />
        </button>
      </form>
      <footer>Edits open a review form. Approval is always yours.</footer>
    </aside>
  )
}
