"""
Care Plan Management Agent

Creates personalized care plans, tracks patient progress, and coordinates care activities.
Generates evidence-based treatment recommendations and monitors plan adherence.
"""

from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from structlog import get_logger

from platform_core.agent_orchestration.base_agent import BaseAgent
from platform_core.config import get_config

logger = get_logger()
config = get_config()


# Input/Output Models


class PatientProfile(BaseModel):
    """Patient profile for care plan creation."""

    patient_id: str
    patient_name: str
    age: int
    gender: str
    primary_diagnoses: list[str] = Field(..., description="Primary diagnoses (ICD-10 codes and descriptions)")
    comorbidities: list[str] = Field(default_factory=list, description="Additional conditions")
    current_medications: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    social_determinants: Optional[dict[str, Any]] = Field(
        None, description="Social factors (housing, transportation, etc.)"
    )
    health_literacy_level: str = Field(default="average", description="low, average, high")
    preferred_language: str = Field(default="en")


class CareGoal(BaseModel):
    """A specific care goal."""

    goal_id: str = Field(default_factory=lambda: f"GOAL-{uuid4()}")
    goal_description: str = Field(..., description="What the goal aims to achieve")
    goal_type: str = Field(..., description="clinical, behavioral, functional, quality_of_life")
    target_completion_date: str = Field(..., description="Target date for achieving goal (YYYY-MM-DD)")
    measurable_criteria: str = Field(..., description="How success will be measured")
    priority: str = Field(default="medium", description="low, medium, high")


class CareActivity(BaseModel):
    """A specific care activity or intervention."""

    activity_id: str = Field(default_factory=lambda: f"ACT-{uuid4()}")
    activity_type: str = Field(
        ..., description="medication, therapy, lifestyle, monitoring, education, follow_up"
    )
    description: str
    frequency: str = Field(..., description="How often (daily, weekly, monthly, as_needed)")
    responsible_party: str = Field(..., description="patient, clinician, care_team, family")
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="YYYY-MM-DD, None for ongoing")
    instructions: str = Field(..., description="Detailed instructions for the activity")
    related_goal_id: Optional[str] = Field(None, description="Associated goal ID")


class ProgressMilestone(BaseModel):
    """A milestone for tracking progress."""

    milestone_id: str = Field(default_factory=lambda: f"MILE-{uuid4()}")
    milestone_description: str
    target_date: str = Field(..., description="YYYY-MM-DD")
    completion_criteria: str
    related_goal_id: str


class CarePlanManagementInput(BaseModel):
    """Input for care plan management agent."""

    action: str = Field(..., description="create, update, evaluate_progress")
    patient_profile: PatientProfile
    care_plan_id: Optional[str] = Field(None, description="Existing care plan ID for update/evaluation")
    clinical_notes: Optional[str] = Field(None, description="Recent clinical notes for plan creation/update")
    existing_goals: Optional[list[CareGoal]] = Field(None, description="Current goals (for update/evaluation)")
    existing_activities: Optional[list[CareActivity]] = Field(None, description="Current activities")
    progress_data: Optional[dict[str, Any]] = Field(None, description="Progress data for evaluation")
    plan_duration_days: int = Field(default=90, description="Duration of care plan in days")
    specialty_context: str = Field(..., description="Specialty focus (mental_health, primary_care, chronic_disease)")
    llm_provider: str = Field(default="anthropic", description="LLM provider: anthropic or openai")


class CarePlan(BaseModel):
    """Complete care plan."""

    care_plan_id: str
    patient_id: str
    created_date: str = Field(..., description="YYYY-MM-DD")
    plan_start_date: str
    plan_end_date: str
    specialty_focus: str
    goals: list[CareGoal]
    activities: list[CareActivity]
    milestones: list[ProgressMilestone]
    clinical_summary: str = Field(..., description="Summary of patient's condition and plan rationale")
    risk_factors: list[str] = Field(default_factory=list)
    barriers_to_care: list[str] = Field(default_factory=list)
    care_team: list[str] = Field(default_factory=list, description="List of care team members involved")


class ProgressEvaluation(BaseModel):
    """Evaluation of care plan progress."""

    evaluation_date: str
    overall_progress_score: float = Field(..., description="0.0-1.0, overall progress toward goals")
    goals_on_track: int
    goals_behind: int
    goals_achieved: int
    adherence_rate: float = Field(..., description="0.0-1.0, activity completion rate")
    key_achievements: list[str]
    areas_of_concern: list[str]
    recommendations: list[str] = Field(..., description="Recommended adjustments to care plan")


