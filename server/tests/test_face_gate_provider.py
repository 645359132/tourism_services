"""人脸闸机演示 Provider 的确定性和安全边界测试。"""

from __future__ import annotations

import pytest

from app.providers.gate import DemoFaceGateProvider


@pytest.mark.asyncio
async def test_demo_face_gate_uses_explicit_fixture_without_biometrics() -> None:
    provider = DemoFaceGateProvider()

    owner = await provider.verify(expected_subject_id="tourist-1", sample="OWNER")
    other = await provider.verify(expected_subject_id="tourist-1", sample="OTHER")

    assert owner.result == "DEMO_MATCHED"
    assert other.result == "DEMO_NOT_MATCHED"
    for result in (owner, other):
        assert result.provider == "demo_face_gate"
        assert result.is_demo is True
        assert result.biometric_processed is False
        assert result.admission_granted is False


@pytest.mark.asyncio
async def test_demo_face_gate_requires_an_expected_subject() -> None:
    with pytest.raises(ValueError, match="Expected subject id is required"):
        await DemoFaceGateProvider().verify(expected_subject_id=" ", sample="OWNER")
