# Contributing to cappus

Thank you for helping. This guide covers how to report problems, set up a development copy, and
get a change merged.

## Ways to contribute

- **Report a resource that no longer loads.** CapCut withdraws resources over time, and every
  report keeps drafts clean for everyone. Use the
  [resource issue form](https://github.com/nsudy-code/cappus/issues/new?template=resource-not-loading.yml).
- **Report a bug.** Use the [bug report form](https://github.com/nsudy-code/cappus/issues/new?template=bug-report.yml).
- **Improve the curated picks or the editing guidance** in `aliases.json`, `aliases_pro.json` or
  `references/editing-craft.md`.
- **Fix bugs or add features** in the scripts.

For a larger change, open an issue first so we can agree on the approach before you write code.

## Development setup

1. Fork the repository and clone your fork.
2. Install Python 3.9 or later, plus ffmpeg and ffprobe on your `PATH`.
3. Create a virtual environment and install the dependencies:

   ```bash
   python -m venv .venv
   ```

   ```bash
   python -m pip install -r skills/capcut-editor/requirements.txt
   ```

   Activate the environment first (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate`
   on macOS or Linux).
4. Link `skills/capcut-editor` into `~/.claude/skills/` as described in the README (Option B), so
   Claude Code uses your working copy. Remove any plugin install of cappus first.
5. Generate the demo media and check that both demos validate:

   ```bash
   python examples/make_test_media.py
   ```

   ```bash
   python skills/capcut-editor/scripts/build_draft.py examples/demo.json --check
   ```

   ```bash
   python skills/capcut-editor/scripts/build_draft.py examples/demo-pro.json --check --allow-pro
   ```

## Testing your change

There is no automated test suite yet. Before you open a pull request:

- Run both demo checks above. Each must report `"status": "valid ..."`.
- If your change affects what goes into a draft, build the demo, open it in CapCut, and play it
  through. Note your CapCut version (Settings > About) and operating system in the pull request.
- If you changed `SKILL.md` or a reference file, try a real request in a new Claude Code session
  and confirm that Claude follows the new instructions.

## Project conventions

- **Scripts** use only the standard library, `pycapcut` and `numpy`. They print JSON so that
  Claude can read the result, and they report all problems at once rather than stopping at the
  first.
- **`SKILL.md`** stays short and focused on the workflow. Put details in `references/`, and point
  to them from `SKILL.md`.
- **Documentation** is in English. `docs/cara-pakai.md` is the Indonesian user guide. If you change
  how users install or use cappus, update the README and, if you can, the Indonesian guide. If you
  cannot, say so in the pull request.

### Curated aliases

`aliases.json` (free resources) and `aliases_pro.json` (Pro resources) map a short English alias
to a catalog name, grouped by kind:

```json
"transition": {
  "white_flash": "White_Flash"
}
```

- Use lowercase `snake_case` that describes what the viewer sees, for example `film_burn`, not the
  literal translation of the internal name.
- Look up the catalog name with `catalog.py <kind> <keyword> --all`.
- Check that the resource loads before you add it (see the next section). Curated picks are what
  Claude reaches for first, so each one must work.

### The withdrawn-resource list

`unavailable.json` lists catalog items that CapCut no longer loads. The builder rejects them and
`catalog.py` hides them. Never edit this file by hand. Update it only from evidence collected with
`check_resources.py`:

1. Build probe drafts, for example all curated animations and fonts:

   ```bash
   python skills/capcut-editor/scripts/check_resources.py probe
   ```

   Large checks are split into several drafts named `cappus-check-1`, `cappus-check-2`, and so on.
2. In CapCut, open each probe draft in turn, play it through once, wait until nothing is
   downloading, and return to the home screen before opening the next one. CapCut only saves what
   it downloaded when you leave the editor.
3. Read the results and record them:

   ```bash
   python skills/capcut-editor/scripts/check_resources.py read cappus-check-1 cappus-check-2 --save
   ```

   `read` records a failure only when CapCut was demonstrably downloading that kind of resource
   in the draft. Anything it cannot confirm is listed under `not_confirmed` and not saved.
4. Commit `unavailable.json`, and include the CapCut version and operating system from the
   report's `seen_in` field in your pull request.

To check whether withdrawn items have come back, add `--recheck` to `probe`. Items that load again
are removed from the list.

## Pull requests

- Keep each pull request focused on one change.
- Write commit messages in the imperative mood ("Add ...", "Fix ..."), with a short summary line.
- Fill in the pull request template, including what you checked in CapCut.
- Do not commit generated media, drafts, virtual environments or personal paths. The
  `.gitignore` already covers the usual ones.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
