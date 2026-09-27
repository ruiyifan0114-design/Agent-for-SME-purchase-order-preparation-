import { useEffect, useRef, useState } from 'react'
import { ArrowUp, Bot, Loader2, Sparkles, X } from 'lucide-react'
import { api } from './api'
import type { AgentReply } from './types'

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
    { role: 'user' | 'agent' | 'error'; text: string; provider?: string }[]
  >([
    {
      role: 'agent',
      text: 'I’m your procurement assistant. Ask for a daily brief, review changes, explain a SKU, or prepare the next action. Stored backend evidence remains the source of truth.',
    },
  ])
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
    setInput('')
    setMessages((old) => [...old, { role: 'user', text }])
    setBusy(true)
    try {
      const response = await api.message(text, runId, sku)
      if (!alive.current) return
      if (response.sku_id) setSku(response.sku_id)
      setMessages((old) => [
        ...old,
        { role: 'agent', text: response.message, provider: response.provider },
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
          <small>One assistant. Your decisions.</small>
        </div>
        <button className="icon-button" onClick={onClose} aria-label="Close agent">
          <X size={18} />
        </button>
      </header>
      <div ref={list} className="chat-messages" aria-live="polite">
        {messages.map((m, i) => (
          <div className={`message ${m.role}`} key={i}>
            <p>{m.text}</p>
            {m.provider && (
              <small>
                {m.provider === 'DeepSeek'
                  ? 'DeepSeek intent · backend evidence'
                  : 'Procurement workflow'}
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
          'What changed since the last review?',
          'Why is SKU-004 blocked?',
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
          placeholder="Ask about this review…"
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
