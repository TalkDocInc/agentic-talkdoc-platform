"""
Denial Management Agent

Analyzes claim denials, determines appeal viability, and automates the appeals process.
Provides actionable recommendations and generates appeal documentation.
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


class DenialDetails(BaseModel):
    """Details about a denied claim."""

    claim_id: str
    patient_name: str
    patient_id: str
    service_date: str = Field(..., description="Date of service (YYYY-MM-DD)")
    payer_id: str
    payer_name: str
    denial_date: str = Field(..., description="Date claim was denied (YYYY-MM-DD)")
    denial_code: str = Field(..., description="Reason code from payer")
    denial_reason: str = Field(..., description="Human-readable denial reason")
    denied_amount: float
    service_codes: list[str] = Field(..., description="CPT/HCPCS codes that were denied")
    diagnosis_codes: list[str] = Field(..., description="ICD-10 codes submitted")
    clinical_notes: Optional[str] = Field(None, description="Clinical documentation supporting the service")
    prior_authorization_number: Optional[str] = None
    is_initial_denial: bool = Field(default=True, description="True if first denial, False if appeal was denied")


class DenialManagementInput(BaseModel):
    """Input for denial management agent."""

    denial: DenialDetails
    include_appeal_letter: bool = Field(default=True, description="Generate appeal letter draft")
    llm_provider: str = Field(default="anthropic", description="LLM provider for analysis: anthropic or openai")
    appeal_priority: Optional[str] = Field(None, description="high, medium, low (auto-calculated if not provided)")


class AppealRecommendation(BaseModel):
    """Recommendation on whether to appeal."""

    should_appeal: bool
    appeal_viability_score: float = Field(..., description="0.0-1.0, likelihood of successful appeal")
    appeal_priority: str = Field(..., description="high, medium, low")
    reasoning: str = Field(..., description="Why appeal should or should not be pursued")
    estimated_success_rate: str = Field(..., description="Percentage likelihood of success")
    estimated_effort: str = Field(..., description="low, medium, high")


class AppealStrategy(BaseModel):
    """Strategy for appealing the denial."""

    appeal_type: str = Field(..., description="standard, expedited, peer_to_peer")
    appeal_level: str = Field(..., description="first_level, second_level, external_review")
    key_arguments: list[str] = Field(..., description="Main arguments to include in appeal")
    required_documentation: list[str] = Field(..., description="Documents needed for appeal")
    clinical_justification: str = Field(..., description="Medical necessity justification")
    regulatory_citations: list[str] = Field(default_factory=list, description="Relevant regulations or policies")
    deadline: str = Field(..., description="Appeal submission deadline (YYYY-MM-DD)")


class AppealLetter(BaseModel):
    """Generated appeal letter."""

    letter_content: str = Field(..., description="Full appeal letter text")
    subject_line: str
    attachments_needed: list[str] = Field(default_factory=list)
    word_count: int


class DenialManagementOutput(BaseModel):
    """Output from denial management agent."""

    claim_id: str
    denial_analysis: str = Field(..., description="Analysis of why claim was denied")
    denial_category: str = Field(
        ...,
        description="technical, medical_necessity, authorization, coverage, timely_filing, coding, duplicate, other",
    )
    root_cause: str = Field(..., description="Root cause of the denial")
    recommendation: AppealRecommendation
    appeal_strategy: Optional[AppealStrategy] = None
    appeal_letter: Optional[AppealLetter] = None
    alternative_actions: list[str] = Field(
        default_factory=list, description="Alternative actions if appeal not recommended"
    )
    financial_impact: dict[str, float] = Field(..., description="Analysis of financial impact")


# Agent Implementation


class DenialManagementAgent(BaseAgent[DenialManagementInput, DenialManagementOutput]):
    """
    Denial Management Agent.

    Analyzes claim denials, determines appeal viability, and generates appeal documentation.
    Uses LLM for intelligent analysis of denial reasons and clinical justification.
    """

    def __init__(self, llm_provider: str = "anthropic"):
        super().__init__(
            agent_type="denial_management",
            agent_version="1.0.0",
            description="Analyze claim denials and automate appeals process",
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
        input_data: DenialManagementInput,
        context: dict[str, Any],
    ) -> tuple[DenialManagementOutput, float, dict[str, Any]]:
        """Execute denial management logic."""
        start_time = datetime.now()

        denial = input_data.denial

        # Step 1: Categorize the denial
        denial_category = self._categorize_denial(denial.denial_code, denial.denial_reason)

        # Step 2: Identify root cause
        root_cause = self._identify_root_cause(denial_category, denial)

        # Step 3: Analyze with LLM for deeper insights
        denial_analysis = await self._analyze_denial_with_llm(denial)

        # Step 4: Determine appeal viability
        recommendation = self._evaluate_appeal_viability(denial, denial_category, root_cause)

        # Step 5: Generate appeal strategy if recommended
        appeal_strategy = None
        if recommendation.should_appeal:
            appeal_strategy = self._generate_appeal_strategy(denial, denial_category, root_cause, recommendation)

        # Step 6: Generate appeal letter if requested and recommended
        appeal_letter = None
        if input_data.include_appeal_letter and recommendation.should_appeal and appeal_strategy:
            appeal_letter = await self._generate_appeal_letter(denial, denial_analysis, appeal_strategy)

        # Step 7: Identify alternative actions
        alternative_actions = self._identify_alternative_actions(denial, recommendation)

        # Step 8: Calculate financial impact
        financial_impact = self._calculate_financial_impact(denial, recommendation)

        # Step 9: Create output
        output = DenialManagementOutput(
            claim_id=denial.claim_id,
            denial_analysis=denial_analysis,
            denial_category=denial_category,
            root_cause=root_cause,
            recommendation=recommendation,
            appeal_strategy=appeal_strategy,
            appeal_letter=appeal_letter,
            alternative_actions=alternative_actions,
            financial_impact=financial_impact,
        )

        # Calculate confidence
        confidence = self._calculate_denial_management_confidence(output, denial)

        execution_time_ms = (datetime.now() - start_time).total_seconds() * 1000

        metadata = {
            "llm_provider": self.llm_provider,
            "denial_category": denial_category,
            "should_appeal": recommendation.should_appeal,
            "appeal_viability": recommendation.appeal_viability_score,
            "denied_amount": denial.denied_amount,
            "execution_time_ms": execution_time_ms,
        }

        return output, confidence, metadata

    def _categorize_denial(self, denial_code: str, denial_reason: str) -> str:
        """Categorize the denial based on code and reason."""
        denial_reason_lower = denial_reason.lower()
        code_prefix = denial_code[:2] if len(denial_code) >= 2 else ""

        # Common denial code patterns (simplified)
        if any(keyword in denial_reason_lower for keyword in ["medical necessity", "not medically necessary"]):
            return "medical_necessity"
        elif any(keyword in denial_reason_lower for keyword in ["authorization", "prior auth", "pre-auth"]):
            return "authorization"
        elif any(keyword in denial_reason_lower for keyword in ["coverage", "not covered", "benefit"]):
            return "coverage"
        elif any(keyword in denial_reason_lower for keyword in ["timely filing", "filing limit", "late"]):
            return "timely_filing"
        elif any(keyword in denial_reason_lower for keyword in ["code", "coding", "invalid code", "incorrect code"]):
            return "coding"
        elif any(keyword in denial_reason_lower for keyword in ["duplicate", "already paid", "previously processed"]):
            return "duplicate"
        elif any(keyword in denial_reason_lower for keyword in ["documentation", "missing information", "records"]):
            return "technical"
        else:
            return "other"

    def _identify_root_cause(self, denial_category: str, denial: DenialDetails) -> str:
        """Identify the root cause of the denial."""
        root_causes = {
            "medical_necessity": "Payer determined service was not medically necessary based on submitted documentation",
            "authorization": "Required prior authorization was not obtained before service was rendered",
            "coverage": "Service is not covered under patient's insurance plan or benefit limits exceeded",
            "timely_filing": "Claim was submitted after payer's filing deadline",
            "coding": "Incorrect, invalid, or unsupported procedure/diagnosis codes submitted",
            "duplicate": "Claim represents duplicate billing for same service previously paid",
            "technical": "Missing or incomplete documentation or administrative error in claim submission",
            "other": "Denial reason requires additional investigation",
        }

        base_cause = root_causes.get(denial_category, "Unknown denial reason")

        # Add specific details if available
        if denial.denial_reason:
            return f"{base_cause}. Specific reason: {denial.denial_reason}"

        return base_cause

    async def _analyze_denial_with_llm(self, denial: DenialDetails) -> str:
        """Use LLM to analyze the denial and provide insights."""
        prompt = f"""Analyze this insurance claim denial and provide a comprehensive analysis:

