# CLI Contract

Errors → stderr, exit 1 (usage errors exit 2). Existing `capture`, `list`, `show` output formats are unchanged outside initialized repos.

| Command | Behavior |
|---|---|
| `bugcap setup [--yes]` | Print detected backend, or recommendation. If none & package manager found: prompt `Install <tool>? [y/N]` (skipped with `--yes`; non-TTY without `--yes` prints the command instead). No package manager: print manual guidance. Exit 0 when a backend exists/installed, 1 otherwise. |
| `bugcap capture [--title] [--note] [--tag]... [--image PATH]` | `--image` imports instead of launching a backend. In an initialized repo adds repo tag + `repo`. |
| `bugcap init [--tag T] [--github owner/repo] [--images-repo owner/repo]` | Writes `.bugcap.toml` at git root (else cwd). Existing file: refuses unless `--force`. |
| `bugcap list [--all]` | In repo: only `repo == current`. Outside or `--all`: everything (current format). |
| `bugcap show ID` | Unchanged (+ prints `repo`). |
| `bugcap edit ID [--title] [--note] [--status]` | At least one flag required. |
| `bugcap tag ID add\|remove TAG...` | Idempotent; prints what changed. |
| `bugcap attach ID [--image PATH]` | Capture (or import) and append image. |
| `bugcap github pull [--repo SLUG] [--label L]... [--limit N=30] [--ask]` | Slug from flag, else `.bugcap.toml`. Prints `created/updated/unchanged` counts. `--ask`: per issue `Add a screenshot? [y/N/path]`. |
| `bugcap sync ID --to github [--repo SLUG] [--images-repo SLUG] [--images-path DIR] [--images-branch B] [--yes]` | Per R2/R4. Prints issue URL and committed image permalinks. |
| `bugcap mcp-serve` | stdio MCP server; stdout reserved for protocol. |

Error messages: gh missing → "GitHub CLI (`gh`) not found. Install: <per-OS hint>"; unauthenticated → "`gh` is not logged in. Run `gh auth login`."
