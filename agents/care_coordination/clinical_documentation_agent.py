"""
Clinical Documentation Agent

AI-assisted clinical documentation generation for progress notes, encounter summaries,
and clinical narratives. Helps clinicians create comprehensive, compliant documentation efficiently.
"""

from datetime import datetime
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


class EncounterDetails(BaseModel):
    """Details about the clinical encounter."""

    encounter_id: str
    patient_id: str
    patient_name: str
    patient_age: int
    patient_gender: str
    encounter_date: str = Field(..., description="YYYY-MM-DD")
    encounter_type: str = Field(..., description="office_visit, telehealth, hospital_round, follow_up, initial_consult")
    visit_duration_minutes: int
    chief_complaint: str
    specialty: str = Field(..., description="Clinician's specialty")


class ClinicalObservations(BaseModel):
    """Clinical observations and findings."""

    subjective: str = Field(..., description="Patient's reported symptoms and concerns")
    objective: Optional[str] = Field(None, description="Physical exam findings, vitals, test results")
    vital_signs: Optional[dict[str, Any]] = Field(None, description="BP, HR, Temp, RR, O2 sat, etc.")
    review_of_systems: Optional[str] = Field(None, description="System-by-system review")
    mental_status: Optional[str] = Field(None, description="For behavioral health encounters")


class ClinicalDecisionMaking(BaseModel):
    """Assessment and treatment decisions."""

    assessment: str = Field(..., description="Clinical assessment and diagnoses")
    differential_diagnoses: Optional[list[str]] = Field(None, description="Other diagnoses considered")
    treatment_plan: str = Field(..., description="Treatment interventions and recommendations")
    medications_prescribed: Optional[list[str]] = Field(None, description="New or changed medications")
    tests_ordered: Optional[list[str]] = Field(None, description="Labs, imaging, or other tests ordered")
    referrals_made: Optional[list[str]] = Field(None, description="Specialist referrals")
    patient_education_provided: Optional[str] = Field(None, description="Education topics discussed")
    follow_up_plan: str = Field(..., description="Follow-up timing and next steps")


class ClinicalDocumentationInput(BaseModel):
    """Input for clinical documentation agent."""

    documentation_type: str = Field(
        ..., description="progress_note, soap_note, encounter_summary, discharge_summary, procedure_note"
    )
    encounter: EncounterDetails
    observations: ClinicalObservations
    clinical_decisions: ClinicalDecisionMaking
    previous_encounters: Optional[list[str]] = Field(
        None, description="Previous encounter summaries for context"
    )
    voice_transcript: Optional[str] = Field(
        None, description="Transcribed voice notes from clinician (for voice-to-text workflow)"
    )
    additional_context: Optional[str] = Field(None, description="Any additional context or notes")
    include_billing_codes: bool = Field(
        default=True, description="Include suggested CPT/ICD codes in documentation"
    )
    template_style: str = Field(
        default="comprehensive", description="comprehensive, concise, structured"
    )
    llm_provider: str = Field(default="anthropic", description="LLM provider: anthropic or openai")


class BillingCodeSuggestion(BaseModel):
    """Suggested billing codes."""

    cpt_codes: list[str] = Field(default_factory=list, description="Suggested CPT codes")
    icd_codes: list[str] = Field(default_factory=list, description="Suggested ICD-10 codes")
    level_of_service: Optional[str] = Field(None, description="E&M level (99213, 99214, etc.)")
    justification: str = Field(..., description="Rationale for code selection")


class QualityMetrics(BaseModel):
    """Documentation quality assessment."""

    completeness_score: float = Field(..., description="0.0-1.0, how complete the documentation is")
    compliance_score: float = Field(..., description="0.0-1.0, adherence to documentation standards")
    readability_score: float = Field(..., description="0.0-1.0, clarity and organization")
    missing_elements: list[str] = Field(default_factory=list, description="Critical missing components")
    improvement_suggestions: list[str] = Field(default_factory=list, description="Suggestions for enhancement")


class ClinicalDocumentationOutput(BaseModel):
    """Output from clinical documentation agent."""

    document_id: str
    documentation_type: str
    generated_note: str = Field(..., description="Complete clinical note in standard format")
    sections: dict[str, str] = Field(..., description="Individual sections (subjective, objective, etc.)")
    billing_suggestions: Optional[BillingCodeSuggestion] = None
    quality_metrics: QualityMetrics
    word_count: int
    estimated_documentation_time_saved_minutes: int = Field(
        ..., description="Estimated time saved vs manual documentation"
    )
    compliance_flags: list[str] = Field(
        default_factory=list, description="Compliance or quality issues requiring attention"
    )
    addendum_suggestions: list[str] = Field(
        default_factory=list, description="Suggested additions or clarifications"
    )


