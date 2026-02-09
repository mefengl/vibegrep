# llmgrep

grep, but the search engine is an LLM.

## Install

```bash
pip install llmgrep-cli
```

## Setup

```bash
export LLM_GREP_API_KEY=<your-api-key>
export LLM_GREP_BASE_URL=https://<openai-compatible-api>/v1
export LLM_GREP_MODEL=<a-fast-and-affordable-model>
```

## Usage

```bash
llmgrep "security vulnerabilities" src/
llmgrep "error handling" . -g "*.py"
llmgrep "authentication logic" src/ --depth 2 -j 5
```

### Options

```
QUERY                 search query (required)
PATH                  search path (default: .)
--depth 1|2           directory depth (default: 1)
-j NUM, --threads NUM concurrent requests (default: 10)
-g GLOB, --glob GLOB  file filter (e.g. '*.py')
--model MODEL         override LLM_GREP_MODEL
--dry-run             preview batching without calling API
```

### Output

TTY:
```
src/auth.py
 42│     password = request.form["password"]
 43│     db.execute(f"SELECT * FROM users WHERE pass='{password}'")

 67│     os.system(user_input)
```

Pipe:
```
src/auth.py:42:    password = request.form["password"]
src/auth.py:43:    db.execute(f"SELECT * FROM users WHERE pass='{password}'")
```

## License

MIT