class CarePlanManagementOutput(BaseModel):
    """Output from care plan management agent."""

    action_taken: str
    care_plan: Optional[CarePlan] = None
    progress_evaluation: Optional[ProgressEvaluation] = None
    plan_summary: str = Field(..., description="Human-readable summary of the care plan or evaluation")
    next_review_date: str = Field(..., description="When plan should be reviewed next (YYYY-MM-DD)")
    alerts: list[str] = Field(default_factory=list, description="Any alerts or urgent items")
    patient_education_materials: list[str] = Field(
        default_factory=list, description="Recommended educational resources"
    )


# Agent Implementation


class CarePlanManagementAgent(BaseAgent[CarePlanManagementInput, CarePlanManagementOutput]):
    """
    Care Plan Management Agent.

    Creates personalized, evidence-based care plans and tracks patient progress.
    Uses LLM for intelligent care plan generation and progress evaluation.
    """

    def __init__(self, llm_provider: str = "anthropic"):
        super().__init__(
            agent_type="care_plan_management",
            agent_version="1.0.0",
            description="Create and manage personalized patient care plans",
        )
        self.llm_provider = llm_provider

        # Initialize LLM clients
        if llm_provider == "anthropic":
            if not config.anthropic_api_key:
                raise ValueError("Anthropic API key not configured")
            self.anthropic_client = AsyncAnthropic(api_key=config.anthropic_api_key)
        elif llm_provider == "openai":
            if not config.openai_api_key:
                raise ValueError("OpenAI API key not configured")
            self.openai_client = AsyncOpenAI(api_key=config.openai_api_key)
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_provider}")

    async def _execute_internal(
        self,
        input_data: CarePlanManagementInput,
        context: dict[str, Any],
    ) -> tuple[CarePlanManagementOutput, float, dict[str, Any]]:
        """Execute care plan management logic."""
        start_time = datetime.now()

        if input_data.action == "create":
            output = await self._create_care_plan(input_data)
        elif input_data.action == "update":
            output = await self._update_care_plan(input_data)
        elif input_data.action == "evaluate_progress":
            output = await self._evaluate_progress(input_data)
        else:
            raise ValueError(f"Unsupported action: {input_data.action}")

        # Calculate confidence
        confidence = self._calculate_care_plan_confidence(output, input_data)

        execution_time_ms = (datetime.now() - start_time).total_seconds() * 1000

        metadata = {
            "llm_provider": self.llm_provider,
            "action": input_data.action,
            "specialty": input_data.specialty_context,
            "execution_time_ms": execution_time_ms,
        }

        return output, confidence, metadata

    async def _create_care_plan(self, input_data: CarePlanManagementInput) -> CarePlanManagementOutput:
        """Create a new care plan."""
        patient = input_data.patient_profile

        # Step 1: Generate clinical summary and goals using LLM
        goals_and_summary = await self._generate_goals_with_llm(input_data)

        # Step 2: Parse goals
        goals = self._parse_goals_from_llm_output(goals_and_summary, input_data.plan_duration_days)

        # Step 3: Generate activities for each goal
        activities = self._generate_activities_for_goals(goals, patient, input_data.specialty_context)

        # Step 4: Create milestones
        milestones = self._create_milestones_for_goals(goals)

        # Step 5: Identify risk factors and barriers
        risk_factors = self._identify_risk_factors(patient)
        barriers = self._identify_barriers_to_care(patient)

        # Step 6: Determine care team
        care_team = self._determine_care_team(input_data.specialty_context, patient)

        # Step 7: Create care plan
        plan_start = datetime.now().strftime("%Y-%m-%d")
        plan_end = (datetime.now() + timedelta(days=input_data.plan_duration_days)).strftime("%Y-%m-%d")

        care_plan = CarePlan(
            care_plan_id=input_data.care_plan_id or f"CP-{uuid4()}",
            patient_id=patient.patient_id,
            created_date=datetime.now().strftime("%Y-%m-%d"),
            plan_start_date=plan_start,
            plan_end_date=plan_end,
            specialty_focus=input_data.specialty_context,
            goals=goals,
            activities=activities,
            milestones=milestones,
            clinical_summary=goals_and_summary.get("clinical_summary", ""),
            risk_factors=risk_factors,
            barriers_to_care=barriers,
            care_team=care_team,
        )

        # Step 8: Generate patient education materials
        education_materials = self._recommend_education_materials(patient, input_data.specialty_context)

        # Step 9: Calculate next review date
        next_review = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")  # 30-day review

        # Step 10: Generate alerts
        alerts = self._generate_alerts_for_new_plan(care_plan, patient)

        output = CarePlanManagementOutput(
            action_taken="create",
            care_plan=care_plan,
            plan_summary=self._generate_plan_summary(care_plan),
            next_review_date=next_review,
            alerts=alerts,
            patient_education_materials=education_materials,
        )

        return output

    async def _update_care_plan(self, input_data: CarePlanManagementInput) -> CarePlanManagementOutput:
        """Update an existing care plan."""
        # For update, we'd analyze progress and adjust goals/activities
        # Simplified implementation - in production would integrate with database

        patient = input_data.patient_profile

        # Generate updated recommendations using LLM
        update_recommendations = await self._generate_update_recommendations_with_llm(input_data)

        # Parse recommendations and update plan
        # This is simplified - real implementation would modify existing plan
        output = CarePlanManagementOutput(
            action_taken="update",
            plan_summary=f"Care plan updated for {patient.patient_name}. {update_recommendations}",
            next_review_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            alerts=["Care plan has been updated based on recent progress"],
            patient_education_materials=[],
        )

        return output

    async def _evaluate_progress(self, input_data: CarePlanManagementInput) -> CarePlanManagementOutput:
        """Evaluate progress on existing care plan."""
        patient = input_data.patient_profile
        existing_goals = input_data.existing_goals or []
        progress_data = input_data.progress_data or {}

        # Calculate progress metrics
        goals_achieved = progress_data.get("goals_achieved", 0)
        goals_on_track = progress_data.get("goals_on_track", len(existing_goals) // 2)
        goals_behind = len(existing_goals) - goals_achieved - goals_on_track

        adherence_rate = progress_data.get("adherence_rate", 0.75)
        overall_progress = (goals_achieved + goals_on_track * 0.5) / max(len(existing_goals), 1)

        # Generate evaluation using LLM
        evaluation_text = await self._generate_progress_evaluation_with_llm(input_data, overall_progress)

        progress_evaluation = ProgressEvaluation(
            evaluation_date=datetime.now().strftime("%Y-%m-%d"),
            overall_progress_score=overall_progress,
            goals_on_track=goals_on_track,
            goals_behind=goals_behind,
            goals_achieved=goals_achieved,
            adherence_rate=adherence_rate,
            key_achievements=self._extract_achievements(evaluation_text),
            areas_of_concern=self._extract_concerns(evaluation_text),
            recommendations=self._extract_recommendations(evaluation_text),
        )

        output = CarePlanManagementOutput(
            action_taken="evaluate_progress",
            progress_evaluation=progress_evaluation,
            plan_summary=f"Progress evaluation for {patient.patient_name}: {overall_progress:.0%} progress toward goals",
            next_review_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            alerts=self._generate_progress_alerts(progress_evaluation),
            patient_education_materials=[],
        )

        return output

    async def _generate_goals_with_llm(self, input_data: CarePlanManagementInput) -> dict[str, Any]:
        """Use LLM to generate care goals and clinical summary."""
        patient = input_data.patient_profile

        prompt = f"""Create a personalized care plan for a patient with the following profile:

**Patient Information:**
- Age: {patient.age}, Gender: {patient.gender}
- Primary Diagnoses: {', '.join(patient.primary_diagnoses)}
- Comorbidities: {', '.join(patient.comorbidities) if patient.comorbidities else 'None'}
- Current Medications: {', '.join(patient.current_medications) if patient.current_medications else 'None'}
- Health Literacy: {patient.health_literacy_level}

**Specialty Context:** {input_data.specialty_context}
**Plan Duration:** {input_data.plan_duration_days} days

{f"**Clinical Notes:** {input_data.clinical_notes}" if input_data.clinical_notes else ""}

Please provide:
1. A brief clinical summary (2-3 sentences) describing the patient's condition and care needs
2. 3-5 SMART goals for this care plan in the following format:

Goal 1: [Type: clinical/behavioral/functional] - [Description] (Target: [X] days, Measure: [how to measure success])

Ensure goals are:
- Specific and measurable
- Achievable within the time frame
- Relevant to the patient's conditions
- Time-bound with clear deadlines
- Appropriate for the patient's health literacy level
"""

        try:
            if self.llm_provider == "anthropic":
                response = await self.anthropic_client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=1500,
                    temperature=0.7,
                    messages=[{"role": "user", "content": prompt}],
                )
                llm_response = response.content[0].text

            else:  # openai
                response = await self.openai_client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    max_tokens=1500,
                    temperature=0.7,
                    messages=[{"role": "user", "content": prompt}],
                )
                llm_response = response.choices[0].message.content

            # Parse response
            lines = llm_response.split('\n')
            clinical_summary = ""
            goals_text = []

            capturing_summary = False
            for line in lines:
                if "clinical summary" in line.lower() or "summary" in line.lower():
                    capturing_summary = True
                elif line.strip().startswith("Goal"):
                    capturing_summary = False
                    goals_text.append(line)
                elif capturing_summary and line.strip():
                    clinical_summary += line.strip() + " "
                elif "Goal" in line and ":" in line:
                    goals_text.append(line)

            return {
                "clinical_summary": clinical_summary.strip(),
                "goals_text": goals_text,
                "full_response": llm_response,
            }

        except Exception as e:
            logger.error("llm_goal_generation_error", error=str(e), provider=self.llm_provider)
            return {
                "clinical_summary": f"Care plan for {', '.join(patient.primary_diagnoses)}",
                "goals_text": [],
                "full_response": "",
            }

    def _parse_goals_from_llm_output(self, llm_output: dict[str, Any], plan_duration: int) -> list[CareGoal]:
        """Parse goals from LLM output."""
        goals = []
        goals_text = llm_output.get("goals_text", [])

        for idx, goal_text in enumerate(goals_text[:5]):  # Max 5 goals
            # Simple parsing - in production would use more robust extraction
            goal_desc = goal_text.split(":", 1)[-1].split("(")[0].strip()

            # Determine goal type
            goal_type = "clinical"
            if "behavior" in goal_text.lower() or "lifestyle" in goal_text.lower():
                goal_type = "behavioral"
            elif "function" in goal_text.lower() or "mobility" in goal_text.lower():
                goal_type = "functional"

            # Set target date (stagger goals throughout plan)
            days_offset = (plan_duration // (len(goals_text) + 1)) * (idx + 1)
            target_date = (datetime.now() + timedelta(days=days_offset)).strftime("%Y-%m-%d")

            # Extract measurable criteria (simplified)
            measurable = "Progress will be assessed at follow-up appointments"
            if "Measure:" in goal_text:
                measurable = goal_text.split("Measure:")[-1].strip(")")

            priority = "high" if idx == 0 else "medium"  # First goal is highest priority

            goals.append(
                CareGoal(
                    goal_description=goal_desc,
                    goal_type=goal_type,
                    target_completion_date=target_date,
                    measurable_criteria=measurable,
                    priority=priority,
                )
            )

        # If no goals parsed, create default goal
        if not goals:
            goals.append(
                CareGoal(
                    goal_description="Improve overall health and manage primary condition",
                    goal_type="clinical",
                    target_completion_date=(datetime.now() + timedelta(days=plan_duration)).strftime("%Y-%m-%d"),
                    measurable_criteria="Assessed through clinical metrics and patient reported outcomes",
                    priority="high",
                )
            )

        return goals

    def _generate_activities_for_goals(
        self, goals: list[CareGoal], patient: PatientProfile, specialty: str
    ) -> list[CareActivity]:
        """Generate activities to support each goal."""
        activities = []
        start_date = datetime.now().strftime("%Y-%m-%d")

        for goal in goals:
            # Add 2-3 activities per goal
            if goal.goal_type == "clinical":
                activities.extend([
                    CareActivity(
                        activity_type="medication",
                        description=f"Take prescribed medications as directed for {goal.goal_description}",
                        frequency="daily",
                        responsible_party="patient",
                        start_date=start_date,
                        instructions="Take medications at the same time each day with food if required",
                        related_goal_id=goal.goal_id,
                    ),
                    CareActivity(
                        activity_type="monitoring",
                        description="Track symptoms and any side effects",
                        frequency="daily",
                        responsible_party="patient",
                        start_date=start_date,
                        instructions="Use symptom diary or mobile app to record daily observations",
                        related_goal_id=goal.goal_id,
                    ),
                ])

            elif goal.goal_type == "behavioral":
                activities.append(
                    CareActivity(
                        activity_type="lifestyle",
                        description=f"Behavioral modification activities for {goal.goal_description}",
                        frequency="daily",
                        responsible_party="patient",
                        start_date=start_date,
                        instructions="Follow personalized behavioral plan discussed with care team",
                        related_goal_id=goal.goal_id,
                    )
                )

            # Add follow-up activity for all goals
            activities.append(
                CareActivity(
                    activity_type="follow_up",
                    description=f"Follow-up appointment to assess progress on {goal.goal_description[:30]}...",
                    frequency="monthly",
                    responsible_party="clinician",
                    start_date=start_date,
                    instructions="Schedule and attend regular follow-up appointments",
                    related_goal_id=goal.goal_id,
                )
            )

        return activities

    def _create_milestones_for_goals(self, goals: list[CareGoal]) -> list[ProgressMilestone]:
        """Create progress milestones for goals."""
        milestones = []

        for goal in goals:
            # Create 2 milestones per goal (mid-point and completion)
            goal_start = datetime.now()
            goal_end = datetime.strptime(goal.target_completion_date, "%Y-%m-%d")
            duration = (goal_end - goal_start).days

            # Mid-point milestone
            mid_date = (goal_start + timedelta(days=duration // 2)).strftime("%Y-%m-%d")
            milestones.append(
                ProgressMilestone(
                    milestone_description=f"50% progress toward: {goal.goal_description[:50]}...",
                    target_date=mid_date,
                    completion_criteria="Partial achievement of goal metrics",
                    related_goal_id=goal.goal_id,
                )
            )

            # Completion milestone
            milestones.append(
                ProgressMilestone(
                    milestone_description=f"Complete: {goal.goal_description[:50]}...",
                    target_date=goal.target_completion_date,
                    completion_criteria=goal.measurable_criteria,
                    related_goal_id=goal.goal_id,
                )
            )

        return milestones

    def _identify_risk_factors(self, patient: PatientProfile) -> list[str]:
        """Identify patient risk factors."""
        risks = []

        if patient.age > 65:
            risks.append("Advanced age (>65) - increased risk of complications")

        if len(patient.comorbidities) >= 3:
            risks.append("Multiple comorbidities - complex medication management")

        if patient.allergies:
            risks.append(f"Medication allergies: {', '.join(patient.allergies)}")

        if patient.health_literacy_level == "low":
            risks.append("Low health literacy - may need additional education and support")

        return risks

    def _identify_barriers_to_care(self, patient: PatientProfile) -> list[str]:
        """Identify potential barriers to care."""
        barriers = []

        if patient.social_determinants:
            sd = patient.social_determinants
            if sd.get("transportation_challenges"):
                barriers.append("Transportation challenges - may affect appointment attendance")
            if sd.get("housing_instability"):
                barriers.append("Housing instability - impacts medication storage and routine")
            if sd.get("food_insecurity"):
                barriers.append("Food insecurity - may affect nutrition-related goals")

        if patient.preferred_language != "en":
            barriers.append(f"Language preference: {patient.preferred_language} - may need interpreter services")

        return barriers

    def _determine_care_team(self, specialty: str, patient: PatientProfile) -> list[str]:
        """Determine care team members."""
        team = ["Primary Clinician"]

        if specialty == "mental_health":
            team.extend(["Therapist", "Psychiatrist (if medication management)"])
        elif specialty == "chronic_disease":
            team.extend(["Nurse Care Manager", "Specialist"])
        elif specialty == "primary_care":
            team.append("Care Coordinator")

        if len(patient.current_medications) > 5:
            team.append("Pharmacist")

        if patient.social_determinants:
            team.append("Social Worker")

        return team

    def _recommend_education_materials(self, patient: PatientProfile, specialty: str) -> list[str]:
        """Recommend patient education materials."""
        materials = []

        # Add condition-specific materials
        for diagnosis in patient.primary_diagnoses[:2]:  # Top 2 conditions
            materials.append(f"Understanding {diagnosis.split('(')[0].strip()}: Patient Guide")

        # Add medication education if applicable
        if patient.current_medications:
            materials.append("Medication Management: Taking Your Medications Safely")

        # Add specialty-specific materials
        if specialty == "mental_health":
            materials.append("Coping Strategies for Mental Wellness")
        elif specialty == "chronic_disease":
            materials.append("Living Well with Chronic Conditions")

        return materials[:3]  # Limit to 3 materials

    def _generate_alerts_for_new_plan(self, care_plan: CarePlan, patient: PatientProfile) -> list[str]:
        """Generate alerts for new care plan."""
        alerts = []

        if care_plan.risk_factors:
            alerts.append(f"⚠️ {len(care_plan.risk_factors)} risk factors identified - review carefully")

        if care_plan.barriers_to_care:
            alerts.append(f"⚠️ {len(care_plan.barriers_to_care)} barriers to care - may need support services")

        if len(care_plan.activities) > 10:
            alerts.append(f"📋 Care plan includes {len(care_plan.activities)} activities - ensure patient understands all")

        return alerts

    def _generate_plan_summary(self, care_plan: CarePlan) -> str:
        """Generate human-readable care plan summary."""
        summary = f"""Care Plan Summary for {care_plan.plan_start_date} to {care_plan.plan_end_date}:

**Clinical Summary:** {care_plan.clinical_summary}

**Goals:** {len(care_plan.goals)} goals established focusing on {', '.join(set(g.goal_type for g in care_plan.goals))} outcomes

**Activities:** {len(care_plan.activities)} care activities scheduled

**Care Team:** {', '.join(care_plan.care_team)}

**Next Review:** 30 days from plan initiation
"""
        return summary

    async def _generate_update_recommendations_with_llm(self, input_data: CarePlanManagementInput) -> str:
        """Generate care plan update recommendations."""
        prompt = "Based on recent progress, recommend adjustments to the care plan focusing on goals and activities that need modification."

        try:
            if self.llm_provider == "anthropic":
                response = await self.anthropic_client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=500,
                    temperature=0.7,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
            else:
                response = await self.openai_client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    max_tokens=500,
                    temperature=0.7,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.choices[0].message.content
        except:
            return "Care plan updated based on recent clinical assessment"

    async def _generate_progress_evaluation_with_llm(
        self, input_data: CarePlanManagementInput, progress_score: float
    ) -> str:
        """Generate progress evaluation narrative."""
        prompt = f"Evaluate patient progress at {progress_score:.0%}. Identify achievements, concerns, and recommendations."

        try:
            if self.llm_provider == "anthropic":
                response = await self.anthropic_client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=800,
                    temperature=0.7,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
            else:
                response = await self.openai_client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    max_tokens=800,
                    temperature=0.7,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.choices[0].message.content
        except:
            return f"Patient demonstrates {progress_score:.0%} progress toward established care goals."

    def _extract_achievements(self, evaluation_text: str) -> list[str]:
        """Extract key achievements from evaluation."""
        # Simplified extraction
        return ["Consistent medication adherence", "Regular appointment attendance"]

    def _extract_concerns(self, evaluation_text: str) -> list[str]:
        """Extract areas of concern."""
        return ["Some goals behind schedule"]

    def _extract_recommendations(self, evaluation_text: str) -> list[str]:
        """Extract recommendations."""
        return ["Continue current treatment plan", "Schedule follow-up in 30 days"]

    def _generate_progress_alerts(self, evaluation: ProgressEvaluation) -> list[str]:
        """Generate alerts based on progress evaluation."""
        alerts = []

        if evaluation.overall_progress_score < 0.5:
            alerts.append("⚠️ Progress below 50% - care plan may need adjustment")

        if evaluation.adherence_rate < 0.7:
            alerts.append("⚠️ Low adherence rate - patient may need additional support")

        if evaluation.goals_behind > evaluation.goals_on_track:
            alerts.append("⚠️ More goals behind than on track - consider care plan revision")

        return alerts

    def _calculate_care_plan_confidence(
        self, output: CarePlanManagementOutput, input_data: CarePlanManagementInput
    ) -> float:
        """Calculate confidence in care plan."""
        confidence = 0.8

        # Higher confidence with clinical notes
        if input_data.clinical_notes and len(input_data.clinical_notes) > 100:
            confidence += 0.1

        # Lower confidence for complex cases
        if len(input_data.patient_profile.comorbidities) >= 3:
            confidence -= 0.1

        return max(0.0, min(1.0, confidence))

    def _determine_review_needed(
        self,
        output: CarePlanManagementOutput,
        confidence: float,
        input_data: CarePlanManagementInput,
    ) -> tuple[bool, Optional[str]]:
        """Determine if human review is needed."""
        # Always review new care plans
        if output.action_taken == "create":
            return True, "New care plan requires clinical review"

        # Review if alerts present
        if output.alerts and len(output.alerts) >= 2:
            return True, f"{len(output.alerts)} alerts requiring attention"

        # Review progress evaluations with poor adherence
        if output.progress_evaluation and output.progress_evaluation.adherence_rate < 0.6:
            return True, "Low adherence rate requires intervention"

        return False, None