**Claim Details:**
- Patient: {denial.patient_name}
- Service Date: {denial.service_date}
- Payer: {denial.payer_name}
- Denial Date: {denial.denial_date}
- Denial Code: {denial.denial_code}
- Denial Reason: {denial.denial_reason}
- Denied Amount: ${denial.denied_amount}
- Service Codes: {', '.join(denial.service_codes)}
- Diagnosis Codes: {', '.join(denial.diagnosis_codes)}

{"**Clinical Notes:** " + denial.clinical_notes if denial.clinical_notes else ""}

Provide a brief analysis (2-3 paragraphs) covering:
1. What specifically caused this denial
2. Whether the denial appears justified or appealable
3. Key factors to consider in determining next steps
"""

        try:
            if self.llm_provider == "anthropic":
                response = await self.anthropic_client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=1000,
                    temperature=0.3,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text

            else:  # openai
                response = await self.openai_client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    max_tokens=1000,
                    temperature=0.3,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.choices[0].message.content

        except Exception as e:
            logger.error("llm_analysis_error", error=str(e), provider=self.llm_provider)
            return f"Analysis unavailable. Denial code {denial.denial_code}: {denial.denial_reason}"

    def _evaluate_appeal_viability(
        self, denial: DenialDetails, denial_category: str, root_cause: str
    ) -> AppealRecommendation:
        """Evaluate whether the denial should be appealed."""
        viability_score = 0.5  # Base score
        should_appeal = False
        reasoning_parts = []

        # Factor 1: Denial category (some categories have higher success rates)
        category_scores = {
            "medical_necessity": 0.7,  # Often successful with good documentation
            "authorization": 0.3,  # Harder to overturn, should have been obtained beforehand
            "coverage": 0.2,  # Usually policy-based, hard to appeal
            "timely_filing": 0.1,  # Very difficult to appeal
            "coding": 0.8,  # Often successful if correct codes provided
            "duplicate": 0.4,  # Can be overturned if truly different service
            "technical": 0.9,  # Usually successful with proper documentation
            "other": 0.5,
        }

        viability_score = category_scores.get(denial_category, 0.5)
        reasoning_parts.append(f"{denial_category.replace('_', ' ').title()} denials have ~{int(viability_score * 100)}% success rate")

        # Factor 2: Amount at stake
        if denial.denied_amount > 5000:
            viability_score += 0.1
            reasoning_parts.append(f"High-value claim (${denial.denied_amount:,.2f}) justifies appeal effort")
        elif denial.denied_amount < 500:
            viability_score -= 0.2
            reasoning_parts.append(f"Low-value claim (${denial.denied_amount:,.2f}) may not justify appeal costs")

        # Factor 3: Clinical documentation
        if denial.clinical_notes:
            viability_score += 0.1
            reasoning_parts.append("Clinical documentation available to support appeal")
        else:
            viability_score -= 0.2
            reasoning_parts.append("Lacking clinical documentation weakens appeal potential")

        # Factor 4: Prior authorization (if required)
        if denial_category == "authorization" and not denial.prior_authorization_number:
            viability_score -= 0.3
            reasoning_parts.append("No prior authorization obtained - difficult to appeal")

        # Factor 5: Initial vs repeat denial
        if not denial.is_initial_denial:
            viability_score -= 0.2
            reasoning_parts.append("Already appealed once - lower success rate for second appeal")

        # Normalize score
        viability_score = max(0.0, min(1.0, viability_score))

        # Decide if should appeal
        should_appeal = viability_score >= 0.6

        # Determine priority
        if viability_score >= 0.8 and denial.denied_amount > 1000:
            priority = "high"
        elif viability_score >= 0.6:
            priority = "medium"
        else:
            priority = "low"

        # Build reasoning
        if should_appeal:
            reasoning = "**Appeal Recommended.** " + ". ".join(reasoning_parts)
        else:
            reasoning = "**Appeal Not Recommended.** " + ". ".join(reasoning_parts)

        # Estimate success rate
        if viability_score >= 0.8:
            success_rate = "70-90%"
        elif viability_score >= 0.6:
            success_rate = "50-70%"
        elif viability_score >= 0.4:
            success_rate = "30-50%"
        else:
            success_rate = "10-30%"

        # Estimate effort
        if denial_category in ["technical", "coding"]:
            effort = "low"
        elif denial_category in ["medical_necessity", "duplicate"]:
            effort = "medium"
        else:
            effort = "high"

        return AppealRecommendation(
            should_appeal=should_appeal,
            appeal_viability_score=viability_score,
            appeal_priority=priority,
            reasoning=reasoning,
            estimated_success_rate=success_rate,
            estimated_effort=effort,
        )

    def _generate_appeal_strategy(
        self,
        denial: DenialDetails,
        denial_category: str,
        root_cause: str,
        recommendation: AppealRecommendation,
    ) -> AppealStrategy:
        """Generate a strategy for appealing the denial."""
        # Determine appeal type
        if denial.denied_amount > 10000 or denial_category == "medical_necessity":
            appeal_type = "peer_to_peer"  # Request peer-to-peer review
        elif recommendation.appeal_priority == "high":
            appeal_type = "expedited"
        else:
            appeal_type = "standard"

        # Determine appeal level
        appeal_level = "second_level" if not denial.is_initial_denial else "first_level"

        # Generate key arguments based on denial category
        key_arguments = self._generate_key_arguments(denial, denial_category)

        # Identify required documentation
        required_docs = self._identify_required_documentation(denial, denial_category)

        # Generate clinical justification
        clinical_justification = self._generate_clinical_justification(denial, denial_category)

        # Identify relevant regulations
        regulatory_citations = self._identify_regulatory_citations(denial_category, denial.payer_name)

        # Calculate deadline (typically 180 days from denial, but varies)
        denial_date = datetime.strptime(denial.denial_date, "%Y-%m-%d")
        deadline = (denial_date + timedelta(days=180)).strftime("%Y-%m-%d")

        return AppealStrategy(
            appeal_type=appeal_type,
            appeal_level=appeal_level,
            key_arguments=key_arguments,
            required_documentation=required_docs,
            clinical_justification=clinical_justification,
            regulatory_citations=regulatory_citations,
            deadline=deadline,
        )

    def _generate_key_arguments(self, denial: DenialDetails, denial_category: str) -> list[str]:
        """Generate key arguments for the appeal."""
        arguments = []

        if denial_category == "medical_necessity":
            arguments.extend([
                "Service meets established clinical guidelines and standards of care",
                "Patient's condition warranted the level of service provided",
                "Treatment was appropriate and necessary based on clinical presentation",
            ])
        elif denial_category == "coding":
            arguments.extend([
                "Correct procedure and diagnosis codes accurately reflect services rendered",
                "Coding is supported by clinical documentation in medical record",
                "Services billed are separate and distinct from other procedures",
            ])
        elif denial_category == "technical":
            arguments.extend([
                "All required documentation is included with this appeal",
                "Denial was based on administrative error, not clinical grounds",
                "Claim meets all payer requirements for reimbursement",
            ])
        elif denial_category == "authorization":
            arguments.extend([
                "Service met criteria for emergency/urgent care exception",
                "Prior authorization was clinically impractical given circumstances",
                "Retrospective authorization should be granted based on medical necessity",
            ])

        return arguments

    def _identify_required_documentation(self, denial: DenialDetails, denial_category: str) -> list[str]:
        """Identify documentation needed for appeal."""
        docs = [
            "Complete medical records from date of service",
            "Original claim submission with all attachments",
            "Denial letter from payer",
        ]

        if denial_category == "medical_necessity":
            docs.extend([
                "Clinical notes demonstrating medical necessity",
                "Relevant diagnostic test results",
                "Treatment plan and progress notes",
                "Peer-reviewed literature supporting treatment",
            ])
        elif denial_category == "coding":
            docs.extend([
                "Operative report or procedure notes",
                "CPT/ICD-10 coding rationale",
            ])
        elif denial_category == "authorization":
            docs.extend([
                "Documentation of emergency circumstances (if applicable)",
                "Communication attempts with payer for authorization",
            ])

        return docs

    def _generate_clinical_justification(self, denial: DenialDetails, denial_category: str) -> str:
        """Generate clinical justification text."""
        if denial_category == "medical_necessity":
            return (
                f"The services provided on {denial.service_date} were medically necessary and appropriate "
                f"for the patient's condition as documented by diagnosis codes {', '.join(denial.diagnosis_codes)}. "
                f"The treatment rendered was consistent with clinical standards of care and was the least costly "
                f"appropriate level of care needed to address the patient's medical needs."
            )
        elif denial_category == "coding":
            return (
                f"The procedure codes {', '.join(denial.service_codes)} accurately represent the services "
                f"rendered on {denial.service_date}. These codes are supported by the clinical documentation "
                f"and appropriately describe the work performed."
            )
        else:
            return (
                f"The services billed under codes {', '.join(denial.service_codes)} were appropriate "
                f"and necessary for the treatment of the patient's condition."
            )

    def _identify_regulatory_citations(self, denial_category: str, payer_name: str) -> list[str]:
        """Identify relevant regulatory citations."""
        citations = []

        # Add relevant citations based on category
        if "Medicare" in payer_name or "CMS" in payer_name:
            citations.append("Medicare Claims Processing Manual, Chapter 23")
            if denial_category == "medical_necessity":
                citations.append("42 CFR § 411.15 - Particular services excluded from coverage")

        if denial_category == "timely_filing":
            citations.append("Payer's provider contract - Timely filing provisions")

        return citations

    async def _generate_appeal_letter(
        self, denial: DenialDetails, analysis: str, strategy: AppealStrategy
    ) -> AppealLetter:
        """Generate appeal letter using LLM."""
        prompt = f"""Generate a professional appeal letter for a denied insurance claim. Use formal business letter format.

