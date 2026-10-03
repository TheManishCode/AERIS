# Palisade — monorepo

**Desktop fences for Wayland.** Development happens here; the four packages
below are published as four separate repositories.

Palisade exists because [PecoFence](https://github.com/DayuanJiang/PecoFence) —
the best open-source desktop organiser going — is Windows-only. It is ~105k
lines of Rust written directly against Win32, Direct2D, DirectComposition and
WebView2. There is no port. On Wayland the category was simply empty.

---

## The packages

| Directory | Published as | What it is |
| --- | --- | --- |
| `packages/palisade-core` | [palisade-core](https://github.com/PALISADE_OWNER/palisade-core) | The panel: layer-shell surface, cards, theme, config, CLI, IPC, module registry. Draws nothing on its own. |
| `packages/palisade-files` | [palisade-files](https://github.com/PALISADE_OWNER/palisade-files) | Folders, saved searches, and the in-panel renderer — images, video, Markdown, code, PDF. |
| `packages/palisade-dock` | [palisade-dock](https://github.com/PALISADE_OWNER/palisade-dock) | A real minimize for Hyprland, plus the docked taskbar. |
| `packages/palisade-apps` | [palisade-apps](https://github.com/PALISADE_OWNER/palisade-apps) | Installed applications, searchable and launchable. |

The three modules depend on core and on **nothing else** — not on each other.
Core depends on none of them. That rule is what makes any subset installable,
and it is the one thing to check before adding an import. See
[ARCHITECTURE.md](packages/palisade-core/ARCHITECTURE.md).

---

## Working here

```bash
packages/palisade-core/bin/palisade run     # dev daemon, all modules from source
packages/palisade-core/bin/palisade doctor  # what it loaded
```

The launcher puts every sibling `packages/palisade-*/src` on `PYTHONPATH` and
names them in `PALISADE_MODULES`, because a checkout has no `.dist-info` and
entry-point discovery would find nothing. After `git subtree split` the
siblings do not exist, the glob matches nothing, and installed modules are
found through their entry points as normal — one line serves both layouts.

Each suite runs from its own directory with no `PYTHONPATH` incantation:

```bash
for p in packages/palisade-*; do (cd "$p" && python3 -m pytest tests -q); done
```

## Shipping

```bash
python3 tools/gen-installers.py     # regenerate the three module install.sh
tools/split-repos.sh                # four local branches, nothing pushed
tools/split-repos.sh --push OWNER   # push each to github.com/OWNER/<name>
```

`git subtree split` is idempotent: re-run it and the branches move forward.
Note that it does not follow renames, and every package directory was created
in one restructuring commit — so each branch starts at that commit and grows
from there. Full history stays here. `git filter-repo --path-rename` is the
route if you want the pre-split commits carried across.

`CHANGELOG.md`, `SESSION_LOG.md` and `TODO.md` stay at this root and cover all
four packages; the split repositories carry their own `README.md` and
`LICENSE`.

## Licence

MIT. See [LICENSE](LICENSE).
