from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from avatar_service.core.command_router import CommandResolution
from avatar_service.core.script_normalizer import ScriptNormalizer, Segment
from avatar_service.core.state_controller import StateController
from avatar_service.models.enums import AvatarState, EventType, ModeType, ResultLevel
from avatar_service.models.schemas import (
    ModeSwitchRequest,
    OpeningBroadcastRequest,
    PPTScriptItem,
    ProjectIntroPayload,
    ResultEventItem,
    ResultStatusRequest,
    SlideBroadcastRequest,
)


@dataclass(slots=True)
class ScriptPlan:
    event_type: EventType
    mode: ModeType
    avatar_state: AvatarState
    slide_no: int | None
    subtitle: str
    segments: list[Segment]
    voice: str | None
    speed: str | float | None
    updates_current_slide: bool = False
    last_event_name: str | None = None
    is_intro: bool = False


class ScriptPlanner:
    """Build internal speech plans from structured requests."""

    def __init__(self, normalizer: ScriptNormalizer, state_controller: StateController) -> None:
        self.normalizer = normalizer
        self.state_controller = state_controller

    def plan_opening(self, request: OpeningBroadcastRequest) -> ScriptPlan:
        return self.plan_project_intro(
            ProjectIntroPayload(
                title=request.title,
                summary=request.summary,
                highlights=request.highlights,
                voice=request.voice,
                speed=request.speed,
            ),
            voice=request.voice,
            speed=request.speed,
        )

    def plan_project_intro(
        self,
        payload: ProjectIntroPayload,
        voice: str | None = None,
        speed: str | float | None = None,
    ) -> ScriptPlan:
        highlights = ""
        if payload.highlights:
            highlights = "本次重点包括：" + "；".join(item.strip() for item in payload.highlights if item.strip()) + "。"
        segments = self.normalizer.build_segments(
            self.normalizer.normalize_sentence(f"项目《{payload.title}》现在开始讲解"),
            self.normalizer.normalize_sentence(payload.summary),
            highlights,
        )
        return self._build_plan(
            event_type=EventType.OPENING_OVERVIEW,
            mode=ModeType.PROJECT_INTRO,
            avatar_state=AvatarState.SPEAKING,
            slide_no=None,
            segments=segments,
            voice=voice or payload.voice,
            speed=speed if speed is not None else payload.speed,
            is_intro=True,
        )

    def plan_slide(self, request: SlideBroadcastRequest) -> ScriptPlan:
        return self.plan_ppt_explain(
            PPTScriptItem(
                slide_no=request.slide_no,
                title=request.title,
                bullets=request.bullets,
                speaker_notes=request.speaker_notes,
                voice=request.voice,
                speed=request.speed,
            ),
            level="full",
            voice=request.voice,
            speed=request.speed,
        )

    def plan_ppt_explain(
        self,
        script: PPTScriptItem,
        level: Literal["full", "summary"],
        voice: str | None = None,
        speed: str | float | None = None,
    ) -> ScriptPlan:
        if level == "summary":
            summary = script.summary or self._derive_slide_summary(script)
            segments = self.normalizer.build_segments(
                self.normalizer.normalize_sentence(f"第{script.slide_no}页总结"),
                self.normalizer.normalize_sentence(summary),
            )
        else:
            title = f"本页标题是《{script.title}》。" if script.title else ""
            bullets = ""
            if script.bullets:
                bullets = "要点如下：" + "；".join(item.strip() for item in script.bullets if item.strip()) + "。"
            speaker_notes = ""
            if script.speaker_notes:
                speaker_notes = self.normalizer.normalize_sentence(f"补充说明：{script.speaker_notes.rstrip('。')}")
            segments = self.normalizer.build_segments(
                self.normalizer.normalize_sentence(f"现在讲解第{script.slide_no}页"),
                title,
                bullets,
                speaker_notes,
            )
        return self._build_plan(
            event_type=EventType.SLIDE_NARRATION,
            mode=ModeType.PPT_EXPLAIN,
            avatar_state=AvatarState.SPEAKING,
            slide_no=script.slide_no,
            segments=segments,
            voice=voice or script.voice,
            speed=speed if speed is not None else script.speed,
            updates_current_slide=True,
        )

    def plan_result(self, request: ResultStatusRequest) -> ScriptPlan:
        return self.plan_broadcast(
            ResultEventItem(
                event="legacy_result",
                result_level=request.result_level,
                summary=request.summary,
                details=request.details,
                next_action=request.next_action,
                slide_no=request.slide_no,
                voice=request.voice,
                speed=request.speed,
            ),
            voice=request.voice,
            speed=request.speed,
        )

    def plan_broadcast(
        self,
        event: ResultEventItem,
        voice: str | None = None,
        speed: str | float | None = None,
    ) -> ScriptPlan:
        level_text = {
            ResultLevel.SUCCESS: "当前结果状态为成功。",
            ResultLevel.WARNING: "当前结果状态为预警。",
            ResultLevel.ERROR: "当前结果状态为异常。",
            ResultLevel.INFO: "当前结果状态为信息更新。",
        }[event.result_level]
        details = ""
        if event.details:
            details = "详细信息：" + "；".join(item.strip() for item in event.details if item.strip()) + "。"
        next_action = ""
        if event.next_action:
            next_action = self.normalizer.normalize_sentence(f"建议下一步：{event.next_action.rstrip('。')}")
        segments = self.normalizer.build_segments(
            level_text,
            self.normalizer.normalize_sentence(event.summary),
            details,
            next_action,
        )
        return self._build_plan(
            event_type=EventType.RESULT_STATUS,
            mode=ModeType.RESULT_BROADCAST,
            avatar_state=AvatarState.SPEAKING,
            slide_no=event.slide_no,
            segments=segments,
            voice=voice or event.voice,
            speed=speed if speed is not None else event.speed,
            last_event_name=event.event,
        )

    def plan_mode_switch(self, request: ModeSwitchRequest, slide_no: int | None) -> ScriptPlan:
        mode_label = {
            ModeType.IDLE: "空闲",
            ModeType.PROJECT_INTRO: "项目开场",
            ModeType.PPT_EXPLAIN: "PPT讲解",
            ModeType.RESULT_BROADCAST: "结果播报",
            ModeType.INTERACTION: "指令交互",
            ModeType.PAUSED: "暂停",
        }[request.mode]
        reason = ""
        if request.reason:
            reason = self.normalizer.normalize_sentence(f"切换原因：{request.reason.rstrip('。')}")
        segments = self.normalizer.build_segments(
            f"已切换到{mode_label}模式。",
            reason,
        )
        return self._build_plan(
            event_type=EventType.MODE_SWITCH,
            mode=request.mode,
            avatar_state=self.state_controller.mode_switch_avatar_state(request.mode),
            slide_no=slide_no,
            segments=segments,
            voice=None,
            speed=request.speed,
        )

    def plan_command(self, resolution: CommandResolution, voice: str | None, speed: str | float | None) -> ScriptPlan:
        segments = self.normalizer.build_segments(resolution.subtitle)
        return self._build_plan(
            event_type=EventType.COMMAND_INTERACTION,
            mode=resolution.mode,
            avatar_state=resolution.avatar_state,
            slide_no=resolution.slide_no,
            segments=segments,
            voice=voice,
            speed=speed,
            updates_current_slide=resolution.updates_current_slide,
            last_event_name=resolution.last_event_name,
            is_intro=resolution.is_intro,
        )

    def _derive_slide_summary(self, script: PPTScriptItem) -> str:
        if script.summary:
            return script.summary
        if script.bullets:
            lead = "；".join(item.strip() for item in script.bullets[:2] if item.strip())
            if lead:
                return f"本页概括：{lead}"
        if script.title:
            return f"本页围绕《{script.title}》展开。"
        return f"第{script.slide_no}页内容已准备完成。"

    def _build_plan(
        self,
        event_type: EventType,
        mode: ModeType,
        avatar_state: AvatarState,
        slide_no: int | None,
        segments: list[Segment],
        voice: str | None,
        speed: str | float | None,
        updates_current_slide: bool = False,
        last_event_name: str | None = None,
        is_intro: bool = False,
    ) -> ScriptPlan:
        return ScriptPlan(
            event_type=event_type,
            mode=mode,
            avatar_state=avatar_state,
            slide_no=slide_no,
            subtitle=self.normalizer.build_subtitle(segments),
            segments=segments,
            voice=voice,
            speed=speed,
            updates_current_slide=updates_current_slide,
            last_event_name=last_event_name,
            is_intro=is_intro,
        )
