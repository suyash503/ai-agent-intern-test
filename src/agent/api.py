from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .agent import SupportAgent

app = FastAPI(title="Aster & Row support agent")
agent = SupportAgent()

PAGE = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Aster &amp; Row support</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 720px; margin: 40px auto;">
<h2>Aster &amp; Row support agent</h2>
<div id="log"></div>
<form id="form" style="margin-top:16px;">
  <input id="message" style="width:78%;padding:8px;" autocomplete="off" placeholder="Ask about a policy or an order">
  <button style="padding:8px 16px;">Send</button>
</form>
<script>
const log = document.getElementById("log");
const sessionId = "web-" + Math.random().toString(36).slice(2, 10);
function line(who, text) {
  const block = document.createElement("p");
  block.innerHTML = "<b>" + who + ":</b> " + text.replace(/\\n/g, "<br>");
  log.appendChild(block);
}
document.getElementById("form").onsubmit = async (event) => {
  event.preventDefault();
  const field = document.getElementById("message");
  const message = field.value.trim();
  if (!message) return;
  field.value = "";
  line("you", message);
  const reply = await fetch("/chat", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({session_id: sessionId, message: message}),
  }).then((response) => response.json());
  let text = reply.answer;
  if (reply.sources.length) text += "<br><i>Sources: " + reply.sources.join(", ") + "</i>";
  if (reply.handoff) text += "<br><b>Recommended next step: a human specialist should take this over.</b>";
  line("agent", text);
};
</script>
</body>
</html>
"""


class ChatRequest(BaseModel):
    message: str
    session_id: str = "web"


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


@app.post("/chat")
def chat(request: ChatRequest):
    response = agent.ask(request.message, session_id=request.session_id)
    return {
        "answer": response.answer,
        "sources": response.sources,
        "handoff": response.handoff,
        "handoff_reason": response.handoff_reason,
        "trace_id": response.trace.get("trace_id"),
    }


def main():
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
