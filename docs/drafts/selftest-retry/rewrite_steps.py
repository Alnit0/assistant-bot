"""Turn every `async with h.step(...):` into `async for attempt in h.step(...):` / `async with attempt:`,
the body indented four more. Refuses a body with a string over several lines (indenting would change it)."""
import ast
import sys
from pathlib import Path

for name in sys.argv[1:]:
    p = Path(name)
    raw = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    lines = text.split("\n")
    tree = ast.parse(text)
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncWith) and len(node.items) == 1 and ast.unparse(node.items[0].context_expr).startswith("h.step(") and node.items[0].optional_vars is None:
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Constant, ast.JoinedStr)) and sub.lineno != sub.end_lineno:
                    raise SystemExit(f"{name}:{sub.lineno}: a string over several lines in a step")
                if isinstance(sub, (ast.Break, ast.Continue)):
                    raise SystemExit(f"{name}:{sub.lineno}: break or continue in a step")
            sites.append((node.lineno, node.body[0].lineno, node.end_lineno))
    # Innermost last does not matter: steps are never nested; work from the bottom up
    for head, first, last in sorted(sites, reverse=True):
        for at in range(first - 1, last):
            if lines[at].strip():
                lines[at] = "    " + lines[at]
        line = lines[head - 1]
        indent = line[: len(line) - len(line.lstrip())]
        assert line.lstrip().startswith("async with h.step(") and line.rstrip().endswith("):"), (name, head, line)
        lines[head - 1] = line.replace("async with h.step(", "async for attempt in h.step(", 1)
        lines.insert(head, f"{indent}    async with attempt:")
    out = "\n".join(lines)
    ast.parse(out)
    p.write_bytes((out.replace("\n", "\r\n") if crlf else out).encode("utf-8"))
    print(name, len(sites))
