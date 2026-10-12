# The assistant says it is off

**Symptom.** The floating button opens, the header reads "Off", and a yellow
box gives a reason. Or an answer comes back red.

**Diagnosis.** The yellow box is the reason. `curl -s localhost:8000/api/assistant/status`
prints the same. Nothing is sent to anyone while it is off.

| Reason shown | Fix |
|---|---|
| No `GROQ_API_KEY` in `.env` | Sign in at console.groq.com, create an API key, and put it in `.env` as `GROQ_API_KEY`. Never put it in `.env.example` |
| Turn on Zero Data Retention | In the Groq console open Settings, then Data Controls, and turn on Zero Data Retention. Then add `EULERLAB_ASSISTANT_ZDR=1` to `.env`. The code cannot see the Groq setting; this line is your statement that you turned it on |
| Not an approved host | `config/llm.yaml` points `assistant` at a host whose data terms were not read. Point it back at `groq`, or read ADR-064 before adding a host to `chat.ALLOWED_HOSTS` |
| The free quota is used up | Wait a minute. OpenRouter's free models allow 20 requests a minute and 50 a day (1,000 a day once 10 credits have ever been bought). One question uses one to six requests |
| HTTP 401, Invalid API Key | The key is not a Groq key. Groq keys start with `gsk_`. A key starting `xai-` is from xAI (the Grok model), a different company. Seen 2026-10-12 |
| HTTP 403, error code 1010 | Cloudflare refusing Python's default user agent. Fixed 2026-10-12: `chat.USER_AGENT`. If it returns, that header was dropped |
| No zero-retention endpoint serves the model | The free model lost its zero-retention endpoint, so OpenRouter refused and nothing was sent on. Choose another under `openrouter-private` in `config/llm.yaml`. Research 073 says how the current one was found |
| No `OPENROUTER_API_KEY` in `.env` | Create a key at openrouter.ai and add it |
| Could not reach the host | No internet, or the name could not be looked up. Seen 2026-10-12 as `[Errno 8] nodename nor servname provided`; it cleared by itself. Check the connection and ask again |
| The API is not running | Start it: `make api` |
| HTTP 400 naming a tool | The model wrote a bad tool call. Ask again, or more simply. If it repeats, change `model` under `groq` in `config/llm.yaml` to `openai/gpt-oss-120b` |

After editing `.env`, restart the API so it reads the new values.

## The button is not on the screen

Seen 2026-10-12. The button was in the page but had no colour, size or
position: its styles use tokens (`--ink`, `--s5`) that exist only inside the
`.terminal` element, and it had been mounted in the root layout, outside it.
It now sits in `web/app/terminal/layout.tsx`. A new page outside `/terminal`
would need its own mount inside an element that defines those tokens.

## The question box fills the panel

Seen 2026-10-12. `web/app/globals.css` gives every `textarea` a 300px minimum
height and full width. `assistant.css` undoes each by name under
`.asst-panel`. A new form control in the panel needs the same care.

## Adding a model to the list

The panel's Model list is `config/llm.yaml`. Nothing else needs editing.

1. Add a block under `providers` with a `name`, `base_url`, `model` and
   `api_key_var`. Copy `openrouter-private` and change the `model` line to
   try another OpenRouter model with the same key.
2. Put the key in `.env` under the name in `api_key_var`. Restart the API.
3. Open the panel. The model is in the list. If it is greyed out, the words
   after it say why: `no key`, `host not approved`, `retention not confirmed`.

`host not approved` is deliberate. A key is not enough: the assistant sends
your numbers, so a new host (OpenAI, xAI, any other) is added to
`chat.ALLOWED_HOSTS` only after its data terms are read and recorded, as
research 073 did for Groq and OpenRouter. The list shows only that a model
passes the locks, not that it answers; no request is sent until you ask.

**Prevention.** `tests/test_assistant.py` pins the locks. The status route
never sends a probe, so opening the panel costs no quota.

**To switch it off:** remove `EULERLAB_ASSISTANT_ZDR` from `.env`.
