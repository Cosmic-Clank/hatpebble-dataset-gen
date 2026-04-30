"use client";

import React, { useState, useRef } from "react";

const API_URL = (process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000").replace(/^ws/, "http");

interface AIResponse {
  answer: string;
  tools_used: string[];
}

type Status = "idle" | "loading" | "done" | "error";

const EXAMPLE_QUESTIONS = [
  "What was the average battery SOC over the last 3 days?",
  "Which day had the highest spike in active power in load group 1?",
  "How many critical alerts were there this week?",
  "What is the current trend in load 2 power consumption today?",
  "Were there any sustained anomalies on the battery voltage this week?",
  "Compare the peak active power between load groups 1, 2, and 3 today.",
];

const TOOL_LABELS: Record<string, string> = {
  query_sensor_data:  "Sensor Data",
  query_alert_data:   "Alerts",
  query_anomaly_data: "Anomalies",
};

const TOOL_COLORS: Record<string, string> = {
  query_sensor_data:  "#3b82f6",
  query_alert_data:   "#ef4444",
  query_anomaly_data: "#a855f7",
};

function ToolBadge({ name }: { name: string }) {
  const color = TOOL_COLORS[name] ?? "#64748b";
  return (
    <span
      className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border"
      style={{ color, borderColor: `${color}40`, backgroundColor: `${color}15` }}
    >
      {TOOL_LABELS[name] ?? name}
    </span>
  );
}

export default function AIInsightsPage() {
  const [question,  setQuestion]  = useState("");
  const [status,    setStatus]    = useState<Status>("idle");
  const [answer,    setAnswer]    = useState<string | null>(null);
  const [toolsUsed, setToolsUsed] = useState<string[]>([]);
  const [error,     setError]     = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  async function submit(q: string) {
    const trimmed = q.trim();
    if (!trimmed || status === "loading") return;
    setStatus("loading");
    setAnswer(null);
    setError(null);
    setToolsUsed([]);

    try {
      const res = await fetch(`${API_URL}/api/ai/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error((detail as { detail?: string })?.detail ?? `HTTP ${res.status}`);
      }
      const data: AIResponse = await res.json();
      setAnswer(data.answer);
      setToolsUsed(data.tools_used ?? []);
      setStatus("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
      setStatus("error");
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit(question);
    }
  }

  function useExample(q: string) {
    setQuestion(q);
    textareaRef.current?.focus();
  }

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold">AI Insights</h1>
        <p className="text-xs text-muted mt-0.5">
          Ask a natural language question about your energy data. The AI fetches and analyses the relevant records automatically.
        </p>
      </div>

      {/* Example chips */}
      <div className="flex flex-col gap-2">
        <span className="text-[10px] uppercase tracking-widest text-muted font-semibold">Example questions</span>
        <div className="flex flex-wrap gap-2">
          {EXAMPLE_QUESTIONS.map((q) => (
            <button
              key={q}
              onClick={() => useExample(q)}
              className="px-3 py-1.5 rounded-full text-[11px] border border-card-border text-muted
                         hover:text-foreground hover:border-accent-purple/50 hover:bg-accent-purple/5
                         transition-all text-left"
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      {/* Input card */}
      <div className="bg-card border border-card-border rounded-xl p-4 flex flex-col gap-3">
        <textarea
          ref={textareaRef}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything about your energy data… (Enter to submit, Shift+Enter for new line)"
          rows={3}
          className="w-full bg-background border border-card-border rounded-lg px-4 py-3 text-sm
                     text-foreground placeholder:text-muted resize-none focus:outline-none
                     focus:border-accent-purple transition-colors"
        />
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-muted">
            Press{" "}
            <kbd className="px-1.5 py-0.5 rounded border border-card-border font-mono text-[10px]">Enter</kbd>
            {" "}to ask,{" "}
            <kbd className="px-1.5 py-0.5 rounded border border-card-border font-mono text-[10px]">Shift+Enter</kbd>
            {" "}for a new line
          </span>
          <button
            onClick={() => submit(question)}
            disabled={!question.trim() || status === "loading"}
            className="flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold
                       bg-accent-purple text-white hover:opacity-90 disabled:opacity-40 transition-all"
          >
            {status === "loading" ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Thinking…
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                Ask AI
              </>
            )}
          </button>
        </div>
      </div>

      {/* Loading skeleton */}
      {status === "loading" && (
        <div className="bg-card border border-card-border rounded-xl p-5 flex flex-col gap-3">
          <div className="flex items-center gap-2 text-xs text-muted">
            <div className="w-3.5 h-3.5 border-2 border-accent-purple border-t-transparent rounded-full animate-spin" />
            Fetching and analysing data…
          </div>
          <div className="space-y-2">
            <div className="h-3 bg-card-border rounded animate-pulse w-3/4" />
            <div className="h-3 bg-card-border rounded animate-pulse w-full" />
            <div className="h-3 bg-card-border rounded animate-pulse w-5/6" />
            <div className="h-3 bg-card-border rounded animate-pulse w-2/3" />
          </div>
        </div>
      )}

      {/* Error */}
      {status === "error" && error && (
        <div className="bg-accent-red/10 border border-accent-red/30 rounded-xl px-4 py-3 text-sm text-accent-red">
          {error}
        </div>
      )}

      {/* Answer */}
      {status === "done" && answer && (
        <div className="bg-card border border-card-border rounded-xl p-5 flex flex-col gap-4">
          {toolsUsed.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] text-muted uppercase tracking-wider">Data sources queried:</span>
              {[...new Set(toolsUsed)].map((t) => (
                <ToolBadge key={t} name={t} />
              ))}
            </div>
          )}
          <div className="text-sm text-foreground leading-relaxed whitespace-pre-wrap">
            {answer}
          </div>
          <div className="pt-2 border-t border-card-border text-[10px] text-muted italic">
            Query: &ldquo;{question}&rdquo;
          </div>
        </div>
      )}

      {/* Idle empty state */}
      {status === "idle" && (
        <div className="bg-card border border-card-border rounded-xl p-8 flex flex-col items-center gap-3 text-center">
          <div className="w-12 h-12 rounded-full bg-accent-purple/10 flex items-center justify-center">
            <svg className="w-6 h-6 text-accent-purple" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold">Ask a question to get started</p>
            <p className="text-xs text-muted mt-1">
              Click an example above or type your own question about battery, load groups, alerts, or anomalies.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
