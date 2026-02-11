#!/usr/bin/env python3
"""vibegrep: grep, but the search engine is an LLM."""
import sys, os, argparse, fnmatch, subprocess, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

MAX_CHARS, BINARY_BYTES = 20000, 8192  # ~8k tokens

PROMPT = "You are a semantic grep. Given files and a query, output ONLY the original lines that match.\n" \
  "- Match by meaning, not literal text\n- Copy lines exactly as they appear, preserving whitespace\n" \
  "- Output nothing else — no explanations, no line numbers, no markdown\n- If nothing matches, output nothing"

def env(k):
  v = os.environ.get(k)
  if not v: print(f"Error: missing required environment variable {k}\n  Set it with: export {k}=<value>", file=sys.stderr); sys.exit(2)
  return v

def is_binary(p):
  try: return b"\x00" in open(p, "rb").read(BINARY_BYTES)
  except: return True

def read_file(p):
  try: return p.read_text(errors="replace")
  except: return None

def gitignored(root):
  try:
    r = subprocess.run(["git", "-C", str(root), "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"], capture_output=True, text=True, timeout=5)
    return {str(root / l.rstrip("/")) for l in r.stdout.splitlines() if l.strip()}
  except: return set()

def _ok(p, ignored, glob_pat):
  return not p.name.startswith(".") and str(p).rstrip("/") not in ignored and str(p) not in ignored \
    and p.is_file() and (not glob_pat or fnmatch.fnmatch(p.name, glob_pat)) and not is_binary(p)

def collect_files(root, depth, glob_pat):
  root, ignored = Path(root).resolve(), gitignored(Path(root).resolve())
  files = [p for p in sorted(root.iterdir()) if _ok(p, ignored, glob_pat)]
  if depth > 1:
    for d in sorted(root.iterdir()):
      if d.is_dir() and not d.name.startswith(".") and str(d).rstrip("/") not in ignored:
        files += [p for p in sorted(d.iterdir()) if _ok(p, ignored, glob_pat)]
  return files

# Chunk: (label, content, line_offset) — line_offset for correct line numbering
def chunk_file(rel, content):
  """Split large files into MAX_CHARS chunks by line boundaries."""
  if len(content) <= MAX_CHARS: return [(rel, content, 0)]
  lines, chunks, cur, cur_len, start = content.splitlines(keepends=True), [], [], 0, 0
  for i, line in enumerate(lines):
    if cur_len + len(line) > MAX_CHARS and cur:
      chunks.append((f"{rel}[{start+1}:]", "".join(cur), start))
      cur, cur_len, start = [line], len(line), i
    else: cur.append(line); cur_len += len(line)
  if cur: chunks.append((f"{rel}[{start+1}:]" if start > 0 else rel, "".join(cur), start))
  return chunks

def pack_batches(files, root):
  batches, cur, cur_len = [], [], 0
  for f in files:
    content = read_file(f)
    if content is None: continue
    rel = str(f.relative_to(root))
    for label, text, offset in chunk_file(rel, content):
      size = len(text)
      if size > MAX_CHARS: batches.append([(label, text, offset)]); continue
      if cur_len + size > MAX_CHARS:
        if cur: batches.append(cur)
        cur, cur_len = [(label, text, offset)], size
      else: cur.append((label, text, offset)); cur_len += size
  if cur: batches.append(cur)
  return batches

def call_llm(query, batch, base_url, api_key, model):
  import httpx
  user_msg = f"Search query: {query}\n\n" + "\n".join(f"=== FILE: {l} ===\n{c}" for l, c, _ in batch)
  body = {"model": model, "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": user_msg}], "temperature": 0, "max_completion_tokens": 8192}
  headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
  for attempt in range(3):
    r = httpx.post(f"{base_url}/chat/completions", headers=headers, json=body, timeout=120)
    if r.status_code in (429, 502, 503, 504): time.sleep(2 ** attempt); continue
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    return (msg.get("content") or "").strip()
  r.raise_for_status()

