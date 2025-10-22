"""
Medical Coding Agent

Automatically extracts CPT (procedure) and ICD (diagnosis) codes from clinical documentation
using LLM-based natural language processing.

This agent:
1. Takes clinical notes, visit summaries, or encounter documentation
2. Uses OpenAI/Anthropic to analyze the text and extract relevant codes
3. Returns structured CPT and ICD code recommendations
4. Provides confidence scores and justifications
5. Flags low-confidence extractions for human review
"""

from datetime import datetime
from typing import Any, Optional

from anthropic import Anthropic
from openai import OpenAI
from pydantic import BaseModel, Field

from platform_core.agent_orchestration.base_agent import BaseAgent
from platform_core.config import get_config
from platform_core.shared_services.tenant_context import get_tenant_context

config = get_config()


class CPTCode(BaseModel):
    """CPT (Current Procedural Terminology) code."""

    code: str = Field(..., description="CPT code (e.g., 99213)")
    description: str = Field(..., description="Description of the procedure")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in this code")
    justification: str = Field(..., description="Why this code was selected")
    modifier: Optional[str] = Field(default=None, description="CPT modifier if applicable")


class ICDCode(BaseModel):
    """ICD (International Classification of Diseases) code."""

    code: str = Field(..., description="ICD-10 code (e.g., F41.1)")
    description: str = Field(..., description="Description of the diagnosis")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in this code")
    justification: str = Field(..., description="Why this code was selected")
    is_primary: bool = Field(default=False, description="Is this the primary diagnosis?")


class MedicalCodingInput(BaseModel):
    """Input for medical coding agent."""

    # Clinical documentation
    clinical_notes: str = Field(..., description="Clinical notes from the encounter")
    visit_type: str = Field(
        ..., description="Type of visit (e.g., office visit, telehealth, procedure)"
    )
    specialty: str = Field(
        default="general", description="Medical specialty (e.g., psychiatry, primary care)"
    )

    # Patient context (optional, helps with coding)
    patient_age: Optional[int] = Field(default=None)
    is_new_patient: bool = Field(default=False, description="Is this a new patient?")
    visit_duration_minutes: Optional[int] = Field(default=None)

    # Additional context
    procedures_performed: Optional[list[str]] = Field(
        default=None, description="List of procedures performed"
    )
    diagnosis_mentioned: Optional[list[str]] = Field(
        default=None, description="Diagnoses mentioned by clinician"
    )


class MedicalCodingOutput(BaseModel):
    """Output from medical coding agent."""

    # Extracted codes
    cpt_codes: list[CPTCode] = Field(default_factory=list, description="CPT procedure codes")
    icd_codes: list[ICDCode] = Field(default_factory=list, description="ICD diagnosis codes")

    # Summary
    coding_summary: str = Field(..., description="Summary of the coding rationale")
    total_codes: int = Field(default=0, description="Total number of codes recommended")

    # Quality indicators
    average_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Average confidence across all codes"
    )
    requires_review: bool = Field(
        default=False, description="Does this require coder review?"
    )
    review_reasons: list[str] = Field(
        default_factory=list, description="Reasons why review is needed"
    )

    # Billing estimates
    estimated_rvu: Optional[float] = Field(
        default=None, description="Estimated Relative Value Units"
    )
    complexity_level: Optional[str] = Field(
        default=None, description="Visit complexity (e.g., Level 3, Level 4)"
    )


