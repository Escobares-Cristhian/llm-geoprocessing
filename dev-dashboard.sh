#!/usr/bin/env bash
SESSION=geollm
HTOP_HEIGHT=10  # rows

# 1. Start fresh
tmux kill-session -t "$SESSION" 2>/dev/null
# Note: Adding -x and -y ensures the detached session isn't created 
# at a default small size (like 80x24), which would make the resize fail.
tmux new-session -d -s "$SESSION" -x "$(tput cols)" -y "$(tput lines)"

# 2. Setup Pane 0 (Top): htop
tmux send-keys -t "$SESSION":0.0 "export TERM=xterm-256color; htop" C-m

# 3. Create structure
# Split vertically (creates bottom pane)
tmux split-window -v -t "$SESSION":0.0
# Split the NEW bottom pane (0.1) horizontally
tmux split-window -h -t "$SESSION":0.1

# 4. Send commands to bottom panes
# Bottom-left: main app
tmux send-keys -t "$SESSION":0.1 \
  "xhost +local:; docker compose -f docker/compose.dev.yaml run --rm --build --env GEOLLM_LOG_LEVEL=DEBUG geollm python -m llm_geoprocessing.app.main" C-m

# Bottom-right: logs
tmux send-keys -t "$SESSION":0.2 \
  "docker compose -f docker/compose.dev.yaml logs --no-log-prefix -f gee" C-m

# 5. FIX: Apply layout and Enforce Height
# First, ensure the layout interprets pane 0 as the 'main' (top) pane
tmux select-layout -t "$SESSION":0 main-horizontal

# Then, explicitly force the resize of the top pane (0.0) to the variable height
tmux resize-pane -t "$SESSION":0.0 -y "$HTOP_HEIGHT"

# 6. Attach
tmux attach -t "$SESSION"
