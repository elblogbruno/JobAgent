import pytest
from packages.candidate_profile.answer_vault import CandidateAnswerVault
from packages.candidate_profile.profile import CandidateProfileLoader


@pytest.mark.asyncio
async def test_resolve_eu_authorization():
    profile = CandidateProfileLoader.get()
    vault = CandidateAnswerVault()

    # Question on EU right to work
    q1 = "Are you legally authorized to work in Spain / European Union?"
    answer, confidence, key = await vault.resolve(q1, profile)
    assert answer is True
    assert confidence >= 0.95
    assert key == "authorized_to_work_eu"


@pytest.mark.asyncio
async def test_resolve_eu_sponsorship():
    profile = CandidateProfileLoader.get()
    vault = CandidateAnswerVault()

    q2 = "Will you now or in the future require visa sponsorship in Europe?"
    answer, confidence, key = await vault.resolve(q2, profile)
    assert answer is False
    assert confidence >= 0.95
    assert key == "requires_sponsorship_eu"


@pytest.mark.asyncio
async def test_resolve_unknown_question():
    profile = CandidateProfileLoader.get()
    vault = CandidateAnswerVault()

    q3 = "What is your secret favorite dessert?"
    answer, confidence, key = await vault.resolve(q3, profile)
    assert answer is None
    assert confidence == 0.0
    assert key == ""