**Claim Information:**
- Claim ID: {denial.claim_id}
- Patient: {denial.patient_name}
- Service Date: {denial.service_date}
- Payer: {denial.payer_name}
- Denied Amount: ${denial.denied_amount}
- Denial Code: {denial.denial_code}
- Denial Reason: {denial.denial_reason}

**Appeal Strategy:**
- Appeal Type: {strategy.appeal_type}
- Key Arguments: {'; '.join(strategy.key_arguments)}
- Clinical Justification: {strategy.clinical_justification}

**Analysis:**
{analysis}

Generate a professional appeal letter that:
1. Clearly states this is a formal appeal
2. References the claim and denial details
3. Presents the key arguments systematically
4. Includes clinical justification
5. Requests specific action (overturn denial and process payment)
6. Is professional, concise, and persuasive
7. Is 500-800 words

Do not include sender/recipient addresses or dates (those will be added separately).
Start directly with the letter content.
"""

        try:
            if self.llm_provider == "anthropic":
                response = await self.anthropic_client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=2000,
                    temperature=0.5,
                    messages=[{"role": "user", "content": prompt}],
                )
                letter_content = response.content[0].text

            else:  # openai
                response = await self.openai_client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    max_tokens=2000,
                    temperature=0.5,
                    messages=[{"role": "user", "content": prompt}],
                )
                letter_content = response.choices[0].message.content

            word_count = len(letter_content.split())

            return AppealLetter(
                letter_content=letter_content,
                subject_line=f"APPEAL - Claim #{denial.claim_id} - {denial.patient_name}",
                attachments_needed=strategy.required_documentation,
                word_count=word_count,
            )

        except Exception as e:
            logger.error("appeal_letter_generation_error", error=str(e))
            # Return template letter
            return AppealLetter(
                letter_content="[Appeal letter template - LLM generation failed]",
                subject_line=f"APPEAL - Claim #{denial.claim_id}",
                attachments_needed=strategy.required_documentation,
                word_count=0,
            )

    def _identify_alternative_actions(
        self, denial: DenialDetails, recommendation: AppealRecommendation
    ) -> list[str]:
        """Identify alternative actions if appeal not recommended."""
        actions = []

        if not recommendation.should_appeal:
            actions.append("Accept denial and adjust patient account")
            actions.append("Review billing processes to prevent future denials")

            if denial.denied_amount > 1000:
                actions.append("Consider negotiating payment plan with patient")

        else:
            actions.append("Monitor appeal status and follow up if no response within 30 days")
            actions.append("Document denial patterns for this payer to inform future submissions")

        return actions

    def _calculate_financial_impact(
        self, denial: DenialDetails, recommendation: AppealRecommendation
    ) -> dict[str, float]:
        """Calculate financial impact of denial and potential appeal."""
        appeal_cost_estimate = 150.0  # Estimated administrative cost to file appeal

        if recommendation.should_appeal:
            # Expected value = (denied amount * success probability) - appeal cost
            success_probability = recommendation.appeal_viability_score
            expected_recovery = denial.denied_amount * success_probability
            net_expected_value = expected_recovery - appeal_cost_estimate
        else:
            expected_recovery = 0.0
            net_expected_value = -appeal_cost_estimate  # Cost without benefit

        return {
            "denied_amount": denial.denied_amount,
            "appeal_cost_estimate": appeal_cost_estimate,
            "expected_recovery": expected_recovery,
            "net_expected_value": net_expected_value,
            "roi_percentage": (net_expected_value / appeal_cost_estimate * 100) if appeal_cost_estimate > 0 else 0,
        }

    def _calculate_denial_management_confidence(
        self, output: DenialManagementOutput, denial: DenialDetails
    ) -> float:
        """Calculate confidence in denial management recommendations."""
        confidence = 0.8  # Base confidence

        # Increase confidence for clear-cut cases
        if output.denial_category in ["coding", "technical", "duplicate"]:
            confidence += 0.1  # These are usually straightforward

        # Decrease confidence for ambiguous cases
        if output.denial_category == "other":
            confidence -= 0.2

        # Decrease confidence if missing clinical notes
        if not denial.clinical_notes and output.denial_category == "medical_necessity":
            confidence -= 0.15

        # Increase confidence for LLM-analyzed cases (if analysis succeeded)
        if len(output.denial_analysis) > 100:
            confidence += 0.05

        return max(0.0, min(1.0, confidence))

    def _determine_review_needed(
        self,
        output: DenialManagementOutput,
        confidence: float,
        input_data: DenialManagementInput,
    ) -> tuple[bool, Optional[str]]:
        """Determine if human review is needed."""
        # High-value denials always need review
        if input_data.denial.denied_amount > 5000:
            return True, f"High-value denial (${input_data.denial.denied_amount:,.2f})"

        # Appeal recommendations need review before filing
        if output.recommendation.should_appeal and output.recommendation.appeal_priority == "high":
            return True, "High-priority appeal recommended"

        # Low confidence cases need review
        if confidence < 0.6:
            return True, f"Low confidence ({confidence:.2f})"

        # Medical necessity denials need clinical review
        if output.denial_category == "medical_necessity":
            return True, "Medical necessity denial requires clinical review"

        return False, None
