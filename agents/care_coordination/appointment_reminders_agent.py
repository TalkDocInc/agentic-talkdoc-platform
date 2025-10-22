"""
Appointment Reminders Agent

Automates sending appointment reminders via multiple channels (email, SMS, push notifications).
Includes smart timing, personalization, and patient preference handling.
"""

from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field
from structlog import get_logger

from platform_core.agent_orchestration.base_agent import BaseAgent

logger = get_logger()


# Input/Output Models


class AppointmentDetails(BaseModel):
    """Appointment information for reminders."""

    appointment_id: str
    patient_id: str
    patient_name: str
    clinician_name: str
    clinician_specialty: str
    appointment_datetime: str = Field(..., description="ISO 8601 format: YYYY-MM-DDTHH:MM:SS")
    appointment_type: str = Field(..., description="initial_visit, follow_up, therapy_session, etc.")
    modality: str = Field(..., description="in_person, telehealth, phone")
    location_address: Optional[str] = Field(None, description="For in-person appointments")
    video_link: Optional[str] = Field(None, description="For telehealth appointments")
    duration_minutes: int = Field(default=60, description="Appointment duration")
    special_instructions: Optional[str] = Field(None, description="Preparation instructions")


class PatientContactInfo(BaseModel):
    """Patient contact information and preferences."""

    patient_id: str
    email: Optional[str] = None
    phone_number: Optional[str] = None
    preferred_contact_method: str = Field(default="email", description="email, sms, both")
    preferred_language: str = Field(default="en", description="Language code")
    timezone: str = Field(default="America/New_York", description="Patient timezone")


class ReminderSchedule(BaseModel):
    """When to send reminders."""

    send_7_days_before: bool = Field(default=True, description="Send reminder 7 days before")
    send_3_days_before: bool = Field(default=True, description="Send reminder 3 days before")
    send_1_day_before: bool = Field(default=True, description="Send reminder 1 day before")
    send_2_hours_before: bool = Field(default=False, description="Send reminder 2 hours before")
    custom_hours_before: list[int] = Field(
        default_factory=list, description="Custom reminder times in hours before appointment"
    )


class AppointmentRemindersInput(BaseModel):
    """Input for appointment reminders agent."""

    appointment: AppointmentDetails
    patient_contact: PatientContactInfo
    reminder_schedule: ReminderSchedule = Field(default_factory=ReminderSchedule)
    tenant_branding: Optional[dict[str, str]] = Field(
        None, description="Tenant branding (organization_name, logo_url, etc.)"
    )
    include_cancellation_link: bool = Field(default=True, description="Include cancellation/reschedule link")
    include_preparation_checklist: bool = Field(default=True, description="Include appointment preparation info")


class ReminderMessage(BaseModel):
    """A scheduled reminder message."""

    reminder_id: str
    scheduled_send_time: str = Field(..., description="ISO 8601 timestamp when to send")
    channel: str = Field(..., description="email, sms, push")
    recipient: str = Field(..., description="Email address or phone number")
    subject: Optional[str] = Field(None, description="Email subject or SMS preview")
    message_body: str = Field(..., description="Full message content")
    message_html: Optional[str] = Field(None, description="HTML version for email")
    status: str = Field(default="scheduled", description="scheduled, sent, failed, cancelled")


class AppointmentRemindersOutput(BaseModel):
    """Output from appointment reminders agent."""

    appointment_id: str
    scheduled_reminders: list[ReminderMessage] = Field(..., description="All scheduled reminder messages")
    total_reminders_scheduled: int
    channels_used: list[str] = Field(..., description="Channels that will be used (email, sms, etc.)")
    earliest_reminder: str = Field(..., description="ISO 8601 timestamp of first reminder")
    latest_reminder: str = Field(..., description="ISO 8601 timestamp of last reminder")
    personalization_applied: bool = Field(default=True, description="Whether messages were personalized")
    confirmation_instructions: str = Field(..., description="How patient can confirm/cancel")


# Agent Implementation


