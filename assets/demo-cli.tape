Output assets/demo-cli.gif

Set Shell "zsh"
Set FontSize 14
Set Width 1000
Set Height 640
Set Padding 12
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms

# --- hidden setup: isolated HOME, real looper binary on PATH ---
Hide
Type "export HOME=/tmp/looper-demo && rm -rf $HOME && mkdir -p $HOME/.looper"
Enter
Type "export PATH=/Users/amitprasad/.local/bin:$PATH"
Enter
Type "looper install >/dev/null 2>&1"
Enter
Type "clear"
Enter
Show

# --- capture loops (as if Claude created them; here via the CLI) ---
Sleep 600ms
Type "looper add check-deploys 30m --prompt 'Check deploy status on main; report any failures.'"
Sleep 400ms
Enter
Sleep 1.2s

Type "looper add morning-brief '0 9 * * 1-5' --prompt 'Summarize overnight PRs, CI and alerts; slack me a brief.'"
Sleep 400ms
Enter
Sleep 1.2s

# --- the durable registry ---
Type "looper list"
Sleep 400ms
Enter
Sleep 3s

# --- pause one ---
Type "looper pause morning-brief"
Sleep 400ms
Enter
Sleep 1.5s

# --- interactive TUI ---
Type "looper tui"
Sleep 400ms
Enter
Sleep 2s

Down
Sleep 1.2s
Up
Sleep 1.2s

# toggle status
Type "t"
Sleep 1.5s

# quit
Type "q"
Sleep 800ms
