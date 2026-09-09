from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


class JsonPatchOperation(BaseModel):
    op: Literal["add", "remove", "replace", "move", "copy", "test"]
    path: str
    value: Optional[Any] = None
    from_: Optional[str] = Field(default=None, alias="from")

    model_config = {"populate_by_name": True}


class ResumeListItem(BaseModel):
    id: str
    name: str
    slug: str
    tags: List[str] = Field(default_factory=list)
    locked: bool = False
    isPublic: bool = False
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class ResumeWorkItem(BaseModel):
    id: Optional[str] = None
    company: str
    position: str
    location: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    current: bool = False
    summary: Optional[str] = None
    url: Optional[str] = None


class ResumeSkillItem(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    level: Optional[int] = None
    keywords: List[str] = Field(default_factory=list)


class ResumeProjectItem(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    url: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    startDate: Optional[str] = None
    endDate: Optional[str] = None


class ResumeBasics(BaseModel):
    name: str
    headline: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    url: Optional[str] = None


class ResumeData(BaseModel):
    basics: ResumeBasics
    sections: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResumeDetail(BaseModel):
    id: str
    name: str
    slug: str
    tags: List[str] = Field(default_factory=list)
    locked: bool = False
    data: ResumeData
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class ResumeDuplicateRequest(BaseModel):
    name: str
    slug: str
    tags: List[str] = Field(default_factory=list)


class ResumePatchRequest(BaseModel):
    operations: List[JsonPatchOperation]
    expectedUpdatedAt: Optional[datetime] = None


class ApplicationContact(BaseModel):
    name: str
    role: str = ""
    type: str = ""


class ApplicationCreateRequest(BaseModel):
    company: str
    role: str
    location: Optional[str] = None
    salary: Optional[str] = None
    source: Optional[str] = None
    sourceUrl: Optional[str] = None
    jobDescription: Optional[str] = None
    notes: Optional[str] = None
    resumeId: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    status: Literal["saved", "applied", "screening", "interview", "offer", "rejected"] = "saved"
    followUpAt: Optional[datetime] = None
    followUpNote: Optional[str] = None
    contacts: List[ApplicationContact] = Field(default_factory=list)
    stageEnteredAt: Optional[str] = None


class ApplicationUpdateRequest(BaseModel):
    company: Optional[str] = None
    role: Optional[str] = None
    location: Optional[str] = None
    salary: Optional[str] = None
    source: Optional[str] = None
    sourceUrl: Optional[str] = None
    jobDescription: Optional[str] = None
    notes: Optional[str] = None
    resumeId: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[Literal["saved", "applied", "screening", "interview", "offer", "rejected"]] = None
    followUpAt: Optional[datetime] = None
    followUpNote: Optional[str] = None
    contacts: Optional[List[ApplicationContact]] = None
    stageEnteredAt: Optional[str] = None


class ApplicationTimelineEntry(BaseModel):
    id: str
    type: str
    date: str
    note: Optional[str] = None
    stage: Optional[str] = None


class ApplicationResponse(BaseModel):
    id: str
    company: str
    role: str
    location: Optional[str] = None
    salary: Optional[str] = None
    source: Optional[str] = None
    sourceUrl: Optional[str] = None
    jobDescription: Optional[str] = None
    notes: Optional[str] = None
    resumeId: Optional[str] = None
    resumeFileName: Optional[str] = None
    resumeFileUrl: Optional[str] = None
    coverLetterName: Optional[str] = None
    coverLetterUrl: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    status: str
    followUpAt: Optional[datetime] = None
    followUpNote: Optional[str] = None
    contacts: List[ApplicationContact] = Field(default_factory=list)
    timeline: List[ApplicationTimelineEntry] = Field(default_factory=list)
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class ApplicationAutofillResponse(BaseModel):
    company: str
    role: str
    location: Optional[str] = None
    salary: Optional[str] = None


class ApplicationMatchScoreResponse(BaseModel):
    score: Optional[int] = None
    gaps: Optional[List[str]] = None
    strengths: Optional[List[str]] = None


class ApplicationTailorResponse(BaseModel):
    resumeId: str
    name: str


class ApplicationDraftMessageResponse(BaseModel):
    text: str
    coverLetterId: Optional[str] = None


class CoverLetterCreateRequest(BaseModel):
    name: str
    recipient: str = ""
    content: str = ""
    resumeId: Optional[str] = None
    applicationId: Optional[str] = None


class CoverLetterResponse(BaseModel):
    id: str
    name: str
    recipient: Optional[str] = None
    content: Optional[str] = None
    resumeId: Optional[str] = None
    applicationId: Optional[str] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
