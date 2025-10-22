"""
AI Health Advisor Agent

Conversational AI agent that provides specialty-aware health guidance to patients.
Extends TalkDoc's chat functionality to be multi-specialty and multi-tenant.

Features:
- Multi-turn conversational support
- Specialty-aware responses (mental health, primary care, etc.)
- Safety checks and escalation triggers
- Evidence-based health information
- Crisis detection and intervention
"""

import json
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


class ConversationMessage(BaseModel):
    """A single message in the conversation."""

    role: str = Field(..., description="user, assistant, or system")
    content: str = Field(..., description="Message content")
    timestamp: Optional[str] = Field(None, description="Message timestamp")


class PatientContext(BaseModel):
    """Patient context for personalized responses."""

    patient_id: str
    age: Optional[int] = None
    gender: Optional[str] = None
    primary_conditions: list[str] = Field(default_factory=list, description="Known conditions")
    current_medications: list[str] = Field(default_factory=list, description="Current medications")
    allergies: list[str] = Field(default_factory=list, description="Known allergies")
    preferred_language: str = Field(default="en", description="Preferred language code")


class AIHealthAdvisorInput(BaseModel):
    """Input for AI health advisor agent."""

    patient_context: PatientContext
    conversation_history: list[ConversationMessage] = Field(
        default_factory=list, description="Previous conversation messages"
    )
    current_message: str = Field(..., description="Patient's current message/question")
    specialty_context: str = Field(
        ..., description="Healthcare specialty context (e.g., 'mental_health', 'primary_care', 'psychiatry')"
    )
    session_id: Optional[str] = Field(None, description="Conversation session ID for tracking")
    llm_provider: str = Field(default="anthropic", description="LLM provider: anthropic or openai")
    temperature: float = Field(default=0.7, description="LLM temperature (0.0-1.0)")


class SafetyFlag(BaseModel):
    """Safety concern detected in conversation."""

    severity: str = Field(..., description="low, medium, high, critical")
    category: str = Field(..., description="Category of concern (e.g., 'suicidal_ideation', 'self_harm')")
    description: str = Field(..., description="Description of the safety concern")
    recommended_action: str = Field(..., description="Recommended action to take")


class AIHealthAdvisorOutput(BaseModel):
    """Output from AI health advisor agent."""

    response: str = Field(..., description="AI advisor's response to patient")
    conversation_id: str = Field(..., description="Unique conversation/session ID")
    safety_flags: list[SafetyFlag] = Field(default_factory=list, description="Any safety concerns detected")
    requires_clinician_review: bool = Field(default=False, description="Whether clinician review is needed")
    suggested_resources: list[str] = Field(
        default_factory=list, description="Suggested resources or self-help materials"
    )
    follow_up_questions: list[str] = Field(
        default_factory=list, description="Suggested follow-up questions for the patient"
    )
    crisis_detected: bool = Field(default=False, description="Whether a crisis situation was detected")
    crisis_resources: Optional[str] = Field(None, description="Emergency resources if crisis detected")
    sentiment: Optional[str] = Field(None, description="Detected sentiment: positive, neutral, negative, distressed")


# Agent Implementation


