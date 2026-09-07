# Commands

| Command | What it does |
| --- | --- |
| `paratext run -p <project>` | Extract **and** package in one step (the common path) |
| `paratext extract -p <project>` | Run the model, write JSONL only |
| `paratext package <jsonl>` | Re-package an existing JSONL (no model calls) |
| `paratext review [dir]` | Launch the review UI (default: `./review`) |
| `paratext export -p <project>` | Export a reviewed round (`--format hf`/`marc`/`dc`) |
| `paratext inspect [-p <project>]` | Show what an installed project does |
| `paratext new [name]` | Scaffold a new project package |
| `paratext config [--show]` | Open `paratext.toml`; `--show` prints resolved defaults |
| `paratext sample` | Symlink a random image subset out of a nested tree |
| `paratext carbon` | Show current grid carbon/renewables |
| `paratext guide` | Print the agent guide |
| `paratext skill` | Installs a paratext skill for your coding agent |

Run `paratext <command> -h` for that command's flags.