def find_lines(content, offset, matched):
  """Find matched lines in content, returning (global_line_no, line_text)."""
  src, results, seen, idx = content.splitlines(), [], set(), 0
  for ml in matched:
    s = ml.strip()
    if not s: continue
    for search_range in [range(idx, len(src)), range(len(src))]:
      for i in search_range:
        gln = offset + i + 1  # global line number
        if src[i].strip() == s and gln not in seen:
          results.append((gln, src[i])); seen.add(gln); idx = i+1; break
      else: continue
      break
  return results

def rel_from_label(label):
  """Extract real file path from chunk label: 'file.py[42:]' → 'file.py'"""
  return label[:label.index("[")] if "[" in label else label

def match_results(output, batch):
  if not output or not output.strip(): return {}
  lines, results = output.splitlines(), {}
  for label, content, offset in batch:
    if m := find_lines(content, offset, lines):
      rel = rel_from_label(label)
      results.setdefault(rel, []).extend(m)
  # Sort by line number, dedup
  for rel in results:
    results[rel] = sorted(set(results[rel]))
  return results

def fmt_tty(results, printed):
  B, D, R = "\033[1m", "\033[2m", "\033[0m"
  for rel in sorted(results):
    if printed: print()
    printed = True
    print(f"{B}{rel}{R}")
    matches = results[rel]
    w, prev = len(str(max(n for n,_ in matches))), -2
    for n, line in matches:
      if prev >= 0 and n - prev > 1: print()
      print(f"{D}{n:>{w}}│{R} {line}"); prev = n
  return printed

def fmt_pipe(results):
  for rel in sorted(results):
    for n, line in results[rel]: print(f"{rel}:{n}:{line}")

def main():
  p = argparse.ArgumentParser(prog="vibegrep", description="grep, but the search engine is an LLM")
  p.add_argument("query"); p.add_argument("path", nargs="?", default=".")
  p.add_argument("--depth", type=int, default=1, choices=[1, 2])
  p.add_argument("-j", "--threads", type=int, default=10)
  p.add_argument("-g", "--glob", dest="glob_pat")
  p.add_argument("--model"); p.add_argument("--dry-run", action="store_true")
  args = p.parse_args()

  if not args.dry_run:
    api_key, base_url, model = env("VIBEGREP_API_KEY"), env("VIBEGREP_BASE_URL").rstrip("/"), args.model or env("VIBEGREP_MODEL")
  else:
    api_key, base_url = os.environ.get("VIBEGREP_API_KEY", ""), os.environ.get("VIBEGREP_BASE_URL", "")
    model = args.model or os.environ.get("VIBEGREP_MODEL", "unknown")

  root = Path(args.path).resolve()
  if not root.exists(): print(f"Error: path '{args.path}' does not exist", file=sys.stderr); sys.exit(2)

  files = collect_files(root, args.depth, args.glob_pat)
  if not files: print("No files to search", file=sys.stderr); sys.exit(1)

  batches = pack_batches(files, root)
  if args.dry_run:
    total = sum(sum(len(c) for _,c,_ in b) for b in batches)
    print(f"Would search {len(files)} files in {len(batches)} batches (~{total//4:,} tokens total)")
    oversized = [(i, b) for i, b in enumerate(batches) if sum(len(c) for _,c,_ in b) > MAX_CHARS]
    if oversized:
      print(f"  ⚠ {len(oversized)} oversized batches (may exceed context window):")
      for i, b in oversized: print(f"    Batch {i+1}: {', '.join(l for l,_,_ in b)} ({sum(len(c) for _,c,_ in b)//4:,} tokens)")
    sys.exit(0)

  is_tty, found, printed = sys.stdout.isatty(), False, False
  with ThreadPoolExecutor(max_workers=args.threads) as pool:
    futs = {pool.submit(call_llm, args.query, b, base_url, api_key, model): b for b in batches}
    for fut in as_completed(futs):
      try: output = fut.result()
      except Exception as e: print(f"Error searching {', '.join(l for l,_,_ in futs[fut])}: {e}", file=sys.stderr); continue
      results = match_results(output, futs[fut])
      if results:
        found = True
        printed = fmt_tty(results, printed) if is_tty else (fmt_pipe(results) or printed)
  sys.exit(0 if found else 1)