class AIHealthAdvisorAgent(BaseAgent[AIHealthAdvisorInput, AIHealthAdvisorOutput]):
    """
    AI Health Advisor Agent.

    Provides conversational, specialty-aware health guidance to patients using LLMs.
    Includes safety checks, crisis detection, and escalation triggers.
    """

    def __init__(self, llm_provider: str = "anthropic"):
        super().__init__(
            agent_type="ai_health_advisor",
            agent_version="1.0.0",
            description="Conversational AI health advisor with specialty-aware guidance and safety checks",
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
        input_data: AIHealthAdvisorInput,
        context: dict[str, Any],
    ) -> tuple[AIHealthAdvisorOutput, float, dict[str, Any]]:
        """Execute AI health advisor logic."""
        start_time = datetime.now()

        # Generate conversation ID if not provided
        conversation_id = input_data.session_id or f"CONV-{uuid4()}"

        # Step 1: Check for crisis keywords immediately
        crisis_detected, crisis_keywords = self._check_crisis_keywords(input_data.current_message)

        if crisis_detected:
            # Return immediate crisis response
            output = self._generate_crisis_response(conversation_id, crisis_keywords)
            return output, 0.5, {"crisis_detected": True, "crisis_keywords": crisis_keywords}

        # Step 2: Build system prompt based on specialty and patient context
        system_prompt = self._build_system_prompt(input_data)

        # Step 3: Build conversation messages
        messages = self._build_conversation_messages(input_data)

        # Step 4: Call LLM
        llm_response = await self._call_llm(system_prompt, messages, input_data.temperature)

        # Step 5: Analyze response for safety concerns
        safety_flags = self._analyze_safety_concerns(input_data.current_message, llm_response)

        # Step 6: Detect sentiment
        sentiment = self._detect_sentiment(input_data.current_message)

        # Step 7: Generate suggested resources and follow-ups
        suggested_resources = self._generate_resources(input_data.specialty_context, input_data.current_message)
        follow_up_questions = self._generate_follow_up_questions(input_data.specialty_context)

        # Step 8: Determine if clinician review is needed
        requires_review = self._requires_clinician_review(safety_flags, sentiment)

        # Step 9: Create output
        output = AIHealthAdvisorOutput(
            response=llm_response,
            conversation_id=conversation_id,
            safety_flags=safety_flags,
            requires_clinician_review=requires_review,
            suggested_resources=suggested_resources,
            follow_up_questions=follow_up_questions,
            crisis_detected=False,
            sentiment=sentiment,
        )

        # Calculate confidence
        confidence = self._calculate_advisor_confidence(input_data, llm_response, safety_flags)

        execution_time_ms = (datetime.now() - start_time).total_seconds() * 1000

        metadata = {
            "llm_provider": self.llm_provider,
            "specialty": input_data.specialty_context,
            "conversation_turns": len(input_data.conversation_history) + 1,
            "safety_flags_count": len(safety_flags),
            "sentiment": sentiment,
            "execution_time_ms": execution_time_ms,
        }

        return output, confidence, metadata

    def _check_crisis_keywords(self, message: str) -> tuple[bool, list[str]]:
        """Check for crisis keywords that require immediate intervention."""
        crisis_keywords = {
            "suicidal": ["kill myself", "end my life", "suicide", "want to die", "better off dead", "suicidal"],
            "self_harm": ["hurt myself", "cut myself", "self harm", "self-harm"],
            "violence": ["hurt someone", "kill someone", "violent thoughts"],
            "abuse": ["being abused", "someone is hurting me"],
        }

        message_lower = message.lower()
        detected_keywords = []

        for category, keywords in crisis_keywords.items():
            for keyword in keywords:
                if keyword in message_lower:
                    detected_keywords.append(f"{category}:{keyword}")

        return len(detected_keywords) > 0, detected_keywords

    def _generate_crisis_response(self, conversation_id: str, crisis_keywords: list[str]) -> AIHealthAdvisorOutput:
        """Generate immediate crisis response with resources."""
        crisis_response = (
            "I'm very concerned about what you've shared with me. Your safety is the top priority. "
            "Please reach out to a crisis counselor immediately:\n\n"
            "**Crisis Resources:**\n"
            "- **988 Suicide & Crisis Lifeline**: Call or text 988 (available 24/7)\n"
            "- **Crisis Text Line**: Text HOME to 741741\n"
            "- **Emergency Services**: Call 911 if you're in immediate danger\n\n"
            "If you'd like, I can help you connect with a clinician right away. "
            "You don't have to go through this alone."
        )

        crisis_flag = SafetyFlag(
            severity="critical",
            category="crisis_intervention",
            description=f"Crisis keywords detected: {', '.join(crisis_keywords)}",
            recommended_action="Immediate clinician contact and crisis intervention required",
        )

        return AIHealthAdvisorOutput(
            response=crisis_response,
            conversation_id=conversation_id,
            safety_flags=[crisis_flag],
            requires_clinician_review=True,
            crisis_detected=True,
            crisis_resources=(
                "988 Suicide & Crisis Lifeline (call/text 988), "
                "Crisis Text Line (text HOME to 741741), "
                "Emergency Services (911)"
            ),
            sentiment="distressed",
        )

    def _build_system_prompt(self, input_data: AIHealthAdvisorInput) -> str:
        """Build system prompt based on specialty and patient context."""
        base_prompt = (
            "You are a compassionate and knowledgeable AI health advisor. "
            "Your role is to provide evidence-based health information, emotional support, "
            "and guidance to patients in a conversational manner.\n\n"
        )

        # Add specialty-specific guidance
        specialty_guidance = self._get_specialty_guidance(input_data.specialty_context)
        base_prompt += f"**Specialty Context**: {specialty_guidance}\n\n"

        # Add patient context
        if input_data.patient_context.age:
            base_prompt += f"Patient is {input_data.patient_context.age} years old. "

        if input_data.patient_context.primary_conditions:
            base_prompt += f"Known conditions: {', '.join(input_data.patient_context.primary_conditions)}. "

        if input_data.patient_context.current_medications:
            base_prompt += f"Current medications: {', '.join(input_data.patient_context.current_medications)}. "

        base_prompt += "\n\n"

        # Add guidelines
        guidelines = (
            "**Guidelines**:\n"
            "1. Be empathetic, warm, and supportive in your responses\n"
            "2. Provide evidence-based information when possible\n"
            "3. NEVER diagnose conditions - suggest consulting a healthcare provider instead\n"
            "4. If asked about medications, provide general information but emphasize consulting their doctor\n"
            "5. For urgent symptoms, recommend seeking immediate medical attention\n"
            "6. Keep responses concise (2-4 paragraphs) and easy to understand\n"
            "7. Use simple language, avoid complex medical jargon unless necessary\n"
            "8. If uncertain, acknowledge limitations and suggest professional consultation\n"
            "9. Be culturally sensitive and respectful\n"
            "10. Focus on wellness, prevention, and self-care when appropriate\n"
        )

        base_prompt += guidelines

        return base_prompt

    def _get_specialty_guidance(self, specialty: str) -> str:
        """Get specialty-specific guidance for the system prompt."""
        specialty_prompts = {
            "mental_health": (
                "You are specialized in mental health and emotional well-being. "
                "Focus on providing emotional support, coping strategies, and mental health education. "
                "Be especially attentive to signs of crisis or severe distress."
            ),
            "psychiatry": (
                "You are specialized in psychiatry and mental health conditions. "
                "You can discuss mental health conditions, coping strategies, and general medication information, "
                "but always defer to the patient's psychiatrist for specific medical advice."
            ),
            "primary_care": (
                "You are a general health advisor covering common health concerns. "
                "Provide guidance on general wellness, common symptoms, preventive care, and when to seek medical attention."
            ),
            "pediatrics": (
                "You are specialized in child and adolescent health. "
                "Provide age-appropriate health information and guidance. Remember you're often speaking to parents/guardians."
            ),
            "cardiology": (
                "You are specialized in heart health and cardiovascular wellness. "
                "Provide information about heart-healthy lifestyle, common cardiac symptoms, and when to seek urgent care."
            ),
        }

        return specialty_prompts.get(
            specialty,
            "You provide general health information and guidance across various healthcare specialties.",
        )

    def _build_conversation_messages(self, input_data: AIHealthAdvisorInput) -> list[dict[str, str]]:
        """Build conversation messages for LLM."""
        messages = []

        # Add conversation history
        for msg in input_data.conversation_history:
            if msg.role in ["user", "assistant"]:
                messages.append({"role": msg.role, "content": msg.content})

        # Add current message
        messages.append({"role": "user", "content": input_data.current_message})

        return messages

    async def _call_llm(self, system_prompt: str, messages: list[dict[str, str]], temperature: float) -> str:
        """Call LLM to generate response."""
        try:
            if self.llm_provider == "anthropic":
                response = await self.anthropic_client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=1000,
                    temperature=temperature,
                    system=system_prompt,
                    messages=messages,
                )
                return response.content[0].text

            else:  # openai
                # Prepend system message to messages
                openai_messages = [{"role": "system", "content": system_prompt}] + messages

                response = await self.openai_client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    max_tokens=1000,
                    temperature=temperature,
                    messages=openai_messages,
                )
                return response.choices[0].message.content

        except Exception as e:
            logger.error("llm_call_error", error=str(e), provider=self.llm_provider)
            raise ValueError(f"Failed to call LLM: {str(e)}")

    def _analyze_safety_concerns(self, user_message: str, assistant_response: str) -> list[SafetyFlag]:
        """Analyze conversation for safety concerns."""
        flags = []
        message_lower = user_message.lower()

        # Check for concerning symptoms
        concerning_patterns = {
            "chest_pain": ["chest pain", "crushing chest", "heart attack"],
            "severe_headache": ["worst headache", "severe headache", "thunderclap headache"],
            "breathing_difficulty": ["can't breathe", "difficulty breathing", "shortness of breath"],
            "suicidal_thoughts": ["thoughts of suicide", "suicidal thoughts", "thinking about suicide"],
            "severe_depression": ["completely hopeless", "no reason to live", "everything is hopeless"],
            "severe_anxiety": ["panic attack", "extreme anxiety", "can't stop panicking"],
            "medication_concerns": ["overdose", "took too much", "wrong medication"],
        }

        for category, patterns in concerning_patterns.items():
            for pattern in patterns:
                if pattern in message_lower:
                    severity = self._determine_severity(category)
                    flags.append(
                        SafetyFlag(
                            severity=severity,
                            category=category,
                            description=f"Patient mentioned: '{pattern}'",
                            recommended_action=self._get_recommended_action(category, severity),
                        )
                    )
                    break  # Only flag once per category

        return flags

    def _determine_severity(self, category: str) -> str:
        """Determine severity level for a safety concern category."""
        critical_categories = ["chest_pain", "suicidal_thoughts", "medication_concerns"]
        high_categories = ["severe_headache", "breathing_difficulty", "severe_depression"]
        medium_categories = ["severe_anxiety"]

        if category in critical_categories:
            return "critical"
        elif category in high_categories:
            return "high"
        elif category in medium_categories:
            return "medium"
        else:
            return "low"

    def _get_recommended_action(self, category: str, severity: str) -> str:
        """Get recommended action for a safety concern."""
        if severity == "critical":
            return "Immediate clinician review required. Suggest patient seek emergency care."
        elif severity == "high":
            return "Urgent clinician review within 24 hours. Monitor closely."
        elif severity == "medium":
            return "Clinician review recommended within 48-72 hours."
        else:
            return "Document and mention to clinician at next appointment."

    def _detect_sentiment(self, message: str) -> str:
        """Detect sentiment from patient message."""
        message_lower = message.lower()

        # Distressed indicators
        distressed_words = ["hopeless", "desperate", "can't take it", "unbearable", "suffering", "dying"]
        if any(word in message_lower for word in distressed_words):
            return "distressed"

        # Negative indicators
        negative_words = ["sad", "depressed", "anxious", "worried", "scared", "upset", "frustrated", "angry"]
        if any(word in message_lower for word in negative_words):
            return "negative"

        # Positive indicators
        positive_words = ["better", "improving", "happy", "grateful", "thankful", "good", "great"]
        if any(word in message_lower for word in positive_words):
            return "positive"

        return "neutral"

    def _generate_resources(self, specialty: str, message: str) -> list[str]:
        """Generate relevant resource suggestions."""
        resources = []

        specialty_resources = {
            "mental_health": [
                "MindfulBreath: Guided meditation exercises",
                "Crisis Text Line: Text HOME to 741741",
                "NAMI Mental Health Support",
            ],
            "psychiatry": [
                "Medication tracking app (MyTherapy)",
                "Mental Health America resources",
                "SAMHSA National Helpline: 1-800-662-4357",
            ],
            "primary_care": [
                "CDC Health Guidelines",
                "MyChart for medical records",
                "Preventive care schedule",
            ],
        }

        return specialty_resources.get(specialty, [])[:2]  # Return top 2 resources

    def _generate_follow_up_questions(self, specialty: str) -> list[str]:
        """Generate suggested follow-up questions."""
        follow_ups = {
            "mental_health": [
                "How have you been sleeping lately?",
                "What coping strategies have you tried?",
                "Is there anyone you can talk to about this?",
            ],
            "psychiatry": [
                "How are your current medications working?",
                "Have you noticed any side effects?",
                "When is your next psychiatrist appointment?",
            ],
            "primary_care": [
                "When did your symptoms start?",
                "Have you taken any medications for this?",
                "Do you have any other symptoms?",
            ],
        }

        return follow_ups.get(specialty, [])[:2]  # Return top 2 questions

    def _requires_clinician_review(self, safety_flags: list[SafetyFlag], sentiment: str) -> bool:
        """Determine if clinician review is required."""
        if not safety_flags:
            return False

        # Critical or high severity flags require review
        for flag in safety_flags:
            if flag.severity in ["critical", "high"]:
                return True

        # Multiple medium flags require review
        medium_flags = [f for f in safety_flags if f.severity == "medium"]
        if len(medium_flags) >= 2:
            return True

        # Distressed sentiment with any flag requires review
        if sentiment == "distressed" and safety_flags:
            return True

        return False

    def _calculate_advisor_confidence(
        self, input_data: AIHealthAdvisorInput, response: str, safety_flags: list[SafetyFlag]
    ) -> float:
        """Calculate confidence in the advisor response."""
        confidence = 0.8  # Base confidence for conversational responses

        # Decrease for safety flags
        if safety_flags:
            critical_flags = [f for f in safety_flags if f.severity == "critical"]
            high_flags = [f for f in safety_flags if f.severity == "high"]

            confidence -= len(critical_flags) * 0.2
            confidence -= len(high_flags) * 0.1

        # Decrease for very short responses (might indicate uncertainty)
        if len(response) < 100:
            confidence -= 0.1

        # Decrease for long conversation history (context may be complex)
        if len(input_data.conversation_history) > 10:
            confidence -= 0.05

        return max(0.0, min(1.0, confidence))

    def _determine_review_needed(
        self,
        output: AIHealthAdvisorOutput,
        confidence: float,
        input_data: AIHealthAdvisorInput,
    ) -> tuple[bool, Optional[str]]:
        """Determine if human review is needed."""
        # Crisis always needs review
        if output.crisis_detected:
            return True, "Crisis situation detected"

        # Safety flags require review
        if output.requires_clinician_review:
            return True, f"{len(output.safety_flags)} safety concerns detected"

        # Low confidence requires review
        if confidence < 0.6:
            return True, f"Low confidence ({confidence:.2f})"

        # Distressed sentiment requires review
        if output.sentiment == "distressed":
            return True, "Patient appears distressed"

        return False, None
