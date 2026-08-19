'use client'

import React, { useState, useRef, useEffect, useCallback } from "react"
import { 
  Send, Loader2, MessageSquare, Plus, User, Bot, 
  Github, ThumbsUp, RefreshCw, Share2 
} from "lucide-react"
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export type MessagePart = {
  type: "text"
  text: string
}

export type Message = {
  id: string
  role: "user" | "assistant"
  parts: MessagePart[]
}

export type Conversation = {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messages: Message[]
}

const STORAGE_KEY = "ctu_chatbot_conversations_v1"
const ACTIVE_CONV_KEY = "ctu_chatbot_active_id_v1"

export default function Chat() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConvId, setActiveConvId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [status, setStatus] = useState<"idle" | "streaming">("idle")
  const [isInitialized, setIsInitialized] = useState(false)

  const scrollRef = useRef<HTMLDivElement>(null)
  const bufferRef = useRef("")
  const flushTimer = useRef<NodeJS.Timeout | null>(null)
  const activeConvIdRef = useRef<string | null>(null)

  // Keep activeConvId ref in sync for streaming closures
  useEffect(() => {
    activeConvIdRef.current = activeConvId
  }, [activeConvId])

  // Load conversations from localStorage on initial render
  useEffect(() => {
    try {
      const savedData = localStorage.getItem(STORAGE_KEY)
      const savedActiveId = localStorage.getItem(ACTIVE_CONV_KEY)
      if (savedData) {
        const parsed: Conversation[] = JSON.parse(savedData)
        if (Array.isArray(parsed) && parsed.length > 0) {
          parsed.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
          setConversations(parsed)

          const target = parsed.find(c => c.id === savedActiveId) || parsed[0]
          if (target) {
            setActiveConvId(target.id)
            setMessages(target.messages || [])
          }
        }
      }
    } catch (e) {
      console.error("Failed to load conversation history from localStorage:", e)
    } finally {
      setIsInitialized(true)
    }
  }, [])

  // Save conversations to localStorage whenever they change
  useEffect(() => {
    if (!isInitialized) return
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations))
      if (activeConvId) {
        localStorage.setItem(ACTIVE_CONV_KEY, activeConvId)
      } else {
        localStorage.removeItem(ACTIVE_CONV_KEY)
      }
    } catch (e) {
      console.error("Failed to save conversation history to localStorage:", e)
    }
  }, [conversations, activeConvId, isInitialized])

  // Auto-scroll when messages update
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth"
      })
    }
  }, [messages, status])

  // Flush text buffer during streaming
  const flushBuffer = useCallback((assistantId: string) => {
    const text = bufferRef.current
    bufferRef.current = ""
    if (!text) return

    setMessages(prev => {
      const updated: Message[] = prev.map(m =>
        m.id === assistantId
          ? { ...m, parts: [{ type: "text" as const, text: (m.parts[0]?.text || "") + text }] }
          : m
      )

      // Sync into current conversation in state
      const currentId = activeConvIdRef.current
      if (currentId) {
        setConversations(convs =>
          convs.map(c =>
            c.id === currentId
              ? { ...c, messages: updated, updatedAt: Date.now() }
              : c
          )
        )
      }
      return updated
    })
  }, [])

  // Start a new conversation
  const handleNewChat = () => {
    if (status === "streaming") return

    setActiveConvId(null)
    setMessages([])
    setInput("")
  }

  // Switch to an existing conversation
  const handleSelectConversation = (conv: Conversation) => {
    if (status === "streaming" || conv.id === activeConvId) return

    setActiveConvId(conv.id)
    setMessages(conv.messages || [])
    setInput("")
  }

  // Send message
  const handleSend = async (e?: React.FormEvent, customPrompt?: string) => {
    if (e) e.preventDefault()
    const messageText = (customPrompt || input).trim()
    if (!messageText || status === "streaming") return

    const nowTimestamp = Date.now()
    const userMsg: Message = {
      id: nowTimestamp.toString(),
      role: "user",
      parts: [{ type: "text" as const, text: messageText }]
    }

    let currentConvId = activeConvId
    let newConversations = [...conversations]

    // If starting a fresh chat session without an active conversation
    if (!currentConvId) {
      currentConvId = "conv_" + nowTimestamp
      const shortTitle = messageText.length > 38 
        ? messageText.substring(0, 38) + "..." 
        : messageText

      const newConv: Conversation = {
        id: currentConvId,
        title: shortTitle,
        createdAt: nowTimestamp,
        updatedAt: nowTimestamp,
        messages: [userMsg]
      }
      newConversations = [newConv, ...newConversations]
      setActiveConvId(currentConvId)
      setConversations(newConversations)
      setMessages([userMsg])
    } else {
      // Append to existing conversation
      const nextMessages = [...messages, userMsg]
      setMessages(nextMessages)
      newConversations = newConversations.map(c =>
        c.id === currentConvId
          ? { ...c, messages: nextMessages, updatedAt: nowTimestamp }
          : c
      ).sort((a, b) => b.updatedAt - a.updatedAt)
      setConversations(newConversations)
    }

    setInput("")
    setStatus("streaming")

    try {
      const payloadMessages = (currentConvId 
        ? newConversations.find(c => c.id === currentConvId)?.messages || [...messages, userMsg]
        : [...messages, userMsg]
      ).map(m => ({ role: m.role, parts: m.parts }))

      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: payloadMessages
        })
      })

      if (!response.body) throw new Error("No response body received")

      const assistantId = (Date.now() + 1).toString()
      const assistantMsg: Message = { 
        id: assistantId, 
        role: "assistant", 
        parts: [{ type: "text" as const, text: "" }] 
      }

      setMessages(prev => [...prev, assistantMsg])

      const reader = response.body.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split("\n")

        for (const line of lines) {
          if (!line.startsWith("0:")) continue
          try {
            const token = JSON.parse(line.slice(2))
            bufferRef.current += token
            if (!flushTimer.current) {
              flushTimer.current = setTimeout(() => {
                flushBuffer(assistantId)
                flushTimer.current = null
              }, 30)
            }
          } catch (err) { 
            console.error("Stream parse error:", err) 
          }
        }
      }
      flushBuffer(assistantId)
    } catch (err) {
      console.error("Chat error:", err)
      const errorMsg: Message = {
        id: (Date.now() + 2).toString(),
        role: "assistant",
        parts: [{ type: "text" as const, text: "Xin lỗi, đã xảy ra lỗi kết nối với máy chủ học vụ. Vui lòng thử lại sau giây lát." }]
      }
      setMessages(prev => {
        const updated = [...prev, errorMsg]
        if (currentConvId) {
          setConversations(convs =>
            convs.map(c =>
              c.id === currentConvId
                ? { ...c, messages: updated, updatedAt: Date.now() }
                : c
            )
          )
        }
        return updated
      })
    } finally {
      setStatus("idle")
    }
  }

  return (
    <div className="flex h-screen bg-[#F8FAFC] font-sans text-slate-900 selection:bg-blue-100">
      {/* Sidebar - Modern Glassmorphism */}
      <aside className="hidden md:flex w-80 bg-white/70 backdrop-blur-xl border-r border-slate-200/60 flex-col">
        <div className="p-6 flex items-center gap-3">
          <div className="w-10 h-10 bg-linear-to-br from-blue-600 to-indigo-700 rounded-xl flex items-center justify-center text-white shadow-lg shadow-blue-200">
            <Bot size={24} />
          </div>
          <div>
            <h1 className="font-bold text-slate-800 tracking-tight leading-none">CTUChatbot</h1>
            <span className="text-[10px] text-blue-600 font-bold uppercase tracking-widest">Enterprise Edition</span>
          </div>
        </div>

        <div className="p-4">
          <button 
            onClick={handleNewChat}
            className="w-full flex items-center justify-center gap-2 p-3 bg-white text-slate-700 rounded-xl hover:bg-slate-50 transition-all font-semibold border border-slate-200 shadow-sm active:scale-[0.98] cursor-pointer"
          >
            <Plus size={18}/> Cuộc hội thoại mới
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-2 space-y-1">
          <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider px-3 mt-4 mb-2">Lịch sử tư vấn</div>
          
          {conversations.length === 0 ? (
            <div className="px-3 py-6 text-center text-xs text-slate-400">
              Chưa có lịch sử cuộc trò chuyện nào
            </div>
          ) : (
            conversations.map((conv) => {
              const isActive = conv.id === activeConvId
              return (
                <div
                  key={conv.id}
                  onClick={() => handleSelectConversation(conv)}
                  className={`group flex items-center gap-3 p-3 rounded-xl cursor-pointer transition-all text-sm font-medium ${
                    isActive
                      ? "bg-blue-50/80 border border-blue-100 text-blue-700"
                      : "text-slate-600 hover:bg-slate-50 border border-transparent"
                  }`}
                >
                  <MessageSquare size={16} className={isActive ? "text-blue-600" : "text-slate-400"}/>
                  <span className="truncate flex-1">{conv.title || "Cuộc trò chuyện"}</span>
                </div>
              )
            })
          )}
        </div>

        <div className="p-4 border-t border-slate-100 bg-white/50">
          <div className="flex items-center gap-3 p-2 rounded-xl hover:bg-slate-100/50 transition-all cursor-pointer group">
            <div className="w-10 h-10 bg-linear-to-tr from-slate-100 to-slate-200 rounded-full flex items-center justify-center text-slate-500 group-hover:from-blue-50 group-hover:to-blue-100 group-hover:text-blue-600 transition-all">
              <User size={20}/>
            </div>
            <div className="flex-1 overflow-hidden">
              <div className="text-sm font-bold truncate text-slate-800">Tinh - CTU Student</div>
              <div className="text-[10px] text-slate-400 font-medium">Tinh.ctu.edu.vn</div>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex flex-col flex-1 relative min-w-0 bg-white">
        {/* Transparent Header */}
        <header className="h-16 flex items-center justify-between px-8 bg-white/80 backdrop-blur-md border-b border-slate-100 sticky top-0 z-20">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 px-3 py-1 bg-emerald-50 rounded-full border border-emerald-100">
              <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse"></div>
              <span className="text-[11px] font-bold text-emerald-700 uppercase tracking-tight">Hệ thống đang trực tuyến</span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-all"><Share2 size={18}/></button>
            <div className="h-4 w-px bg-slate-200 mx-1"></div>
            <button className="p-2 text-slate-400 hover:text-slate-900 transition-colors"><Github size={20}/></button>
          </div>
        </header>

        {/* Conversation View */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto w-full py-10 px-6 space-y-10">
            {messages.length === 0 ? (
              <div className="py-20 flex flex-col items-center justify-center text-center space-y-6">
                <div className="w-20 h-20 bg-blue-50 rounded-4xl flex items-center justify-center text-blue-600 rotate-3 hover:rotate-0 transition-transform duration-500 shadow-inner">
                  <Bot size={40}/>
                </div>
                <div className="space-y-2">
                  <h2 className="text-3xl font-extrabold text-slate-800 tracking-tight">Trợ lý học vụ CTU</h2>
                  <p className="text-slate-500 max-w-sm mx-auto text-sm leading-relaxed">
                    Xin chào! Tôi là trợ lý học vụ của Đại học Cần Thơ. 
                  </p>
                </div>
              </div>
            ) : (
              messages.map(m => (
                <div key={m.id} className={`flex gap-4 ${m.role === "user" ? "flex-row-reverse" : "flex-row"} group animate-in fade-in slide-in-from-bottom-2 duration-300`}>
                  <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 shadow-sm ${
                    m.role === "user" 
                      ? "bg-linear-to-br from-blue-600 to-blue-700 text-white" 
                      : "bg-white border border-slate-200 text-emerald-600"
                  }`}>
                    {m.role === "user" ? <User size={20}/> : <Bot size={20}/>}
                  </div>
                  
                  <div className={`flex flex-col gap-2 max-w-[85%] ${m.role === "user" ? "items-end" : "items-start"}`}>
                    <div className={`p-4 rounded-2xl text-[15px] leading-7 transition-all ${
                      m.role === "user" 
                        ? "bg-blue-600 text-white shadow-blue-100 shadow-lg rounded-tr-none" 
                        : "bg-white border border-slate-200 text-slate-800 shadow-sm rounded-tl-none hover:border-slate-300"
                    }`}>
                      {/* Markdown Rendering */}
                      <article className={`prose prose-sm max-w-none ${m.role === 'user' ? 'prose-invert text-white [&_p]:text-white' : 'prose-slate'}`}>
                        <div className="whitespace-pre-words break-words [&_p]:mb-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 [&_table]:border-collapse [&_table]:w-full [&_th]:border [&_th]:border-slate-300 [&_th]:p-2 [&_th]:bg-slate-50 [&_td]:border [&_td]:border-slate-300 [&_td]:p-2">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {m.parts?.[0]?.text}
                          </ReactMarkdown>
                        </div>
                      </article>
                    </div>
                    
                    {/* Bot Actions Area */}
                    {m.role === "assistant" && m.parts[0]?.text && (
                      <div className="flex items-center gap-1 ml-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button title="Hữu ích" className="p-1.5 text-slate-400 hover:text-emerald-600 hover:bg-emerald-50 rounded-md transition-all cursor-pointer"><ThumbsUp size={14}/></button>
                        <button title="Tạo lại" className="p-1.5 text-slate-400 hover:text-orange-600 hover:bg-orange-50 rounded-md transition-all cursor-pointer"><RefreshCw size={14}/></button>
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}

            {status === "streaming" && (
              <div className="flex gap-4 items-start animate-pulse">
                <div className="w-9 h-9 rounded-xl bg-white border border-emerald-100 text-emerald-500 flex items-center justify-center shadow-sm">
                  <Bot size={20}/>
                </div>
                <div className="bg-emerald-50/50 border border-emerald-100/50 p-4 rounded-2xl rounded-tl-none text-emerald-700/70 text-sm font-medium flex items-center gap-3">
                  <div className="flex gap-1">
                    <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-bounce [animation-delay:-0.3s]"></span>
                    <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-bounce [animation-delay:-0.15s]"></span>
                    <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-bounce"></span>
                  </div>
                  Đang trả lời...
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Floating Input Bar */}
        <footer className="p-6 md:p-10 bg-linear-to-t from-white via-white to-transparent">
          <form onSubmit={handleSend} className="max-w-3xl mx-auto">
            <div className="relative group shadow-2xl shadow-slate-200 rounded-4xl overflow-hidden border border-slate-200 focus-within:border-blue-400 focus-within:ring-4 focus-within:ring-blue-50 transition-all bg-white p-2">
              <div className="flex items-end">
                <textarea
                  rows={1}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault()
                      handleSend(e)
                    }
                  }}  
                  placeholder="Hỏi bất cứ điều gì về học vụ CTU..."
                  className="w-full resize-none p-3 pl-4 bg-transparent text-slate-800 outline-none text-[15px] min-h-13 max-h-48 scrollbar-hide"
                />
                <button
                  type="submit"
                  disabled={status === "streaming" || !input.trim()}
                  className={`mb-1 mr-1 p-3 rounded-2xl transition-all flex items-center justify-center cursor-pointer ${
                    status === "streaming" || !input.trim()
                      ? "bg-slate-50 text-slate-300 cursor-not-allowed"
                      : "bg-blue-600 text-white hover:bg-blue-700 shadow-lg shadow-blue-200 active:scale-95"
                  }`}
                >
                  {status === "streaming" ? <Loader2 className="animate-spin w-5 h-5"/> : <Send size={20} className="ml-0.5"/>}
                </button>
              </div>
            </div>
            <p className="text-[10px] text-center text-slate-400 mt-4 font-bold uppercase tracking-widest opacity-60">
            </p>
          </form>
        </footer>
      </main>
    </div>
  )
}