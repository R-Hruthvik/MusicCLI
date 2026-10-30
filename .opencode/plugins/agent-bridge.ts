import { type Plugin, tool } from "@opencode-ai/plugin";
import fs from "fs";
import path from "path";

export interface Finding {
  agentName: string;
  sessionID: string;
  setID: string | null;
  finding: string;
  severity: "low" | "medium" | "high" | "critical";
  evidencePaths: string[];
  filesChanged: string[];
  rawOutputPath: string | null;
  rawOutputText: string | null;
}

export interface TrackedSession {
  id: string;
  agentName: string | null;
  setID: string | null;
  status: "pending" | "running" | "completed" | "error";
  error: string | null;
  startedAt: number | null;
  completedAt: number | null;
  filesChanged: string[];
  outputPath: string | null;
}

export interface SessionMeta {
  sessionID: string;
  setID: string;
  agentName: string;
  outputPath: string;
}

function readOutputFile(outputPath: string | null): string | null {
  if (!outputPath) return null;
  try {
    const resolved = path.isAbsolute(outputPath)
      ? outputPath
      : path.resolve(process.cwd(), outputPath);
    if (fs.existsSync(resolved)) {
      return fs.readFileSync(resolved, "utf8");
    }
  } catch {
    // ignore read errors
  }
  return null;
}

function createBridgeState() {
  const sessions = new Map<string, TrackedSession>();
  const findings: Finding[] = [];
  const sessionMeta = new Map<string, SessionMeta>();

  function trackSession(id: string): TrackedSession {
    if (!sessions.has(id)) {
      sessions.set(id, {
        id,
        agentName: null,
        setID: null,
        status: "pending",
        error: null,
        startedAt: null,
        completedAt: null,
        filesChanged: [],
        outputPath: null,
      });
    }
    return sessions.get(id)!;
  }

  function handleEvent(event: Record<string, unknown>) {
    switch (event.type) {
      case "session.created": {
        const s = trackSession((event.properties as { info: { id: string } }).info.id);
        s.agentName = (event.properties as { info: { title?: string } }).info.title || null;
        s.startedAt = Date.now();
        break;
      }
      case "session.status": {
        const s = trackSession((event.properties as { sessionID: string }).sessionID);
        if ((event.properties as { status: { type: string } }).status.type === "idle") {
          s.status = "completed";
          s.completedAt = Date.now();
        }
        break;
      }
      case "session.error": {
        const props = event.properties as { sessionID?: string; error?: { type?: string } };
        if (!props.sessionID) break;
        const s = trackSession(props.sessionID);
        s.status = "error";
        s.error = props.error?.type || "Unknown error";
        s.completedAt = Date.now();
        break;
      }
      case "session.diff": {
        const props = event.properties as { sessionID: string; diff: { file: string }[] };
        const s = trackSession(props.sessionID);
        for (const d of props.diff) {
          if (!s.filesChanged.includes(d.file)) s.filesChanged.push(d.file);
        }
        break;
      }
      case "session.deleted": {
        const s = sessions.get((event.properties as { info: { id: string } }).info.id);
        if (s && s.status !== "completed" && s.status !== "error") {
          s.status = "completed";
          s.completedAt = Date.now();
        }
        break;
      }
      case "session.idle": {
        const s = trackSession((event.properties as { sessionID: string }).sessionID);
        if (s && s.status === "running") {
          s.status = "completed";
          s.completedAt = Date.now();
        }
        break;
      }
    }
  }

  function handleRegisterSession({ sessionID, setID, agentName, outputPath }: SessionMeta) {
    const s = trackSession(sessionID);
    s.agentName = agentName;
    s.setID = setID;
    s.outputPath = outputPath;
    sessionMeta.set(sessionID, { sessionID, setID, agentName, outputPath });
    return { output: `Registered ${agentName} -> ${outputPath}` };
  }

  async function handleGetResults() {
    const completed = [...sessions.values()];
    for (const s of completed) {
      if (s.outputPath && !findings.some((f) => f.sessionID === s.id)) {
        const rawText = readOutputFile(s.outputPath);
        findings.push({
          agentName: s.agentName,
          sessionID: s.id,
          setID: s.setID,
          finding: rawText ? "Raw findings written to output file" : "No output file found",
          severity: rawText ? "medium" : "high",
          evidencePaths: s.filesChanged,
          filesChanged: s.filesChanged,
          rawOutputPath: s.outputPath,
          rawOutputText: rawText,
        });
      }
    }

    const out = JSON.stringify(
      {
        summary: {
          totalAgents: completed.length,
          completed: completed.filter((s) => s.status === "completed").length,
          errors: completed.filter((s) => s.status === "error").length,
          totalFilesChanged: [...new Set(completed.flatMap((s) => s.filesChanged))].length,
          findingsWithOutput: findings.filter((f) => f.rawOutputText).length,
          findingsMissingOutput: findings.filter((f) => !f.rawOutputText).length,
        },
        sessions: completed.map((s) => ({
          id: s.id,
          agentName: s.agentName,
          setID: s.setID,
          status: s.status,
          error: s.error,
          filesChanged: s.filesChanged,
          outputPath: s.outputPath,
          duration: s.startedAt && s.completedAt ? s.completedAt - s.startedAt : null,
        })),
        findings,
      },
      null,
      2
    );

    return { output: out };
  }

  function handleClearResults() {
    sessions.clear();
    findings.length = 0;
    sessionMeta.clear();
    return { output: "Cleared" };
  }

  return {
    sessions,
    findings,
    sessionMeta,
    trackSession,
    handleEvent,
    handleRegisterSession,
    handleGetResults,
    handleClearResults,
  };
}

export const AgentBridgePlugin: Plugin = async () => {
  const state = createBridgeState();

  return {
    config: async () => ({
      provider: {},
      models: {},
    }),

    event: async ({ event }) => {
      state.handleEvent(event);
    },

    tool: {
      register_session: tool({
        description:
          "Register a subagent session's output path so get_results can read its findings file.",
        args: {
          sessionID: {
            description: "Subagent session ID",
            type: "string",
          },
          setID: {
            description: "Agent set ID",
            type: "string",
          },
          agentName: {
            description: "Agent name",
            type: "string",
          },
          outputPath: {
            description:
              "Output file path for this agent's findings, e.g. .opencode/agent-results/{set_id}/{agent_name}.md",
            type: "string",
          },
        },
        async execute({ sessionID, setID, agentName, outputPath }: {
          sessionID: string; setID: string; agentName: string; outputPath: string;
        }) {
          return state.handleRegisterSession({ sessionID, setID, agentName, outputPath });
        },
      }),

      get_results: tool({
        description:
          "Get compiled results from all tracked subagent sessions. Call after subagents finish to collect findings, file changes, session status, and raw output file contents.",
        args: {},
        async execute() {
          return state.handleGetResults();
        },
      }),

      clear_results: tool({
        description: "Clear all tracked session data and findings to start fresh.",
        args: {},
        async execute() {
          return state.handleClearResults();
        },
      }),
    },
  };
};

export default AgentBridgePlugin;
