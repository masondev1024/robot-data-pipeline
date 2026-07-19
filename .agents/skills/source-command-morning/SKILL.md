---
name: "source-command-morning"
description: "오늘 작업 브리핑 (task-router 호출, 200자 이내 요약)"
---

# source-command-morning

Use this skill when the user asks to run the migrated source command `morning`.

## Command Template

`Agent` tool로 task-router subagent를 호출해서 오늘 작업을 브리핑해.

호출 파라미터:
- subagent_type: `task-router`
- description: "오늘 작업 브리핑"
- prompt: "오늘 작업 브리핑을 해줘. docs/plan/active.md의 P0/P1/P2 + 어제~오늘 git log + 미커밋 변경을 종합해서 200자 이내로."

받은 결과를 그대로 사용자에게 전달하고, 마지막에 한 줄로 "어떤 항목부터 시작할까요?"로 다음 액션을 묻는다.
