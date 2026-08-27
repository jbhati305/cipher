#!/usr/bin/env bash
# context-keeper: auto-inject context files into Claude sessions
EVENT="${1:-SessionStart}"

# Stop hook: remind to update context after real work (commits in last 2h)
if [ "$EVENT" = "Stop" ]; then
    if git log --since="2 hours ago" --oneline 2>/dev/null | grep -q .; then
        jq -n '{"systemMessage": "context-keeper: ask me to run context-keeper:update to save session context."}'
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
