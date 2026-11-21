# AGENTS.md

This repository is **cappus**, an Agent Skill that edits video into editable CapCut desktop drafts.

## The user wants a video edited

Read `skills/capcut-editor/SKILL.md` first and follow it. It says which scripts to run (all in
`skills/capcut-editor/scripts/`, plain Python CLIs), which references to read, and what to tell the
user at the end. Start with `python skills/capcut-editor/scripts/doctor.py` to check the machine.

The drafts are written to CapCut's local drafts folder, so this only works when you run on the same
computer as CapCut desktop. Look at the contact sheet images the scripts make before choosing cuts.

## You are changing cappus itself

- Tests: `python -m pytest -q tests` (slow, several minutes; most tests build real drafts).
- `CONTRIBUTING.md` has the conventions. Keep `SKILL.md`, `references/edit-spec.md`, the README and
  `docs/cara-pakai.md` (Indonesian guide) in step with what the scripts do.
- Anything about CapCut's draft format that you could not check in CapCut desktop is a guess: say so.
