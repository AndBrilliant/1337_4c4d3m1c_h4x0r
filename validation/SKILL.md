---
name: validation
description: "Exercise a change through the real human-facing interface before calling it done: open the UI, run the CLI, curl the API. Config parsing, env vars, unit tests, and a running container are NOT validation."
whenToUse: Before reporting anything as done, fixed, or working.
---

# Validation Skill

## CRITICAL — ALWAYS INVOKE AFTER ANY CHANGE

Before reporting ANYTHING as "done," "fixed," or "working," you MUST validate
it through the actual human-facing interface. No exceptions.

## What validation means

**Validation = exercise the thing the way the user would.** Open a browser, log
in, click the buttons, type the text, observe the result. If it's a CLI tool,
run it and check the output. If it's an API, curl it and verify the response
body.

## What validation is NOT

- Checking that env vars are set
- Verifying config files parse
- Running unit tests
- Checking that a container is running
- Any check done from inside the server

Those are **pre-checks** — do them too, but they are NOT validation.

## The validation test

A proper validation test answers one question: **"If the user did this right now,
would it work?"**

To answer that, you must actually DO what the user would do:
1. Open the browser/page/GUI the user would use
2. Authenticate if needed
3. Exercise the feature
4. Observe the result
5. Report: what happened, what you saw, whether it worked

## Browser validation on ganymede — `gui-validate` ONLY

⛔ **Playwright, Puppeteer, Chrome MCP (`chrome_navigate`/`chrome_screenshot`),
and raw CDP/WebSocket scripting are BANNED on ganymede** — hard-blocked by a hook
in `~/.claude/settings.json`. Do not use any of them, even for a "quick check",
and do not work around the ban from Bash — that is the same violation with
different syntax.

The **ONLY** sanctioned browser method is `/home/Drew/bin/gui-validate`
(scratch Xvfb + real Chrome + `xdotool` + `import -window root`):

```bash
gui-validate start http://localhost:3080/login   # scratch Xvfb + Chrome, isolated profile
gui-validate shot /tmp/x.png                     # then Read the PNG inline
gui-validate click 799 523                       # xdotool click
gui-validate type 'some text'
gui-validate key Return
gui-validate open http://localhost:3080/c/new
gui-validate stop                                # ALWAYS tear down
```

It picks a free display above `:70` and launches Chrome through the
`/usr/local/bin/google-chrome` wrapper. Read the screenshot PNG with the Read
tool — it renders in context. Only report "done" after you have seen proof it
works.

### Three traps it exists to avoid (do not hand-roll this and rediscover them)

1. **`gnome-screenshot` ignores `$DISPLAY`.** It goes over the GNOME session bus
   and always captures the real console `:0`; pointed at a headless display it
   silently returns Drew's desktop, which reads as "my page didn't render." Use
   `import -window root` (what `gui-validate shot` does).
2. **Never validate on `:0` or `:99`.** `:0` is Drew's actual desktop (there is
   no `:1` on this box). `:99` is the Xvfb pvbatch uses for 2D report figures.
3. **Chrome needs `--password-store=basic`** or it hangs on every page load when
   the GNOME keyring is locked. `gui-validate` launches through the wrapper that
   injects this automatically.

## When to use this skill

Invoke after:
- Any config file change
- Any code change to a running service
- Any "fix" to a reported problem
- Before committing or reporting status

## Credentials — never embed secrets here

This file is read into model context and persisted in session history, so
**do NOT hardcode passwords in it.** Resolve credentials from files at
validation time:

- LibreChat test login: `/home/Drew/librechat/TEST_USER_CREDENTIALS.md` —
  **never use Drew's own account for automation.**
- LibreChat-comms credentials: `/home/Drew/librechat-comms/CREDENTIALS.md`.

Read the relevant file when you need it; do not paste secrets into prompts.

## If you cannot validate

If you cannot access the interface (no credentials, no browser, etc.), tell the
user explicitly: "I cannot validate this because [reason]. Here's what I did
verify, and here's what you should check." Never imply something works when you
haven't seen it work.
