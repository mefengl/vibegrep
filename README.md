# vibegrep

grep, but the search engine is an LLM.

## Install

```bash
pip install vibegrep  # or: uvx vibegrep
```

## Setup

```bash
export VIBEGREP_API_KEY=<your-api-key>
export VIBEGREP_BASE_URL=https://<openai-compatible-api>/v1
export VIBEGREP_MODEL=<a-fast-and-affordable-model>
```

## Usage

```bash
vibegrep "security vulnerabilities" src/
vibegrep "error handling" . -g "*.py"
vibegrep "authentication logic" src/ --depth 2 -j 5
```

### Options

```
QUERY                 search query (required)
PATH                  search path (default: .)
--depth 1|2           directory depth (default: 1)
-j NUM, --threads NUM concurrent requests (default: 10)
-g GLOB, --glob GLOB  file filter (e.g. '*.py')
--model MODEL         override VIBEGREP_MODEL
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