# Agent Implementation


class ClinicalDocumentationAgent(BaseAgent[ClinicalDocumentationInput, ClinicalDocumentationOutput]):
    """
    Clinical Documentation Agent.

    Generates comprehensive, compliant clinical documentation using AI to assist clinicians
    in creating high-quality progress notes and encounter summaries efficiently.
    """

    def __init__(self, llm_provider: str = "anthropic"):
        super().__init__(
            agent_type="clinical_documentation",
            agent_version="1.0.0",
            description="AI-assisted clinical documentation generation for progress notes and encounter summaries",
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
        input_data: ClinicalDocumentationInput,
        context: dict[str, Any],
    ) -> tuple[ClinicalDocumentationOutput, float, dict[str, Any]]:
        """Execute clinical documentation generation."""
        start_time = datetime.now()

        # Step 1: Generate clinical note using LLM
        generated_sections = await self._generate_clinical_note(input_data)

        # Step 2: Assemble complete note
        complete_note = self._assemble_complete_note(generated_sections, input_data)

        # Step 3: Generate billing code suggestions if requested
        billing_suggestions = None
        if input_data.include_billing_codes:
            billing_suggestions = await self._suggest_billing_codes(input_data, generated_sections)

        # Step 4: Assess documentation quality
        quality_metrics = self._assess_documentation_quality(generated_sections, input_data)

        # Step 5: Identify compliance flags
        compliance_flags = self._check_compliance(generated_sections, input_data)

        # Step 6: Generate addendum suggestions
        addendum_suggestions = self._generate_addendum_suggestions(generated_sections, quality_metrics)

        # Step 7: Calculate time saved
        word_count = len(complete_note.split())
        time_saved = self._estimate_time_saved(word_count, input_data.documentation_type)

        # Step 8: Create output
        output = ClinicalDocumentationOutput(
            document_id=f"DOC-{uuid4()}",
            documentation_type=input_data.documentation_type,
            generated_note=complete_note,
            sections=generated_sections,
            billing_suggestions=billing_suggestions,
            quality_metrics=quality_metrics,
            word_count=word_count,
            estimated_documentation_time_saved_minutes=time_saved,
            compliance_flags=compliance_flags,
            addendum_suggestions=addendum_suggestions,
        )

        # Calculate confidence
        confidence = self._calculate_documentation_confidence(output, input_data)

        execution_time_ms = (datetime.now() - start_time).total_seconds() * 1000

        metadata = {
            "llm_provider": self.llm_provider,
            "documentation_type": input_data.documentation_type,
            "word_count": word_count,
            "time_saved_minutes": time_saved,
            "quality_score": quality_metrics.completeness_score,
            "execution_time_ms": execution_time_ms,
        }

        return output, confidence, metadata

    async def _generate_clinical_note(self, input_data: ClinicalDocumentationInput) -> dict[str, str]:
        """Generate clinical note sections using LLM."""
        encounter = input_data.encounter
        obs = input_data.observations
        decisions = input_data.clinical_decisions

        # Build comprehensive prompt based on documentation type
        if input_data.documentation_type == "soap_note":
            prompt = self._build_soap_note_prompt(input_data)
        elif input_data.documentation_type == "progress_note":
            prompt = self._build_progress_note_prompt(input_data)
        else:
            prompt = self._build_generic_note_prompt(input_data)

        try:
            if self.llm_provider == "anthropic":
                response = await self.anthropic_client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=3000,
                    temperature=0.3,  # Lower temperature for clinical documentation
                    messages=[{"role": "user", "content": prompt}],
                )
                llm_response = response.content[0].text

            else:  # openai
                response = await self.openai_client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    max_tokens=3000,
                    temperature=0.3,
                    messages=[{"role": "user", "content": prompt}],
                )
                llm_response = response.choices[0].message.content

            # Parse sections from LLM response
            sections = self._parse_sections_from_llm(llm_response, input_data.documentation_type)

            return sections

        except Exception as e:
            logger.error("llm_documentation_error", error=str(e), provider=self.llm_provider)
            # Return basic sections as fallback
            return self._generate_fallback_sections(input_data)

    def _build_soap_note_prompt(self, input_data: ClinicalDocumentationInput) -> str:
        """Build prompt for SOAP note generation."""
        encounter = input_data.encounter
        obs = input_data.observations
        decisions = input_data.clinical_decisions

        prompt = f"""Generate a professional SOAP note for the following clinical encounter:

**Patient Information:**
- Name: {encounter.patient_name}
- Age: {encounter.patient_age}, Gender: {encounter.patient_gender}
- Encounter Date: {encounter.encounter_date}
- Encounter Type: {encounter.encounter_type}
- Visit Duration: {encounter.visit_duration_minutes} minutes
- Chief Complaint: {encounter.chief_complaint}
- Specialty: {encounter.specialty}

**SUBJECTIVE:**
{obs.subjective}

**OBJECTIVE:**
{obs.objective or "Physical examination findings to be documented."}

{f"**Vital Signs:** {obs.vital_signs}" if obs.vital_signs else ""}

{f"**Review of Systems:** {obs.review_of_systems}" if obs.review_of_systems else ""}

{f"**Mental Status:** {obs.mental_status}" if obs.mental_status else ""}

**ASSESSMENT:**
{decisions.assessment}

{f"**Differential Diagnoses:** {', '.join(decisions.differential_diagnoses)}" if decisions.differential_diagnoses else ""}

**PLAN:**
{decisions.treatment_plan}

{f"**Medications:** {', '.join(decisions.medications_prescribed)}" if decisions.medications_prescribed else ""}

{f"**Tests Ordered:** {', '.join(decisions.tests_ordered)}" if decisions.tests_ordered else ""}

{f"**Referrals:** {', '.join(decisions.referrals_made)}" if decisions.referrals_made else ""}

{f"**Patient Education:** {decisions.patient_education_provided}" if decisions.patient_education_provided else ""}

**Follow-up:**
{decisions.follow_up_plan}

{f"**Previous Context:** {input_data.previous_encounters[0][:200]}..." if input_data.previous_encounters else ""}

{f"**Additional Context:** {input_data.additional_context}" if input_data.additional_context else ""}

Please generate a complete, professional SOAP note with the following sections:
1. SUBJECTIVE
2. OBJECTIVE
3. ASSESSMENT
4. PLAN

Use proper medical terminology and formatting. Ensure the note is comprehensive, accurate, and compliant with documentation standards. Style: {input_data.template_style}.
"""
        return prompt

    def _build_progress_note_prompt(self, input_data: ClinicalDocumentationInput) -> str:
        """Build prompt for progress note generation."""
        encounter = input_data.encounter
        obs = input_data.observations
        decisions = input_data.clinical_decisions

        prompt = f"""Generate a professional progress note for the following clinical encounter:

**Patient:** {encounter.patient_name}, {encounter.patient_age}yo {encounter.patient_gender}
**Date:** {encounter.encounter_date}
**Visit Type:** {encounter.encounter_type}
**Chief Complaint:** {encounter.chief_complaint}

**Clinical Information:**
- Subjective: {obs.subjective}
- Objective: {obs.objective or "See physical exam"}
- Assessment: {decisions.assessment}
- Treatment Plan: {decisions.treatment_plan}
- Follow-up: {decisions.follow_up_plan}

Generate a comprehensive progress note that documents this encounter clearly and professionally. Style: {input_data.template_style}.
"""
        return prompt

    def _build_generic_note_prompt(self, input_data: ClinicalDocumentationInput) -> str:
        """Build generic note prompt."""
        return f"Generate a {input_data.documentation_type} for the encounter. Include all relevant clinical information in a professional format."

    def _parse_sections_from_llm(self, llm_response: str, doc_type: str) -> dict[str, str]:
        """Parse sections from LLM response."""
        sections = {}
        current_section = None
        current_content = []

        lines = llm_response.split('\n')

        for line in lines:
            line_upper = line.strip().upper()

            # Detect section headers
            if line_upper in ['SUBJECTIVE:', 'SUBJECTIVE', 'S:', 'SUBJECT:']:
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()
                current_section = 'subjective'
                current_content = []
            elif line_upper in ['OBJECTIVE:', 'OBJECTIVE', 'O:', 'OBJECT:']:
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()
                current_section = 'objective'
                current_content = []
            elif line_upper in ['ASSESSMENT:', 'ASSESSMENT', 'A:', 'ASSESS:']:
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()
                current_section = 'assessment'
                current_content = []
            elif line_upper in ['PLAN:', 'PLAN', 'P:']:
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()
                current_section = 'plan'
                current_content = []
            elif current_section and line.strip():
                current_content.append(line)

        # Add last section
        if current_section:
            sections[current_section] = '\n'.join(current_content).strip()

        # If no sections parsed, put entire response in 'note' section
        if not sections:
            sections['note'] = llm_response

        return sections

    def _generate_fallback_sections(self, input_data: ClinicalDocumentationInput) -> dict[str, str]:
        """Generate basic sections as fallback."""
        obs = input_data.observations
        decisions = input_data.clinical_decisions

        return {
            'subjective': obs.subjective,
            'objective': obs.objective or "Physical examination documented.",
            'assessment': decisions.assessment,
            'plan': decisions.treatment_plan + f"\n\nFollow-up: {decisions.follow_up_plan}",
        }

    def _assemble_complete_note(self, sections: dict[str, str], input_data: ClinicalDocumentationInput) -> str:
        """Assemble sections into complete clinical note."""
        encounter = input_data.encounter

        # Header
        note = f"""CLINICAL DOCUMENTATION
Document Type: {input_data.documentation_type.replace('_', ' ').title()}
Document ID: DOC-{uuid4()}

PATIENT: {encounter.patient_name}
AGE/GENDER: {encounter.patient_age} years / {encounter.patient_gender}
DATE OF SERVICE: {encounter.encounter_date}
ENCOUNTER TYPE: {encounter.encounter_type.replace('_', ' ').title()}
VISIT DURATION: {encounter.visit_duration_minutes} minutes
CHIEF COMPLAINT: {encounter.chief_complaint}
SPECIALTY: {encounter.specialty.replace('_', ' ').title()}

---

"""

        # Add sections
        if input_data.documentation_type in ['soap_note', 'progress_note']:
            if 'subjective' in sections:
                note += f"SUBJECTIVE:\n{sections['subjective']}\n\n"
            if 'objective' in sections:
                note += f"OBJECTIVE:\n{sections['objective']}\n\n"
            if 'assessment' in sections:
                note += f"ASSESSMENT:\n{sections['assessment']}\n\n"
            if 'plan' in sections:
                note += f"PLAN:\n{sections['plan']}\n\n"
        else:
            # Generic format
            for section_name, content in sections.items():
                note += f"{section_name.upper()}:\n{content}\n\n"

        # Footer
        note += f"""---
Document generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Generated by: Agentic TalkDoc Clinical Documentation Agent v1.0.0
"""

        return note

    async def _suggest_billing_codes(
        self, input_data: ClinicalDocumentationInput, sections: dict[str, str]
    ) -> BillingCodeSuggestion:
        """Suggest billing codes based on documentation."""
        # Use the Medical Coding Agent logic or simplified version
        encounter = input_data.encounter

        # Basic E&M level determination based on duration and complexity
        level = "99213"  # Default
        if encounter.visit_duration_minutes >= 45:
            level = "99215"
        elif encounter.visit_duration_minutes >= 30:
            level = "99214"
        elif encounter.visit_duration_minutes >= 20:
            level = "99213"
        else:
            level = "99212"

        # Determine CPT codes
        cpt_codes = [level]

        # Determine ICD codes from assessment (simplified - real version would use Medical Coding Agent)
        icd_codes = []
        assessment = sections.get('assessment', input_data.clinical_decisions.assessment)

        # Common mental health codes (if specialty matches)
        if 'depression' in assessment.lower():
            icd_codes.append("F32.9")
        if 'anxiety' in assessment.lower():
            icd_codes.append("F41.9")
        if 'hypertension' in assessment.lower():
            icd_codes.append("I10")

        justification = f"E&M level {level} based on {encounter.visit_duration_minutes} minute visit. ICD codes reflect primary diagnoses documented in assessment."

        return BillingCodeSuggestion(
            cpt_codes=cpt_codes,
            icd_codes=icd_codes if icd_codes else ["Z00.00"],  # Default if none found
            level_of_service=level,
            justification=justification,
        )

    def _assess_documentation_quality(
        self, sections: dict[str, str], input_data: ClinicalDocumentationInput
    ) -> QualityMetrics:
        """Assess documentation quality."""
        completeness = 0.0
        compliance = 0.0
        missing_elements = []

        # Check required sections for SOAP note
        if input_data.documentation_type in ['soap_note', 'progress_note']:
            required_sections = ['subjective', 'objective', 'assessment', 'plan']
            present_sections = sum(1 for s in required_sections if s in sections and sections[s])
            completeness = present_sections / len(required_sections)

            for section in required_sections:
                if section not in sections or not sections[section]:
                    missing_elements.append(f"Missing {section.title()} section")

        else:
            completeness = 0.8  # Generic doc types

        # Compliance checks
        compliance_checks = []

        # Check for key elements
        if input_data.clinical_decisions.follow_up_plan:
            compliance_checks.append(True)
        else:
            missing_elements.append("Follow-up plan not specified")
            compliance_checks.append(False)

        if input_data.observations.subjective:
            compliance_checks.append(True)
        else:
            compliance_checks.append(False)

        compliance = sum(compliance_checks) / max(len(compliance_checks), 1)

        # Readability (simplified - based on structure)
        readability = 0.8 if len(sections) >= 3 else 0.6

        # Suggestions
        suggestions = []
        if completeness < 0.8:
            suggestions.append("Add missing documentation sections")
        if not input_data.observations.vital_signs:
            suggestions.append("Consider documenting vital signs")
        if not input_data.clinical_decisions.patient_education_provided:
            suggestions.append("Document patient education provided")

        return QualityMetrics(
            completeness_score=completeness,
            compliance_score=compliance,
            readability_score=readability,
            missing_elements=missing_elements,
            improvement_suggestions=suggestions,
        )

    def _check_compliance(self, sections: dict[str, str], input_data: ClinicalDocumentationInput) -> list[str]:
        """Check for compliance issues."""
        flags = []

        # Check for red flag keywords that need attention
        all_text = ' '.join(sections.values()).lower()

        if 'suicide' in all_text or 'self-harm' in all_text:
            flags.append("⚠️ Suicide/self-harm mentioned - ensure safety assessment documented")

        if 'abuse' in all_text:
            flags.append("⚠️ Abuse mentioned - ensure appropriate reporting and documentation")

        # Check for missing critical elements
        if not input_data.clinical_decisions.follow_up_plan:
            flags.append("⚠️ Follow-up plan not specified")

        return flags

    def _generate_addendum_suggestions(
        self, sections: dict[str, str], quality_metrics: QualityMetrics
    ) -> list[str]:
        """Generate suggestions for addendums."""
        suggestions = []

        if quality_metrics.completeness_score < 0.8:
            suggestions.append("Consider adding more detail to incomplete sections")

        if quality_metrics.missing_elements:
            suggestions.append(f"Address missing elements: {', '.join(quality_metrics.missing_elements[:2])}")

        return suggestions

    def _estimate_time_saved(self, word_count: int, doc_type: str) -> int:
        """Estimate time saved by using AI documentation."""
        # Baseline: clinicians type ~40 words per minute
        # Manual documentation typically takes 2-3x longer due to thinking/formatting

        manual_minutes = (word_count / 40) * 2.5  # 2.5x multiplier for manual effort
        ai_review_minutes = 2  # Time to review and adjust AI-generated note

        time_saved = int(max(0, manual_minutes - ai_review_minutes))

        return time_saved

    def _calculate_documentation_confidence(
        self, output: ClinicalDocumentationOutput, input_data: ClinicalDocumentationInput
    ) -> float:
        """Calculate confidence in documentation quality."""
        confidence = 0.7  # Base confidence

        # Increase for high quality scores
        avg_quality = (
            output.quality_metrics.completeness_score +
            output.quality_metrics.compliance_score +
            output.quality_metrics.readability_score
        ) / 3
        confidence += avg_quality * 0.2

        # Decrease for compliance flags
        if output.compliance_flags:
            confidence -= len(output.compliance_flags) * 0.05

        # Increase if comprehensive input provided
        if input_data.observations.objective and input_data.observations.review_of_systems:
            confidence += 0.05

        return max(0.0, min(1.0, confidence))

    def _determine_review_needed(
        self,
        output: ClinicalDocumentationOutput,
        confidence: float,
        input_data: ClinicalDocumentationInput,
    ) -> tuple[bool, Optional[str]]:
        """Determine if human review is needed."""
        # Always require review - this is clinical documentation
        if output.compliance_flags:
            return True, f"{len(output.compliance_flags)} compliance flags require attention"

        if output.quality_metrics.completeness_score < 0.7:
            return True, "Documentation incomplete - requires clinical review"

        # All clinical documentation should be reviewed by the clinician
        return True, "Clinical documentation requires clinician review and signature"
