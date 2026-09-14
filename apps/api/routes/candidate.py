from fastapi import APIRouter, HTTPException
from packages.candidate_profile.profile import CandidateProfileLoader

router = APIRouter(prefix="/api/candidate", tags=["Candidate Profile"])


@router.get("/profile")
async def get_profile():
    try:
        profile = CandidateProfileLoader.get()
        return profile.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/profile")
async def update_profile(data: dict):
    try:
        updated_profile = CandidateProfileLoader.save(data)
        return {
            "status": "success",
            "message": "Candidate profile updated and saved to config/candidate-profile.yaml",
            "profile": updated_profile.model_dump(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to update profile: {str(e)}")
