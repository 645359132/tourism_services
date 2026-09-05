"""可替换的人脸闸机适配边界, 以及不处理生物信息的本地演示实现。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

FaceDemoSample = Literal["OWNER", "OTHER"]
FaceDemoResult = Literal["DEMO_MATCHED", "DEMO_NOT_MATCHED"]


@dataclass(frozen=True, slots=True)
class FaceGateVerification:
    """Provider 的最小输出; 安全边界字段由类型固定, 避免演示结果被误认为放行。"""

    result: FaceDemoResult
    provider: str = "demo_face_gate"
    is_demo: bool = True
    biometric_processed: bool = False
    admission_granted: bool = False


class FaceGateProvider(Protocol):
    """人脸核验 Provider 端口。

    生产适配器应接收设备侧生成的不透明采集会话引用, 而不是让业务 API
    保存照片或特征模板; 本 MVP 只传 OWNER/OTHER 演示样本。
    """

    async def verify(
        self,
        *,
        expected_subject_id: str,
        sample: FaceDemoSample,
    ) -> FaceGateVerification: ...


class DemoFaceGateProvider:
    """确定性的本地演示适配器; 不调用摄像头, 也不生成或保存生物特征。"""

    async def verify(
        self,
        *,
        expected_subject_id: str,
        sample: FaceDemoSample,
    ) -> FaceGateVerification:
        # expected_subject_id 保留在端口中用于未来对接实名主体; 演示实现只判断显式样本,
        # 不根据姓名、账号或图片“猜测”身份, 因而不会形成伪造的人脸识别能力。
        if not expected_subject_id.strip():
            raise ValueError("Expected subject id is required")
        return FaceGateVerification(
            result="DEMO_MATCHED" if sample == "OWNER" else "DEMO_NOT_MATCHED"
        )
