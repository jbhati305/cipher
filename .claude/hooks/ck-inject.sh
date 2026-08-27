#!/usr/bin/env bash
# context-keeper: auto-inject context files into Claude sessions
EVENT="${1:-SessionStart}"

# Stop hook: on a real 2-hour cadence, force an automatic context-keeper
# update instead of just reminding the user. A state file (outside the
# tracked context/ dir, so it never shows up as a commit-worthy diff) records
# when the last auto-update fired, so this only forces a stop-block once per
# 2-hour window rather than on every single Stop event while the window
# holds.
if [ "$EVENT" = "Stop" ]; then
    CTX=".claude/context"
    if [ -d "$CTX" ]; then
        STATE_FILE=".claude/state/last-auto-update"
        NOW=$(date +%s)
        LAST=0
        [ -f "$STATE_FILE" ] && LAST=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
        ELAPSED=$((NOW - LAST))
        if [ "$ELAPSED" -ge 7200 ]; then
            mkdir -p "$(dirname "$STATE_FILE")"
            echo "$NOW" > "$STATE_FILE"
            jq -n '{"decision":"block","reason":"context-keeper: 2+ hours have passed since the last automatic context update. Autonomously invoke the context-keeper:update skill now (do not ask the user first) to capture recent changes, decisions, and failed attempts into .claude/context/*.md. Once done, continue normally."}'
            exit 0
        fi
    fi
    exit 0
fi

CTX=".claude/context"
[ -d "$CTX" ] || exit 0

CONTENT=""
for f in "$CTX"/*.md; do
    [ -f "$f" ] || continue
    CONTENT="${CONTENT}--- $(basename "$f") ---
$(cat "$f")

"
done

[ -z "$CONTENT" ] && exit 0

if [ "$EVENT" = "PreCompact" ]; then
    jq -n --arg content "$CONTENT" \
        '{"hookSpecificOutput":{"hookEventName":"PreCompact","additionalContext":("IMPORTANT: Invoke context-keeper:compact before compacting this conversation to update and prune context files.\n\nCurrent context files:\n\n"+$content)}}'
else
    jq -n --arg content "$CONTENT" \
        '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":("context-keeper context:\n\n"+$content)}}'
fi