class AppointmentRemindersAgent(BaseAgent[AppointmentRemindersInput, AppointmentRemindersOutput]):
    """
    Appointment Reminders Agent.

    Automates sending appointment reminders across multiple channels with smart timing
    and personalization based on appointment type and patient preferences.
    """

    def __init__(self):
        super().__init__(
            agent_type="appointment_reminders",
            agent_version="1.0.0",
            description="Automated appointment reminders with multi-channel delivery and smart timing",
        )

    async def _execute_internal(
        self,
        input_data: AppointmentRemindersInput,
        context: dict[str, Any],
    ) -> tuple[AppointmentRemindersOutput, float, dict[str, Any]]:
        """Execute appointment reminders logic."""
        start_time = datetime.now()

        # Step 1: Calculate reminder times
        reminder_times = self._calculate_reminder_times(
            input_data.appointment.appointment_datetime, input_data.reminder_schedule
        )

        # Step 2: Determine channels to use
        channels = self._determine_channels(input_data.patient_contact)

        # Step 3: Generate personalized messages for each reminder time and channel
        scheduled_reminders = []
        for reminder_time in reminder_times:
            for channel in channels:
                reminder_msg = self._generate_reminder_message(
                    reminder_time, channel, input_data, len(scheduled_reminders) + 1
                )
                scheduled_reminders.append(reminder_msg)

        # Step 4: Generate confirmation instructions
        confirmation_instructions = self._generate_confirmation_instructions(
            input_data.tenant_branding, input_data.include_cancellation_link
        )

        # Step 5: Create output
        output = AppointmentRemindersOutput(
            appointment_id=input_data.appointment.appointment_id,
            scheduled_reminders=scheduled_reminders,
            total_reminders_scheduled=len(scheduled_reminders),
            channels_used=channels,
            earliest_reminder=min(r.scheduled_send_time for r in scheduled_reminders),
            latest_reminder=max(r.scheduled_send_time for r in scheduled_reminders),
            personalization_applied=True,
            confirmation_instructions=confirmation_instructions,
        )

        # Calculate confidence
        confidence = self._calculate_reminder_confidence(input_data, scheduled_reminders, channels)

        execution_time_ms = (datetime.now() - start_time).total_seconds() * 1000

        metadata = {
            "appointment_type": input_data.appointment.appointment_type,
            "modality": input_data.appointment.modality,
            "channels": channels,
            "reminder_count": len(scheduled_reminders),
            "earliest_reminder_hours_before": self._hours_before_appointment(
                output.earliest_reminder, input_data.appointment.appointment_datetime
            ),
            "execution_time_ms": execution_time_ms,
        }

        return output, confidence, metadata

    def _calculate_reminder_times(self, appointment_datetime_str: str, schedule: ReminderSchedule) -> list[str]:
        """Calculate when to send reminders based on appointment time and schedule."""
        appointment_time = datetime.fromisoformat(appointment_datetime_str.replace("Z", "+00:00"))
        reminder_times = []

        # Standard reminders
        if schedule.send_7_days_before:
            reminder_times.append(appointment_time - timedelta(days=7))

        if schedule.send_3_days_before:
            reminder_times.append(appointment_time - timedelta(days=3))

        if schedule.send_1_day_before:
            reminder_times.append(appointment_time - timedelta(days=1))

        if schedule.send_2_hours_before:
            reminder_times.append(appointment_time - timedelta(hours=2))

        # Custom reminders
        for hours_before in schedule.custom_hours_before:
            reminder_times.append(appointment_time - timedelta(hours=hours_before))

        # Filter out past times
        now = datetime.now()
        reminder_times = [t for t in reminder_times if t > now]

        # Sort by time
        reminder_times.sort()

        # Convert to ISO format
        return [t.isoformat() for t in reminder_times]

    def _determine_channels(self, patient_contact: PatientContactInfo) -> list[str]:
        """Determine which channels to use for reminders."""
        channels = []

        pref = patient_contact.preferred_contact_method.lower()

        if pref in ["email", "both"] and patient_contact.email:
            channels.append("email")

        if pref in ["sms", "both"] and patient_contact.phone_number:
            channels.append("sms")

        # Default to email if no preference or contact info
        if not channels and patient_contact.email:
            channels.append("email")

        return channels

    def _generate_reminder_message(
        self,
        reminder_time: str,
        channel: str,
        input_data: AppointmentRemindersInput,
        reminder_number: int,
    ) -> ReminderMessage:
        """Generate a personalized reminder message."""
        apt = input_data.appointment
        contact = input_data.patient_contact

        # Calculate time until appointment
        reminder_dt = datetime.fromisoformat(reminder_time)
        apt_dt = datetime.fromisoformat(apt.appointment_datetime.replace("Z", "+00:00"))
        time_until = apt_dt - reminder_dt

        # Format appointment time
        apt_time_formatted = apt_dt.strftime("%A, %B %d, %Y at %I:%M %p")

        # Determine greeting based on time until appointment
        if time_until.days >= 7:
            greeting = "This is a friendly reminder"
            urgency = "upcoming"
        elif time_until.days >= 3:
            greeting = "Just a reminder"
            urgency = "upcoming"
        elif time_until.days >= 1:
            greeting = "Reminder: Your appointment is tomorrow"
            urgency = "soon"
        elif time_until.total_seconds() <= 7200:  # 2 hours
            greeting = "Your appointment is in 2 hours"
            urgency = "imminent"
        else:
            greeting = "Your appointment is coming up"
            urgency = "soon"

        # Build message
        if channel == "email":
            return self._generate_email_reminder(reminder_time, greeting, urgency, input_data, apt_time_formatted)
        elif channel == "sms":
            return self._generate_sms_reminder(reminder_time, greeting, urgency, input_data, apt_time_formatted)
        else:
            raise ValueError(f"Unsupported channel: {channel}")

    def _generate_email_reminder(
        self, reminder_time: str, greeting: str, urgency: str, input_data: AppointmentRemindersInput, apt_time: str
    ) -> ReminderMessage:
        """Generate email reminder."""
        apt = input_data.appointment
        contact = input_data.patient_contact
        branding = input_data.tenant_branding or {}

        org_name = branding.get("organization_name", "Your Healthcare Provider")

        # Email subject
        subject = f"Appointment Reminder - {apt.clinician_name} on {apt_time.split(' at ')[0]}"

        # Build email body
        message_body = f"""Dear {apt.patient_name},

{greeting}: You have an appointment scheduled with {apt.clinician_name} ({apt.clinician_specialty}).

**Appointment Details:**
- Date & Time: {apt_time}
- Type: {apt.appointment_type.replace('_', ' ').title()}
- Duration: {apt.duration_minutes} minutes
- Modality: {apt.modality.replace('_', ' ').title()}
"""

        # Add location or video link
        if apt.modality == "in_person" and apt.location_address:
            message_body += f"- Location: {apt.location_address}\n"
        elif apt.modality == "telehealth" and apt.video_link:
            message_body += f"- Video Link: {apt.video_link}\n"

        # Add special instructions
        if apt.special_instructions:
            message_body += f"\n**Preparation Instructions:**\n{apt.special_instructions}\n"

        # Add preparation checklist
        if input_data.include_preparation_checklist:
            checklist = self._generate_preparation_checklist(apt.appointment_type, apt.modality)
            if checklist:
                message_body += f"\n**Before Your Appointment:**\n{checklist}\n"

        # Add cancellation/reschedule info
        if input_data.include_cancellation_link:
            message_body += f"""
**Need to Reschedule or Cancel?**
Please contact us at least 24 hours in advance to avoid cancellation fees.
[Manage Appointment Link - would be actual link in production]
"""

        message_body += f"""
We look forward to seeing you!

Best regards,
{org_name}
"""

        # Simple HTML version
        message_html = message_body.replace("\n", "<br>").replace("**", "<strong>").replace("**", "</strong>")

        return ReminderMessage(
            reminder_id=f"REM-{uuid4()}",
            scheduled_send_time=reminder_time,
            channel="email",
            recipient=contact.email or "",
            subject=subject,
            message_body=message_body,
            message_html=message_html,
            status="scheduled",
        )

    def _generate_sms_reminder(
        self, reminder_time: str, greeting: str, urgency: str, input_data: AppointmentRemindersInput, apt_time: str
    ) -> ReminderMessage:
        """Generate SMS reminder (concise)."""
        apt = input_data.appointment
        contact = input_data.patient_contact

        # SMS must be concise (160 characters ideal, 320 max)
        message_body = f"{greeting}: Appointment with Dr. {apt.clinician_name.split()[-1]} on {apt_time.split(',')[1]}."

        if apt.modality == "telehealth" and apt.video_link:
            message_body += f" Video link: {apt.video_link[:50]}"
        elif apt.modality == "in_person":
            message_body += f" Location: {apt.location_address[:40] if apt.location_address else 'See email'}"

        message_body += " Reply CANCEL to cancel."

        return ReminderMessage(
            reminder_id=f"REM-{uuid4()}",
            scheduled_send_time=reminder_time,
            channel="sms",
            recipient=contact.phone_number or "",
            subject=None,
            message_body=message_body,
            status="scheduled",
        )

    def _generate_preparation_checklist(self, appointment_type: str, modality: str) -> str:
        """Generate appointment preparation checklist."""
        checklist_items = []

        # Common items
        checklist_items.append("- Have your insurance card ready")
        checklist_items.append("- Prepare a list of current medications")

        # Type-specific items
        if appointment_type == "initial_visit":
            checklist_items.append("- Bring any relevant medical records")
            checklist_items.append("- Write down questions you want to ask")
        elif appointment_type in ["therapy_session", "psychiatry"]:
            checklist_items.append("- Reflect on any changes since your last visit")
            checklist_items.append("- Note any symptoms or concerns to discuss")

        # Modality-specific items
        if modality == "telehealth":
            checklist_items.append("- Test your camera and microphone")
            checklist_items.append("- Find a quiet, private space")
            checklist_items.append("- Have a stable internet connection")
        elif modality == "in_person":
            checklist_items.append("- Plan to arrive 10-15 minutes early")
            checklist_items.append("- Bring a form of ID")

        return "\n".join(checklist_items)

    def _generate_confirmation_instructions(
        self, tenant_branding: Optional[dict[str, str]], include_link: bool
    ) -> str:
        """Generate confirmation/cancellation instructions."""
        org_name = tenant_branding.get("organization_name", "us") if tenant_branding else "us"

        instructions = f"To confirm, cancel, or reschedule your appointment, please contact {org_name}"

        if include_link:
            instructions += " via the link in your reminder emails or by replying to text messages."
        else:
            instructions += "."

        instructions += " We recommend canceling at least 24 hours in advance to avoid fees."

        return instructions

    def _hours_before_appointment(self, reminder_time_str: str, appointment_time_str: str) -> float:
        """Calculate hours before appointment."""
        reminder_time = datetime.fromisoformat(reminder_time_str.replace("Z", "+00:00"))
        appointment_time = datetime.fromisoformat(appointment_time_str.replace("Z", "+00:00"))
        delta = appointment_time - reminder_time
        return delta.total_seconds() / 3600

    def _calculate_reminder_confidence(
        self,
        input_data: AppointmentRemindersInput,
        scheduled_reminders: list[ReminderMessage],
        channels: list[str],
    ) -> float:
        """Calculate confidence in reminder delivery."""
        confidence = 0.9  # Base confidence

        # Decrease if no contact information
        if not channels:
            confidence = 0.2

        # Decrease if only SMS and no email backup
        if channels == ["sms"] and not input_data.patient_contact.email:
            confidence -= 0.2

        # Increase if using multiple channels
        if len(channels) >= 2:
            confidence += 0.05

        # Decrease if no reminders scheduled (all times in past)
        if not scheduled_reminders:
            confidence = 0.1

        # Decrease if appointment is very soon and first reminder is late
        apt_time = datetime.fromisoformat(input_data.appointment.appointment_datetime.replace("Z", "+00:00"))
        time_until_apt = (apt_time - datetime.now()).total_seconds() / 3600

        if scheduled_reminders and time_until_apt > 0:
            first_reminder_hours_before = self._hours_before_appointment(
                scheduled_reminders[0].scheduled_send_time, input_data.appointment.appointment_datetime
            )

            if time_until_apt < 24 and first_reminder_hours_before < 2:
                confidence -= 0.1  # Late notice

        return max(0.0, min(1.0, confidence))

    def _determine_review_needed(
        self,
        output: AppointmentRemindersOutput,
        confidence: float,
        input_data: AppointmentRemindersInput,
    ) -> tuple[bool, Optional[str]]:
        """Determine if human review is needed."""
        # Review if confidence is low
        if confidence < 0.5:
            return True, f"Low confidence ({confidence:.2f})"

        # Review if no reminders scheduled
        if output.total_reminders_scheduled == 0:
            return True, "No reminders could be scheduled"

        # Review if no contact channels available
        if not output.channels_used:
            return True, "No contact channels available"

        # Review if appointment is very soon and no immediate reminder
        apt_time = datetime.fromisoformat(input_data.appointment.appointment_datetime.replace("Z", "+00:00"))
        time_until_apt = (apt_time - datetime.now()).total_seconds() / 3600

        if time_until_apt < 48 and time_until_apt > 0:
            earliest_hours_before = self._hours_before_appointment(
                output.earliest_reminder, input_data.appointment.appointment_datetime
            )
            if earliest_hours_before > time_until_apt:
                return True, "Appointment soon but no timely reminder scheduled"

        return False, None