class MedicalCodingAgent(BaseAgent[MedicalCodingInput, MedicalCodingOutput]):
    """
    Agent that extracts medical codes from clinical documentation using LLM.

    Uses OpenAI GPT-4 or Anthropic Claude for natural language understanding.
    """

    def __init__(self, llm_provider: str = "anthropic"):
        """
        Initialize medical coding agent.

        Args:
            llm_provider: LLM provider to use ("openai" or "anthropic")
        """
        super().__init__(
            agent_type="medical_coding",
            agent_version="1.0.0",
            max_retries=2,
            timeout_seconds=60,  # Longer timeout for LLM processing
        )
        self.llm_provider = llm_provider

        # Initialize LLM client
        if llm_provider == "openai":
            self.openai_client = OpenAI(api_key=config.openai_api_key)
        elif llm_provider == "anthropic":
            self.anthropic_client = Anthropic(api_key=config.anthropic_api_key)
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_provider}")

    async def _execute_internal(
        self,
        input_data: MedicalCodingInput,
        context: dict[str, Any],
    ) -> tuple[MedicalCodingOutput, float, dict[str, Any]]:
        """
        Execute medical coding extraction.

        Args:
            input_data: Clinical documentation and context
            context: Execution context

        Returns:
            Tuple of (output, confidence, metrics)
        """
        # Track metrics
        api_calls_made = 0
        tokens_used = 0
        cost_usd = 0.0

        try:
            # Build prompt for LLM
            prompt = self._build_coding_prompt(input_data)

            # Call LLM to extract codes
            llm_response, tokens, cost = await self._call_llm(prompt)
            api_calls_made += 1
            tokens_used += tokens
            cost_usd += cost

            # Parse LLM response into structured codes
            output = self._parse_llm_response(llm_response, input_data)

            # Calculate overall confidence
            confidence = self._calculate_overall_confidence(output)

            # Determine if review is needed
            output.requires_review, output.review_reasons = self._needs_review(output)

            metrics = {
                "api_calls_made": api_calls_made,
                "tokens_used": tokens_used,
                "cost_usd": cost_usd,
            }

            return output, confidence, metrics

        except Exception as e:
            self.logger.error("medical_coding_error", error=str(e))

            # Return empty output with error
            output = MedicalCodingOutput(
                cpt_codes=[],
                icd_codes=[],
                coding_summary=f"Error during coding: {str(e)}",
                requires_review=True,
                review_reasons=[f"Agent error: {str(e)}"],
            )

            metrics = {
                "api_calls_made": api_calls_made,
                "tokens_used": tokens_used,
                "cost_usd": cost_usd,
            }

            return output, 0.0, metrics

    def _build_coding_prompt(self, input_data: MedicalCodingInput) -> str:
        """
        Build prompt for LLM to extract medical codes.

        Args:
            input_data: Clinical documentation

        Returns:
            Formatted prompt
        """
        prompt = f"""You are an expert medical coder. Analyze the following clinical documentation and extract appropriate CPT (procedure) and ICD-10 (diagnosis) codes.

# Clinical Documentation

**Visit Type**: {input_data.visit_type}
**Specialty**: {input_data.specialty}
**New Patient**: {"Yes" if input_data.is_new_patient else "No"}
"""

        if input_data.patient_age:
            prompt += f"**Patient Age**: {input_data.patient_age}\n"

        if input_data.visit_duration_minutes:
            prompt += f"**Visit Duration**: {input_data.visit_duration_minutes} minutes\n"

        prompt += f"\n**Clinical Notes**:\n{input_data.clinical_notes}\n"

        if input_data.procedures_performed:
            prompt += f"\n**Procedures Mentioned**: {', '.join(input_data.procedures_performed)}\n"

        if input_data.diagnosis_mentioned:
            prompt += f"\n**Diagnoses Mentioned**: {', '.join(input_data.diagnosis_mentioned)}\n"

        prompt += """

# Task

Extract and recommend:
1. **CPT Codes**: Procedure codes for services rendered
2. **ICD-10 Codes**: Diagnosis codes for conditions addressed

For each code, provide:
- The code number
- Description
- Confidence score (0.0 to 1.0)
- Justification for selecting this code

# Output Format

Return a JSON object with this structure:
```json
{
  "cpt_codes": [
    {
      "code": "99213",
      "description": "Office visit, established patient, level 3",
      "confidence": 0.95,
      "justification": "20-minute visit with established patient discussing chronic conditions",
      "modifier": null
    }
  ],
  "icd_codes": [
    {
      "code": "F41.1",
      "description": "Generalized anxiety disorder",
      "confidence": 0.90,
      "justification": "Patient presents with anxiety symptoms as documented",
      "is_primary": true
    }
  ],
  "coding_summary": "Brief summary of coding rationale",
  "complexity_level": "Level 3"
}
```

# Guidelines

- Use current CPT and ICD-10 codes
- Consider visit complexity and time spent
- Flag low-confidence codes (< 0.7)
- Include only codes supported by documentation
- Primary diagnosis should have is_primary: true

Return ONLY the JSON object, no other text."""

        return prompt

    async def _call_llm(self, prompt: str) -> tuple[str, int, float]:
        """
        Call LLM to extract codes.

        Args:
            prompt: Formatted prompt

        Returns:
            Tuple of (response_text, tokens_used, cost_usd)
        """
        if self.llm_provider == "anthropic":
            # Use Claude for medical coding
            response = self.anthropic_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=2000,
                temperature=0.2,  # Low temperature for consistency
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = response.content[0].text
            tokens_used = response.usage.input_tokens + response.usage.output_tokens

            # Estimate cost (Claude 3.5 Sonnet: $3/M input, $15/M output)
            input_cost = (response.usage.input_tokens / 1_000_000) * 3.0
            output_cost = (response.usage.output_tokens / 1_000_000) * 15.0
            cost_usd = input_cost + output_cost

            return response_text, tokens_used, cost_usd

        elif self.llm_provider == "openai":
            # Use GPT-4 for medical coding
            response = self.openai_client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2000,
            )

            response_text = response.choices[0].message.content
            tokens_used = response.usage.total_tokens

            # Estimate cost (GPT-4 Turbo: $10/M input, $30/M output)
            # Rough estimate: assume 60/40 split
            cost_usd = (tokens_used / 1_000_000) * 20.0  # Average

            return response_text, tokens_used, cost_usd

        else:
            raise ValueError(f"Unsupported LLM provider: {self.llm_provider}")

    def _parse_llm_response(
        self, llm_response: str, input_data: MedicalCodingInput
    ) -> MedicalCodingOutput:
        """
        Parse LLM response into structured output.

        Args:
            llm_response: Raw LLM response
            input_data: Original input (for context)

        Returns:
            Structured medical coding output
        """
        import json

        try:
            # Extract JSON from response (LLM may include extra text)
            json_start = llm_response.find("{")
            json_end = llm_response.rfind("}") + 1

            if json_start == -1 or json_end == 0:
                raise ValueError("No JSON found in LLM response")

            json_str = llm_response[json_start:json_end]
            parsed = json.loads(json_str)

            # Build CPT codes
            cpt_codes = [
                CPTCode(
                    code=code.get("code", ""),
                    description=code.get("description", ""),
                    confidence=code.get("confidence", 0.5),
                    justification=code.get("justification", ""),
                    modifier=code.get("modifier"),
                )
                for code in parsed.get("cpt_codes", [])
            ]

            # Build ICD codes
            icd_codes = [
                ICDCode(
                    code=code.get("code", ""),
                    description=code.get("description", ""),
                    confidence=code.get("confidence", 0.5),
                    justification=code.get("justification", ""),
                    is_primary=code.get("is_primary", False),
                )
                for code in parsed.get("icd_codes", [])
            ]

            # Calculate average confidence
            all_confidences = [c.confidence for c in cpt_codes] + [
                c.confidence for c in icd_codes
            ]
            avg_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0.0

            output = MedicalCodingOutput(
                cpt_codes=cpt_codes,
                icd_codes=icd_codes,
                coding_summary=parsed.get("coding_summary", "Codes extracted from documentation"),
                total_codes=len(cpt_codes) + len(icd_codes),
                average_confidence=avg_confidence,
                complexity_level=parsed.get("complexity_level"),
            )

            return output

        except Exception as e:
            self.logger.error("llm_response_parse_error", error=str(e), response=llm_response[:200])

            # Return empty output
            return MedicalCodingOutput(
                cpt_codes=[],
                icd_codes=[],
                coding_summary=f"Failed to parse LLM response: {str(e)}",
                requires_review=True,
                review_reasons=[f"Parse error: {str(e)}"],
            )

    def _calculate_overall_confidence(self, output: MedicalCodingOutput) -> float:
        """
        Calculate overall confidence for the coding result.

        Args:
            output: Medical coding output

        Returns:
            Overall confidence score (0.0 to 1.0)
        """
        if output.total_codes == 0:
            return 0.0

        # Start with average confidence
        confidence = output.average_confidence

        # Adjust based on factors
        if output.total_codes < 2:
            # Very few codes might indicate missing documentation
            confidence *= 0.9

        if output.total_codes > 10:
            # Many codes might indicate complexity or uncertainty
            confidence *= 0.95

        # Check if primary diagnosis is present
        has_primary = any(code.is_primary for code in output.icd_codes)
        if not has_primary and output.icd_codes:
            confidence *= 0.85

        # Ensure confidence stays in valid range
        return max(0.0, min(1.0, confidence))

    def _needs_review(self, output: MedicalCodingOutput) -> tuple[bool, list[str]]:
        """
        Determine if coding result needs human review.

        Args:
            output: Medical coding output

        Returns:
            Tuple of (needs_review, reasons)
        """
        needs_review = False
        reasons = []

        # Check if no codes were extracted
        if output.total_codes == 0:
            needs_review = True
            reasons.append("No codes extracted from documentation")

        # Check for low-confidence codes
        low_confidence_codes = [
            code
            for code in (output.cpt_codes + output.icd_codes)
            if code.confidence < 0.7
        ]
        if low_confidence_codes:
            needs_review = True
            reasons.append(
                f"{len(low_confidence_codes)} code(s) with confidence < 0.7"
            )

        # Check if average confidence is low
        if output.average_confidence < 0.75:
            needs_review = True
            reasons.append(f"Low average confidence: {output.average_confidence:.2f}")

        # Check if no primary diagnosis
        has_primary = any(code.is_primary for code in output.icd_codes)
        if output.icd_codes and not has_primary:
            needs_review = True
            reasons.append("No primary diagnosis identified")

        # Check for too many codes (might indicate over-coding)
        if output.total_codes > 15:
            needs_review = True
            reasons.append(f"High code count ({output.total_codes}) - possible over-coding")

        return needs_review, reasons
