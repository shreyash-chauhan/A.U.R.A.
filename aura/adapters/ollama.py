import json
import urllib.error
import urllib.request
import logging
import time
from datetime import datetime

log = logging.getLogger(__name__)


class OllamaClient:
    """Local Ollama adapter. It provides no tools and accepts no executable output."""
    def __init__(self, base_url: str, model: str, timeout: int = 90,
                 keep_alive: str = "15m", num_ctx: int = 4096, num_predict: int = 256):
        self.url = base_url.rstrip("/") + "/api/chat"
        self.model, self.timeout = model, timeout
        self.keep_alive, self.num_ctx, self.num_predict = keep_alive, num_ctx, num_predict

    def generate(self, text: str, capabilities: list[dict]) -> str:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        compact_capabilities = []
        for item in capabilities:
            schema = item.get("arguments", {})
            required = set(schema.get("required", []))
            arguments = {}
            for name, rule in schema.get("properties", {}).items():
                details = {"type": rule.get("type", "value"), "required": name in required}
                if "enum" in rule: details["values"] = rule["enum"]
                if "minimum" in rule: details["minimum"] = rule["minimum"]
                if "maximum" in rule: details["maximum"] = rule["maximum"]
                arguments[name] = details
            compact_capabilities.append({
                "intent": item["intent"],
                "description": item["description"],
                "arguments": arguments,
                "example": item.get("examples", [])[0] if item.get("examples") else None,
            })
        response_schema = {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": [item["intent"] for item in capabilities] + ["clarify"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "arguments": {"type": "object"},
            },
            "required": ["intent", "confidence", "arguments"],
            "additionalProperties": False,
        }
        system = ("Return exactly one compact JSON object with keys intent, confidence, arguments. "
                  "Select only an intent from the supplied registered capabilities, or use the reserved intent clarify with arguments {question: string} when the request is ambiguous. "
                  "Never return commands, code, paths to executables, or extra keys. "
                  "When a category is ambiguous (for example, 'my browser'), ask which registered option rather than guessing. Application IDs are canonical; use the dynamically provided app ID and alias mapping. "
                  "For unsupported requests use intent fallback and arguments {}. "
                  "Use schedule_open_app when the user asks to open an app in the future, and create_reminder for reminder requests. "
                  "For an app launch requested in a relative delay (for example, 'in 10 seconds' or 'in 5 minutes'), set schedule_open_app.delay_seconds to the delay in whole seconds and omit datetime. For a clock time, set datetime and omit delay_seconds. "
                  "For explain_function, set function_id to the registered function ID the user is asking about. Use toggle_spotify for Spotify play/pause requests. "
                  "For set_timer, arguments.seconds is a duration in seconds. Convert explicit units accurately (5 minutes is 300 seconds). If the user gives a number without a duration unit, ask whether they mean seconds, minutes, or another unit; never assume seconds. "
                  "For create_reminder, use the user's reminder text and requested local date/time. Clear requests such as 'set a reminder for breakfast at 8 AM' are valid; if AM/PM or the date is genuinely unclear, ask a short clarification. "
                  "Use confidence 0.9 or higher for clear, direct requests whose arguments are explicit. "
                  "Omit optional arguments that the user did not specify. For reminder and schedule times use this local datetime as the reference: " + now + ". "
                  "Capability list: " + json.dumps(compact_capabilities, ensure_ascii=False, separators=(",", ":")))
        body = json.dumps({"model": self.model, "stream": False, "format": response_schema,
                           "think": False, "keep_alive": self.keep_alive,
                           "options": {"temperature": 0, "num_ctx": self.num_ctx,
                                       "num_predict": self.num_predict},
                           "messages": [{"role": "system", "content": system},
                                        {"role": "user", "content": text}]}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
        try:
            started = time.perf_counter()
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if log.isEnabledFor(logging.DEBUG):
                seconds = lambda key: round(payload.get(key, 0) / 1_000_000_000, 3)
                log.debug("Ollama %.2fs total; load %.2fs; prompt %.2fs (%s tokens); generation %.2fs (%s tokens)",
                          time.perf_counter()-started, seconds("load_duration"), seconds("prompt_eval_duration"),
                          payload.get("prompt_eval_count"), seconds("eval_duration"), payload.get("eval_count"))
            return payload["message"]["content"]
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
            raise RuntimeError("Ollama is unavailable") from exc
