from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from packages.domain.models import CanonicalJob
from packages.domain.role_discovery import JobProvenance
from packages.persistence.models import (
    AgentDecisionORM,
    AgentRunORM,
    ApplicationEventORM,
    ApplicationRunORM,
    CandidateAnswerORM,
    JobORM,
    JobSnapshotORM,
    ManualQuestionORM,
    NotificationORM,
)


def _to_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class JobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, job_id: str) -> Optional[JobORM]:
        result = await self.session.execute(select(JobORM).where(JobORM.id == job_id))
        return result.scalar_one_or_none()

    async def get_by_hash(self, dedup_hash: str) -> Optional[JobORM]:
        result = await self.session.execute(select(JobORM).where(JobORM.dedup_hash == dedup_hash))
        return result.scalar_one_or_none()

    async def get_by_canonical_url(self, url: str) -> Optional[JobORM]:
        result = await self.session.execute(
            select(JobORM).where(JobORM.canonical_url == url)
        )
        return result.scalars().first()

    async def get_by_source_url(self, url: str) -> Optional[JobORM]:
        result = await self.session.execute(select(JobORM).where(JobORM.source_url == url))
        return result.scalars().first()

    async def get_by_source_job_id(self, source: str, source_job_id: str) -> Optional[JobORM]:
        result = await self.session.execute(
            select(JobORM).where(
                JobORM.source == source, JobORM.source_job_id == source_job_id
            )
        )
        return result.scalars().first()

    async def get_by_fingerprint(self, fingerprint: str) -> Optional[JobORM]:
        result = await self.session.execute(
            select(JobORM).where(JobORM.description_fingerprint == fingerprint)
        )
        return result.scalars().first()

    async def find_by_company_and_role(
        self, normalized_company: str, normalized_role: str
    ) -> Optional[JobORM]:
        result = await self.session.execute(
            select(JobORM).where(
                JobORM.normalized_company == normalized_company,
                JobORM.normalized_role == normalized_role,
            )
        )
        return result.scalars().first()

    async def create_or_update(
        self,
        job: CanonicalJob,
        provenance: Optional[JobProvenance] = None,
        description_fingerprint: Optional[str] = None,
    ) -> JobORM:
        existing = await self.get_by_hash(job.dedup_hash)
        if existing:
            existing.status = job.status.value
            existing.updated_at = datetime.utcnow()
            if description_fingerprint and not existing.description_fingerprint:
                existing.description_fingerprint = description_fingerprint
            await self.session.flush()
            return existing

        orm_obj = JobORM(
            id=job.id,
            dedup_hash=job.dedup_hash,
            source=job.source.value,
            source_job_id=job.source_job_id,
            company=job.company,
            normalized_company=job.normalized_company,
            role=job.role,
            normalized_role=job.normalized_role,
            canonical_url=job.canonical_url,
            apply_url=job.apply_url,
            location=job.location,
            is_remote=job.is_remote,
            is_hybrid=job.is_hybrid,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
            salary_currency=job.salary_currency,
            description=job.description,
            requirements=job.requirements,
            preferred_requirements=job.preferred_requirements,
            technologies=job.technologies,
            status=job.status.value,
            published_at=_to_naive_utc(job.published_at),
            discovered_at=_to_naive_utc(job.discovered_at) or datetime.utcnow(),
            description_fingerprint=description_fingerprint,
        )
        if provenance is not None:
            orm_obj.discovered_by = provenance.discovered_by.value
            orm_obj.search_query_id = provenance.search_query_id
            orm_obj.search_provider = provenance.search_provider
            orm_obj.source_url = provenance.source_url
        self.session.add(orm_obj)
        await self.session.flush()
        return orm_obj

    async def list_jobs(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        discovered_by: Optional[str] = None,
        search_query_id: Optional[str] = None,
    ) -> List[JobORM]:
        stmt = select(JobORM).order_by(desc(JobORM.discovered_at))
        if status:
            stmt = stmt.where(JobORM.status == status)
        if discovered_by:
            stmt = stmt.where(JobORM.discovered_by == discovered_by)
        if search_query_id:
            stmt = stmt.where(JobORM.search_query_id == search_query_id)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class ApplicationRunRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, run_id: str) -> Optional[ApplicationRunORM]:
        result = await self.session.execute(
            select(ApplicationRunORM).where(ApplicationRunORM.id == run_id)
        )
        return result.scalar_one_or_none()

    async def get_by_job_id(self, job_id: str) -> Optional[ApplicationRunORM]:
        result = await self.session.execute(
            select(ApplicationRunORM).where(ApplicationRunORM.job_id == job_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        job_id: str,
        execution_mode: str = "AUTO_APPLY",
        match_score: Optional[int] = None,
        scorecard: Optional[Dict[str, Any]] = None,
        reactive_resume_application_id: Optional[str] = None,
    ) -> ApplicationRunORM:
        run = ApplicationRunORM(
            job_id=job_id,
            execution_mode=execution_mode,
            match_score=match_score,
            scorecard=scorecard,
            reactive_resume_application_id=reactive_resume_application_id,
            status="PREPARING",
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def update_status(
        self,
        run_id: str,
        status: str,
        error_message: Optional[str] = None,
        error_category: Optional[str] = None,
        submission_evidence: Optional[Dict[str, Any]] = None,
    ) -> Optional[ApplicationRunORM]:
        run = await self.get_by_id(run_id)
        if not run:
            return None
        run.status = status
        if error_message is not None:
            run.error_message = error_message
        if error_category is not None:
            run.error_category = error_category
        if submission_evidence is not None:
            run.submission_evidence = submission_evidence
        run.updated_at = datetime.utcnow()
        await self.session.flush()
        return run

    async def list_recent(self, limit: int = 50) -> List[ApplicationRunORM]:
        stmt = select(ApplicationRunORM).order_by(desc(ApplicationRunORM.created_at)).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class CandidateAnswerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_canonical(self, canonical_key: str) -> Optional[CandidateAnswerORM]:
        result = await self.session.execute(
            select(CandidateAnswerORM).where(CandidateAnswerORM.question_canonical == canonical_key)
        )
        return result.scalar_one_or_none()

    async def upsert_answer(
        self,
        canonical_key: str,
        answer: Any,
        answer_type: str = "string",
        source: str = "user",
        confidence: float = 1.0,
        raw_question: Optional[str] = None,
    ) -> CandidateAnswerORM:
        existing = await self.get_by_canonical(canonical_key)
        if existing:
            existing.answer = answer
            existing.source = source
            existing.confidence = confidence
            existing.usage_count += 1
            existing.last_confirmed_at = datetime.utcnow()
            if raw_question:
                existing.question_raw = raw_question
            await self.session.flush()
            return existing

        new_entry = CandidateAnswerORM(
            question_canonical=canonical_key,
            question_raw=raw_question,
            answer=answer,
            answer_type=answer_type,
            source=source,
            confidence=confidence,
            usage_count=1,
        )
        self.session.add(new_entry)
        await self.session.flush()
        return new_entry

    async def list_all(self) -> List[CandidateAnswerORM]:
        result = await self.session.execute(select(CandidateAnswerORM))
        return list(result.scalars().all())


class ManualQuestionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        question_text: str,
        application_run_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ManualQuestionORM:
        item = ManualQuestionORM(
            question_text=question_text,
            application_run_id=application_run_id,
            context=context or {},
            status="PENDING",
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def list_pending(self) -> List[ManualQuestionORM]:
        result = await self.session.execute(
            select(ManualQuestionORM).where(ManualQuestionORM.status == "PENDING")
        )
        return list(result.scalars().all())

    async def answer(self, question_id: str, answer_text: str) -> Optional[ManualQuestionORM]:
        result = await self.session.execute(
            select(ManualQuestionORM).where(ManualQuestionORM.id == question_id)
        )
        item = result.scalar_one_or_none()
        if item:
            item.answer = answer_text
            item.status = "ANSWERED"
            item.answered_at = datetime.utcnow()
            await self.session.flush()
        return item


class EventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log(
        self,
        event_type: str,
        message: str,
        application_run_id: Optional[str] = None,
        job_id: Optional[str] = None,
        severity: str = "INFO",
        details: Optional[Dict[str, Any]] = None,
    ) -> ApplicationEventORM:
        event = ApplicationEventORM(
            event_type=event_type,
            message=message,
            application_run_id=application_run_id,
            job_id=job_id,
            severity=severity,
            details=details or {},
        )
        self.session.add(event)
        await self.session.flush()
        return event


class AgentDecisionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def record(
        self,
        run_id: str,
        agent_name: str,
        decision: str,
        confidence: float,
        reason: str,
        input_summary: Optional[Dict[str, Any]] = None,
        evidence: Optional[List[str]] = None,
        model_used: Optional[str] = None,
    ) -> AgentDecisionORM:
        entry = AgentDecisionORM(
            run_id=run_id,
            agent_name=agent_name,
            decision=decision,
            confidence=confidence,
            reason=reason,
            input_summary=input_summary or {},
            evidence=evidence or [],
            model_used=model_used,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry
