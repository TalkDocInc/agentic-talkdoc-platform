"""
Smart Scheduling Agent

Intelligently matches patients with available clinicians based on:
- Specialty and clinical needs
- Insurance compatibility
- Clinician availability
- Patient preferences (location, gender, language)
- Historical match quality
"""

from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field
from structlog import get_logger

from platform_core.agent_orchestration.base_agent import BaseAgent

logger = get_logger()


# Input/Output Models


class PatientPreferences(BaseModel):
    """Patient scheduling preferences."""

    preferred_gender: Optional[str] = Field(None, description="male, female, no_preference")
    preferred_language: Optional[str] = Field(None, description="Language code (e.g., 'en', 'es')")
    max_distance_miles: Optional[float] = Field(None, description="Maximum distance from patient")
    preferred_modality: Optional[str] = Field(None, description="in_person, telehealth, hybrid")
    preferred_time_slots: list[str] = Field(
        default_factory=list, description="Preferred time slots (e.g., 'morning', 'afternoon', 'evening')"
    )
    preferred_days: list[str] = Field(
        default_factory=list, description="Preferred days (e.g., 'monday', 'tuesday')"
    )
    previous_clinician_id: Optional[str] = Field(None, description="ID of previously seen clinician (continuity)")


class ClinicianAvailability(BaseModel):
    """Clinician availability information."""

    clinician_id: str
    full_name: str
    specialty: str
    sub_specialty: Optional[str] = None
    gender: str
    languages: list[str] = Field(default_factory=list)
    license_states: list[str] = Field(default_factory=list)
    accepted_insurance_payers: list[str] = Field(default_factory=list)
    location_city: Optional[str] = None
    location_state: Optional[str] = None
    distance_from_patient_miles: Optional[float] = None
    offers_telehealth: bool = True
    offers_in_person: bool = False
    available_slots: list[dict[str, Any]] = Field(
        ..., description="Available time slots with start_time, end_time, modality"
    )
    rating: Optional[float] = Field(None, description="Average clinician rating (1.0-5.0)")
    total_patients_seen: Optional[int] = Field(None, description="Total patients seen (experience indicator)")
    next_available_date: Optional[str] = Field(None, description="Next available appointment date (YYYY-MM-DD)")


class SmartSchedulingInput(BaseModel):
    """Input for smart scheduling agent."""

    patient_id: str
    patient_location_city: Optional[str] = None
    patient_location_state: str = Field(..., description="Required for telehealth license verification")
    patient_insurance_payer_id: Optional[str] = Field(None, description="Insurance payer ID (e.g., 'AETNA')")
    specialty_required: str = Field(..., description="Required specialty (e.g., 'psychiatry', 'therapy')")
    sub_specialty_preferred: Optional[str] = Field(
        None, description="Preferred sub-specialty (e.g., 'child_psychiatry', 'trauma_therapy')"
    )
    clinical_reason: str = Field(..., description="Reason for visit (helps with matching)")
    urgency_level: str = Field(
        default="routine", description="routine, urgent, emergency - affects scheduling window"
    )
    patient_preferences: PatientPreferences = Field(default_factory=PatientPreferences)
    available_clinicians: list[ClinicianAvailability] = Field(..., description="List of available clinicians to match")
    max_matches: int = Field(default=5, description="Maximum number of matches to return")


class ClinicianMatch(BaseModel):
    """A matched clinician with scoring details."""

    clinician_id: str
    full_name: str
    specialty: str
    sub_specialty: Optional[str] = None
    match_score: float = Field(..., description="Overall match score (0.0-1.0)")
    match_reasons: list[str] = Field(..., description="Reasons why this is a good match")
    potential_concerns: list[str] = Field(default_factory=list, description="Potential concerns or limitations")
    recommended_appointment: Optional[dict[str, Any]] = Field(
        None, description="Recommended appointment slot with start_time, end_time, modality"
    )
    distance_miles: Optional[float] = None
    insurance_accepted: bool
    next_available_date: str = Field(..., description="Next available date (YYYY-MM-DD)")
    rating: Optional[float] = None


class SmartSchedulingOutput(BaseModel):
    """Output from smart scheduling agent."""

    matched_clinicians: list[ClinicianMatch] = Field(..., description="Ranked list of matched clinicians")
    total_clinicians_evaluated: int
    top_match_score: float = Field(..., description="Score of the best match")
    scheduling_recommendation: str = Field(..., description="Human-readable recommendation")
    no_match_reason: Optional[str] = Field(None, description="Reason if no suitable matches found")


# Agent Implementation


class SmartSchedulingAgent(BaseAgent[SmartSchedulingInput, SmartSchedulingOutput]):
    """
    Smart Scheduling Agent.

    Intelligently matches patients with clinicians using a multi-factor scoring algorithm
    that considers clinical fit, availability, insurance, location, and patient preferences.
    """

    def __init__(self):
        super().__init__(
            agent_type="smart_scheduling",
            agent_version="1.0.0",
            description="Intelligent patient-clinician matching for optimal appointment scheduling",
        )

    async def _execute_internal(
        self,
        input_data: SmartSchedulingInput,
        context: dict[str, Any],
    ) -> tuple[SmartSchedulingOutput, float, dict[str, Any]]:
        """Execute smart scheduling logic."""
        start_time = datetime.now()

        # Step 1: Filter clinicians by hard requirements
        eligible_clinicians = self._filter_eligible_clinicians(input_data)

        if not eligible_clinicians:
            # No eligible clinicians found
            output = SmartSchedulingOutput(
                matched_clinicians=[],
                total_clinicians_evaluated=len(input_data.available_clinicians),
                top_match_score=0.0,
                scheduling_recommendation="No suitable clinicians found matching the requirements.",
                no_match_reason=self._determine_no_match_reason(input_data),
            )
            return output, 0.0, {"no_matches": True}

        # Step 2: Score each eligible clinician
        scored_matches = []
        for clinician in eligible_clinicians:
            match_score, match_reasons, concerns = self._score_clinician_match(input_data, clinician)

            # Find best appointment slot
            recommended_appointment = self._find_best_appointment_slot(
                clinician, input_data.patient_preferences, input_data.urgency_level
            )

            match = ClinicianMatch(
                clinician_id=clinician.clinician_id,
                full_name=clinician.full_name,
                specialty=clinician.specialty,
                sub_specialty=clinician.sub_specialty,
                match_score=match_score,
                match_reasons=match_reasons,
                potential_concerns=concerns,
                recommended_appointment=recommended_appointment,
                distance_miles=clinician.distance_from_patient_miles,
                insurance_accepted=self._check_insurance_accepted(input_data, clinician),
                next_available_date=clinician.next_available_date or "Unknown",
                rating=clinician.rating,
            )
            scored_matches.append(match)

        # Step 3: Sort by match score and limit results
        scored_matches.sort(key=lambda x: x.match_score, reverse=True)
        top_matches = scored_matches[: input_data.max_matches]

        # Step 4: Generate recommendation
        recommendation = self._generate_recommendation(top_matches, input_data)

        output = SmartSchedulingOutput(
            matched_clinicians=top_matches,
            total_clinicians_evaluated=len(input_data.available_clinicians),
            top_match_score=top_matches[0].match_score if top_matches else 0.0,
            scheduling_recommendation=recommendation,
        )

        # Calculate confidence
        confidence = self._calculate_scheduling_confidence(input_data, top_matches)

        execution_time_ms = (datetime.now() - start_time).total_seconds() * 1000

        metadata = {
            "total_clinicians": len(input_data.available_clinicians),
            "eligible_clinicians": len(eligible_clinicians),
            "matches_returned": len(top_matches),
            "top_match_score": output.top_match_score,
            "specialty": input_data.specialty_required,
            "urgency": input_data.urgency_level,
            "execution_time_ms": execution_time_ms,
        }

        return output, confidence, metadata

    def _filter_eligible_clinicians(self, input_data: SmartSchedulingInput) -> list[ClinicianAvailability]:
        """Filter clinicians by hard requirements (specialty, license, availability)."""
        eligible = []

        for clinician in input_data.available_clinicians:
            # Check specialty match
            if clinician.specialty.lower() != input_data.specialty_required.lower():
                continue

            # Check license state (for telehealth)
            if input_data.patient_location_state not in clinician.license_states:
                continue

            # Check has available slots
            if not clinician.available_slots:
                continue

            # Check urgency requirements
            if input_data.urgency_level == "urgent":
                # For urgent, need appointment within 3 days
                if clinician.next_available_date:
                    next_date = datetime.strptime(clinician.next_available_date, "%Y-%m-%d")
                    if (next_date - datetime.now()).days > 3:
                        continue
            elif input_data.urgency_level == "emergency":
                # For emergency, need same-day appointment
                if clinician.next_available_date:
                    next_date = datetime.strptime(clinician.next_available_date, "%Y-%m-%d")
                    if next_date.date() != datetime.now().date():
                        continue

            eligible.append(clinician)

        return eligible

    def _score_clinician_match(
        self, input_data: SmartSchedulingInput, clinician: ClinicianAvailability
    ) -> tuple[float, list[str], list[str]]:
        """
        Score a clinician match using multiple factors.

        Returns: (match_score, match_reasons, potential_concerns)
        """
        score = 0.0
        reasons = []
        concerns = []

        # Factor 1: Specialty match (20 points max)
        score += 15  # Base for matching specialty
        reasons.append(f"Specializes in {clinician.specialty}")

        if input_data.sub_specialty_preferred and clinician.sub_specialty:
            if clinician.sub_specialty.lower() == input_data.sub_specialty_preferred.lower():
                score += 5
                reasons.append(f"Sub-specialty match: {clinician.sub_specialty}")

        # Factor 2: Insurance (20 points max)
        insurance_accepted = self._check_insurance_accepted(input_data, clinician)
        if insurance_accepted:
            score += 20
            reasons.append("Accepts patient's insurance")
        elif input_data.patient_insurance_payer_id:
            concerns.append("Insurance not accepted - patient may pay out-of-pocket")

        # Factor 3: Availability (15 points max)
        if clinician.next_available_date:
            days_until_available = (
                datetime.strptime(clinician.next_available_date, "%Y-%m-%d") - datetime.now()
            ).days
            if days_until_available == 0:
                score += 15
                reasons.append("Available today")
            elif days_until_available <= 3:
                score += 12
                reasons.append("Available within 3 days")
            elif days_until_available <= 7:
                score += 10
                reasons.append("Available within 1 week")
            elif days_until_available <= 14:
                score += 7
                reasons.append("Available within 2 weeks")
            else:
                score += 3
                concerns.append(f"Next availability: {clinician.next_available_date}")

        # Factor 4: Patient preferences (20 points max)
        prefs = input_data.patient_preferences

        # Gender preference
        if prefs.preferred_gender and prefs.preferred_gender != "no_preference":
            if clinician.gender.lower() == prefs.preferred_gender.lower():
                score += 5
                reasons.append(f"Matches gender preference: {clinician.gender}")

        # Language preference
        if prefs.preferred_language:
            if prefs.preferred_language in clinician.languages:
                score += 5
                reasons.append(f"Speaks {prefs.preferred_language}")
            else:
                concerns.append(f"May not speak {prefs.preferred_language}")

        # Location/distance preference
        if prefs.max_distance_miles and clinician.distance_from_patient_miles:
            if clinician.distance_from_patient_miles <= prefs.max_distance_miles:
                score += 5
                reasons.append(f"Within {prefs.max_distance_miles} miles")
            else:
                concerns.append(f"Distance: {clinician.distance_from_patient_miles:.1f} miles")

        # Modality preference
        if prefs.preferred_modality:
            if prefs.preferred_modality == "telehealth" and clinician.offers_telehealth:
                score += 5
                reasons.append("Offers telehealth")
            elif prefs.preferred_modality == "in_person" and clinician.offers_in_person:
                score += 5
                reasons.append("Offers in-person visits")
            elif prefs.preferred_modality == "hybrid" and clinician.offers_telehealth and clinician.offers_in_person:
                score += 5
                reasons.append("Offers both telehealth and in-person")

        # Factor 5: Clinician quality (15 points max)
        if clinician.rating:
            # Rating on 1-5 scale, normalize to 15 points
            rating_score = (clinician.rating / 5.0) * 15
            score += rating_score
            if clinician.rating >= 4.5:
                reasons.append(f"Highly rated ({clinician.rating:.1f}/5.0)")
            elif clinician.rating >= 4.0:
                reasons.append(f"Well rated ({clinician.rating:.1f}/5.0)")

        # Factor 6: Experience (10 points max)
        if clinician.total_patients_seen:
            if clinician.total_patients_seen >= 500:
                score += 10
                reasons.append("Highly experienced")
            elif clinician.total_patients_seen >= 100:
                score += 7
                reasons.append("Experienced clinician")
            elif clinician.total_patients_seen >= 20:
                score += 4
            else:
                concerns.append("Limited patient history")

        # Factor 7: Continuity of care (bonus 10 points)
        if prefs.previous_clinician_id and prefs.previous_clinician_id == clinician.clinician_id:
            score += 10
            reasons.append("Previously seen this clinician (continuity of care)")

        # Normalize score to 0.0-1.0
        max_possible_score = 100
        normalized_score = min(score / max_possible_score, 1.0)

        return normalized_score, reasons, concerns

    def _check_insurance_accepted(self, input_data: SmartSchedulingInput, clinician: ClinicianAvailability) -> bool:
        """Check if clinician accepts patient's insurance."""
        if not input_data.patient_insurance_payer_id:
            return True  # No insurance specified, assume accepted

        return input_data.patient_insurance_payer_id in clinician.accepted_insurance_payers

    def _find_best_appointment_slot(
        self,
        clinician: ClinicianAvailability,
        preferences: PatientPreferences,
        urgency_level: str,
    ) -> Optional[dict[str, Any]]:
        """Find the best appointment slot based on preferences and urgency."""
        if not clinician.available_slots:
            return None

        # Sort slots by date/time
        sorted_slots = sorted(clinician.available_slots, key=lambda s: s.get("start_time", ""))

        # For emergency/urgent, return first available
        if urgency_level in ["emergency", "urgent"]:
            return sorted_slots[0] if sorted_slots else None

        # Try to match preferences
        preferred_slots = []

        for slot in sorted_slots:
            slot_datetime = datetime.fromisoformat(slot["start_time"].replace("Z", "+00:00"))
            day_of_week = slot_datetime.strftime("%A").lower()
            hour = slot_datetime.hour

            # Determine time of day
            if hour < 12:
                time_slot = "morning"
            elif hour < 17:
                time_slot = "afternoon"
            else:
                time_slot = "evening"

            # Score this slot based on preferences
            slot_score = 0

            if day_of_week in [d.lower() for d in preferences.preferred_days]:
                slot_score += 2

            if time_slot in [t.lower() for t in preferences.preferred_time_slots]:
                slot_score += 2

            # Modality preference
            if preferences.preferred_modality:
                if slot.get("modality", "").lower() == preferences.preferred_modality.lower():
                    slot_score += 1

            preferred_slots.append((slot, slot_score))

        # Sort by preference score, then by date
        preferred_slots.sort(key=lambda x: (-x[1], x[0].get("start_time", "")))

        return preferred_slots[0][0] if preferred_slots else sorted_slots[0]

    def _generate_recommendation(self, matches: list[ClinicianMatch], input_data: SmartSchedulingInput) -> str:
        """Generate human-readable scheduling recommendation."""
        if not matches:
            return "No suitable clinicians found matching your requirements."

        top_match = matches[0]

        if top_match.match_score >= 0.8:
            quality = "excellent"
        elif top_match.match_score >= 0.6:
            quality = "good"
        else:
            quality = "moderate"

        recommendation = (
            f"Found {len(matches)} {quality} match{'es' if len(matches) > 1 else ''} for "
            f"{input_data.specialty_required}. "
        )

        if top_match.match_score >= 0.7:
            recommendation += (
                f"Top recommendation: {top_match.full_name} "
                f"(match score: {top_match.match_score:.0%}, "
                f"next available: {top_match.next_available_date})."
            )
        else:
            recommendation += (
                f"Best available: {top_match.full_name}, but consider reviewing concerns. "
                f"Next available: {top_match.next_available_date}."
            )

        return recommendation

    def _determine_no_match_reason(self, input_data: SmartSchedulingInput) -> str:
        """Determine why no matches were found."""
        reasons = []

        # Check if any clinicians match specialty
        specialty_matches = [
            c for c in input_data.available_clinicians if c.specialty.lower() == input_data.specialty_required.lower()
        ]

        if not specialty_matches:
            reasons.append(f"No clinicians available for specialty: {input_data.specialty_required}")

        # Check license state
        license_matches = [c for c in specialty_matches if input_data.patient_location_state in c.license_states]

        if specialty_matches and not license_matches:
            reasons.append(f"No clinicians licensed in {input_data.patient_location_state}")

        # Check availability
        available_matches = [c for c in license_matches if c.available_slots]

        if license_matches and not available_matches:
            reasons.append("No clinicians have available appointment slots")

        # Check urgency
        if input_data.urgency_level in ["urgent", "emergency"]:
            reasons.append(f"No clinicians meet {input_data.urgency_level} timing requirements")

        return "; ".join(reasons) if reasons else "No eligible clinicians found"

    def _calculate_scheduling_confidence(
        self, input_data: SmartSchedulingInput, matches: list[ClinicianMatch]
    ) -> float:
        """Calculate confidence in scheduling recommendations."""
        if not matches:
            return 0.0

        confidence = 0.5  # Base confidence

        # Increase for high-quality matches
        top_match_score = matches[0].match_score
        if top_match_score >= 0.8:
            confidence += 0.3
        elif top_match_score >= 0.6:
            confidence += 0.2
        elif top_match_score >= 0.4:
            confidence += 0.1

        # Increase for multiple good matches (more options)
        good_matches = [m for m in matches if m.match_score >= 0.6]
        if len(good_matches) >= 3:
            confidence += 0.15
        elif len(good_matches) >= 2:
            confidence += 0.1

        # Decrease if top match has concerns
        if matches[0].potential_concerns:
            confidence -= len(matches[0].potential_concerns) * 0.05

        # Decrease if insurance not accepted
        if not matches[0].insurance_accepted and input_data.patient_insurance_payer_id:
            confidence -= 0.15

        # Increase if urgent need is met
        if input_data.urgency_level == "urgent" and matches[0].next_available_date:
            next_date = datetime.strptime(matches[0].next_available_date, "%Y-%m-%d")
            if (next_date - datetime.now()).days <= 3:
                confidence += 0.1

        return max(0.0, min(1.0, confidence))

    def _determine_review_needed(
        self,
        output: SmartSchedulingOutput,
        confidence: float,
        input_data: SmartSchedulingInput,
    ) -> tuple[bool, Optional[str]]:
        """Determine if human review is needed."""
        # Review if no matches found
        if not output.matched_clinicians:
            return True, "No suitable clinicians found"

        # Review if confidence is low
        if confidence < 0.6:
            return True, f"Low match confidence ({confidence:.2f})"

        # Review if top match score is low
        if output.top_match_score < 0.5:
            return True, f"Low match quality ({output.top_match_score:.2f})"

        # Review if urgent/emergency and no immediate availability
        if input_data.urgency_level in ["urgent", "emergency"]:
            top_match = output.matched_clinicians[0]
            if top_match.next_available_date:
                next_date = datetime.strptime(top_match.next_available_date, "%Y-%m-%d")
                days_until = (next_date - datetime.now()).days
                if input_data.urgency_level == "emergency" and days_until > 0:
                    return True, "Emergency request but no same-day availability"
                if input_data.urgency_level == "urgent" and days_until > 3:
                    return True, "Urgent request but no availability within 3 days"

        # Review if insurance not accepted
        if output.matched_clinicians[0].insurance_accepted is False and input_data.patient_insurance_payer_id:
            return True, "Top match does not accept patient's insurance"

        # Review if many concerns
        if len(output.matched_clinicians[0].potential_concerns) >= 3:
            return True, f"{len(output.matched_clinicians[0].potential_concerns)} concerns with top match"

        return False, None
