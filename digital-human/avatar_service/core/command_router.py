from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, status

from avatar_service.models.enums import AvatarState, CommandType, ModeType
from avatar_service.models.schemas import CommandRequest, SessionState


@dataclass(slots=True)
class CommandResolution:
    kind: Literal["project_intro", "ppt_explain", "broadcast", "mode_switch", "direct_speech"]
    command: CommandType
    mode: ModeType
    avatar_state: AvatarState
    slide_no: int | None = None
    subtitle: str = ""
    explain_level: Literal["full", "summary"] | None = None
    event_name: str | None = None
    target_mode: ModeType | None = None
    updates_current_slide: bool = False
    last_event_name: str | None = None
    is_intro: bool = False
    command_family: Literal["official", "compat"] = "official"


class CommandRouter:
    """Resolve fixed commands into deterministic command actions."""

    def route(self, session: SessionState, request: CommandRequest) -> CommandResolution:
        if request.command == CommandType.PROJECT_INTRO:
            return CommandResolution(
                kind="project_intro",
                command=request.command,
                mode=ModeType.PROJECT_INTRO,
                avatar_state=AvatarState.SPEAKING,
                is_intro=True,
                command_family="official",
            )

        if request.command == CommandType.REPLAY_INTRO:
            if session.last_intro_subtitle:
                return CommandResolution(
                    kind="direct_speech",
                    command=request.command,
                    mode=ModeType.PROJECT_INTRO,
                    avatar_state=AvatarState.SPEAKING,
                    subtitle=session.last_intro_subtitle,
                    is_intro=True,
                    command_family="official",
                )
            return CommandResolution(
                kind="project_intro",
                command=request.command,
                mode=ModeType.PROJECT_INTRO,
                avatar_state=AvatarState.SPEAKING,
                is_intro=True,
                command_family="official",
            )

        if request.command == CommandType.EXPLAIN_CURRENT_SLIDE:
            slide_no = self._resolve_slide_no(session, request)
            return CommandResolution(
                kind="ppt_explain",
                command=request.command,
                mode=ModeType.PPT_EXPLAIN,
                avatar_state=AvatarState.SPEAKING,
                slide_no=slide_no,
                explain_level="full",
                updates_current_slide=True,
                command_family="official",
            )

        if request.command == CommandType.SUMMARIZE_CURRENT_SLIDE:
            slide_no = self._resolve_slide_no(session, request)
            return CommandResolution(
                kind="ppt_explain",
                command=request.command,
                mode=ModeType.PPT_EXPLAIN,
                avatar_state=AvatarState.SPEAKING,
                slide_no=slide_no,
                explain_level="summary",
                updates_current_slide=True,
                command_family="official",
            )

        if request.command == CommandType.BROADCAST_EVENT:
            event_name = request.effective_event
            if not event_name:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="broadcast_event requires params.event.",
                )
            return CommandResolution(
                kind="broadcast",
                command=request.command,
                mode=ModeType.RESULT_BROADCAST,
                avatar_state=AvatarState.SPEAKING,
                event_name=event_name,
                last_event_name=event_name,
                command_family="official",
            )

        if request.command == CommandType.SWITCH_MODE:
            try:
                target_mode = request.effective_mode
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            if target_mode is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="switch_mode requires params.mode.",
                )
            avatar_state = AvatarState.PAUSED if target_mode == ModeType.PAUSED else AvatarState.AWAITING_COMMAND
            if target_mode in {ModeType.PROJECT_INTRO, ModeType.PPT_EXPLAIN, ModeType.RESULT_BROADCAST}:
                avatar_state = AvatarState.SPEAKING
            if target_mode == ModeType.IDLE:
                avatar_state = AvatarState.IDLE
            return CommandResolution(
                kind="mode_switch",
                command=request.command,
                mode=target_mode,
                avatar_state=avatar_state,
                target_mode=target_mode,
                slide_no=session.current_slide_no,
                command_family="official",
            )

        if request.command == CommandType.REPEAT_LAST:
            if not session.last_subtitle:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No previous subtitle available for repeat_last.",
                )
            return CommandResolution(
                kind="direct_speech",
                command=request.command,
                mode=session.current_mode,
                avatar_state=AvatarState.SPEAKING,
                slide_no=session.current_slide_no,
                subtitle=session.last_subtitle,
                command_family="compat",
            )

        if request.command == CommandType.PAUSE:
            return CommandResolution(
                kind="direct_speech",
                command=request.command,
                mode=ModeType.PAUSED,
                avatar_state=AvatarState.PAUSED,
                slide_no=session.current_slide_no,
                subtitle="已暂停当前播报。",
                command_family="compat",
            )

        if request.command == CommandType.RESUME:
            resumed_mode = session.previous_mode or session.current_mode or ModeType.PPT_EXPLAIN
            if resumed_mode == ModeType.PAUSED:
                resumed_mode = ModeType.PPT_EXPLAIN
            return CommandResolution(
                kind="direct_speech",
                command=request.command,
                mode=resumed_mode,
                avatar_state=AvatarState.SPEAKING,
                slide_no=session.current_slide_no,
                subtitle="已恢复播报。",
                command_family="compat",
            )

        base_slide = request.effective_slide_no or session.current_slide_no or 1
        if request.command == CommandType.NEXT_SLIDE:
            slide_no = base_slide + (0 if request.effective_slide_no else 1)
            return CommandResolution(
                kind="direct_speech",
                command=request.command,
                mode=ModeType.INTERACTION,
                avatar_state=AvatarState.AWAITING_COMMAND,
                slide_no=slide_no,
                subtitle=f"已切换到第{slide_no}页，请准备当前页讲解内容。",
                updates_current_slide=True,
                command_family="compat",
            )

        if request.command == CommandType.PREVIOUS_SLIDE:
            slide_no = request.effective_slide_no or max(1, base_slide - 1)
            return CommandResolution(
                kind="direct_speech",
                command=request.command,
                mode=ModeType.INTERACTION,
                avatar_state=AvatarState.AWAITING_COMMAND,
                slide_no=slide_no,
                subtitle=f"已切换到第{slide_no}页，请准备当前页讲解内容。",
                updates_current_slide=True,
                command_family="compat",
            )

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported command.")

    def _resolve_slide_no(self, session: SessionState, request: CommandRequest) -> int:
        slide_no = request.effective_slide_no or session.current_slide_no
        if slide_no is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{request.command.value} requires params.slide_no or session.current_slide_no.",
            )
        return slide_no
