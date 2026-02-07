from dotenv import load_dotenv

load_dotenv()

import os
from typing import Optional, Literal
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from groq import Groq
import os
import logging
import instructor
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import json
from collections import defaultdict
from datetime import datetime, timedelta

# Track operations per session
operation_tracker = defaultdict(list)
MAX_DELETES_PER_HOUR = 10
MAX_UPDATES_PER_HOUR = 20
MAX_EVENTS_PER_DELETE = 5

# Statistics tracking
session_stats = {
    "created": 0,
    "updated": 0,
    "deleted": 0,
    "listed": 0
}

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Google Calendar API scopes
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Initialize Groq client with Instructor
client = instructor.from_groq(Groq(api_key=os.getenv("GROQ_API_KEY")))
model = "llama-3.3-70b-versatile"


# Step 1: Define the data models for each stage


class EventExtraction(BaseModel):
    """First LLM call: Extract basic event information"""

    description: str = Field(description="Raw description of the event")
    is_calendar_event: bool = Field(
        description="Whether this text describes a calendar event"
    )
    confidence_score: float = Field(description="Confidence score between 0 and 1")


class EventDetails(BaseModel):
    """Second LLM call: Parse specific event details"""

    name: str = Field(description="Name of the event")
    date: str = Field(
        description="Date and time of the event. Use ISO 8601 format (YYYY-MM-DDTHH:MM:SS)."
    )
    duration_minutes: int = Field(description="Expected duration in minutes")
    participants: list[str] = Field(
        description="List of participant email addresses. If only names are given, return empty list."
    )
    location: Optional[str] = Field(
        description="Location of the event if mentioned", default=None
    )
    description: Optional[str] = Field(
        description="Additional details about the event", default=None
    )


class EventConfirmation(BaseModel):
    """Third LLM call: Generate confirmation message"""

    confirmation_message: str = Field(
        description="Natural language confirmation message"
    )
    calendar_link: Optional[str] = Field(
        description="Google Calendar event link", default=None
    )


class IntentClassification(BaseModel):
    """Router LLM call: Determine user intent"""

    intent: Literal["create", "update", "delete", "list", "invalid"] = Field(
        description="The type of calendar operation the user wants to perform"
    )
    confidence_score: float = Field(description="Confidence score between 0 and 1")
    reasoning: str = Field(
        description="Brief explanation of why this intent was chosen"
    )


class EventSearchCriteria(BaseModel):
    """Criteria to search for events to update or delete"""

    event_name_keywords: list[str] = Field(
        description="Keywords from the event name/title", default_factory=list
    )
    date_filter: Optional[str] = Field(
        description="Date or date range in ISO format (e.g., '2024-02-15' or 'tomorrow')",
        default=None,
    )
    time_filter: Optional[str] = Field(
        description="Specific time if mentioned (e.g., '2pm', '14:00')", default=None
    )


class EventUpdateRequest(BaseModel):
    """What changes the user wants to make to an event"""

    new_name: Optional[str] = Field(
        description="New event name/title if changing", default=None
    )
    new_date: Optional[str] = Field(
        description="New date/time in ISO format if rescheduling", default=None
    )
    new_duration_minutes: Optional[int] = Field(
        description="New duration in minutes if changing", default=None
    )
    new_location: Optional[str] = Field(
        description="New location if changing", default=None
    )
    add_participants: list[str] = Field(
        description="Email addresses to add as participants", default_factory=list
    )
    remove_participants: list[str] = Field(
        description="Email addresses to remove from participants", default_factory=list
    )


class DeleteConfirmation(BaseModel):
    """Safety check before deletion"""

    event_ids: list[str] = Field(description="List of event IDs to delete")
    event_summaries: list[str] = Field(
        description="Names of events being deleted (for confirmation)"
    )
    risk_level: Literal["low", "medium", "high"] = Field(
        description="Risk level: low (1 event), medium (2-3 events), high (4+ events)"
    )
    confirmation_message: str = Field(
        description="Message to show user before deleting"
    )


# Step 2: Google Calendar Authentication


def get_calendar_service():
    """Authenticate and return Google Calendar service"""
    creds = None

    # Check if credentials.json exists
    if not os.path.exists("credentials.json"):
        logger.error("❌ credentials.json not found!")
        logger.error("Please download it from Google Cloud Console:")
        logger.error("https://console.cloud.google.com/apis/credentials")
        raise FileNotFoundError("credentials.json is required")

    logger.info("Found credentials.json")

    # Token file stores user's access and refresh tokens
    if os.path.exists("token.json"):
        logger.info("Loading existing token.json")
        try:
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
            logger.info("Token loaded successfully")
        except Exception as e:
            logger.error(f"Error loading token.json: {e}")
            logger.info("Deleting invalid token.json")
            os.remove("token.json")
            creds = None

    # If no valid credentials, let user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Token expired, refreshing...")
            try:
                creds.refresh(Request())
                logger.info("Token refreshed successfully")
            except Exception as e:
                logger.error(f"Failed to refresh token: {e}")
                logger.info("Starting new OAuth flow")
                if os.path.exists("token.json"):
                    os.remove("token.json")
                creds = None

        if not creds:
            logger.info("🌐 Starting OAuth flow - browser will open for authorization")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    "credentials.json", SCOPES
                )
                creds = flow.run_local_server(port=0)
                logger.info("✅ Authentication successful!")
            except Exception as e:
                logger.error(f"❌ OAuth flow failed: {e}")
                raise

        # Save credentials for next run
        try:
            with open("token.json", "w") as token:
                token.write(creds.to_json())
            logger.info("✅ Credentials saved to token.json")
        except Exception as e:
            logger.error(f"Failed to save token: {e}")

    # Build and return the service
    try:
        service = build("calendar", "v3", credentials=creds)
        logger.info("✅ Google Calendar service initialized")
        return service
    except Exception as e:
        logger.error(f"❌ Failed to build Calendar service: {e}")
        raise


# Step 3: Create actual Google Calendar event


def create_google_calendar_event(event_details: EventDetails) -> Optional[str]:
    """Create an actual event in Google Calendar and return the event link"""
    try:
        logger.info("Initializing Google Calendar service...")
        service = get_calendar_service()

        # Parse the ISO datetime
        start_time = datetime.fromisoformat(event_details.date)
        end_time = start_time + timedelta(minutes=event_details.duration_minutes)

        # Prepare event body for Google Calendar API
        event_body = {
            "summary": event_details.name,
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "UTC",
            },
        }

        # Add location if provided
        if event_details.location:
            event_body["location"] = event_details.location

        # Add description if provided
        if event_details.description:
            event_body["description"] = event_details.description

        # Add attendees if email addresses were provided
        if event_details.participants:
            event_body["attendees"] = [
                {"email": email} for email in event_details.participants
            ]

        # Debug: Show what we're sending
        logger.debug(f"Event body: {json.dumps(event_body, indent=2)}")

        # Create the event
        logger.info(f"Creating calendar event: {event_details.name}")
        created_event = (
            service.events()
            .insert(
                calendarId="primary",
                body=event_body,
                sendUpdates="all" if event_details.participants else "none",
            )
            .execute()
        )

        event_link = created_event.get("htmlLink")
        logger.info(f"✅ Event created successfully! Link: {event_link}")

        return event_link

    except HttpError as error:
        logger.error(f"Google Calendar API error: {error}")
        logger.error(
            f"Error details: {error.error_details if hasattr(error, 'error_details') else 'No details'}"
        )
        return None
    except FileNotFoundError as error:
        logger.error(f"Setup error: {error}")
        return None
    except Exception as error:
        logger.error(f"Failed to create calendar event: {error}")
        logger.error(f"Error type: {type(error).__name__}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        return None


def list_calendar_events(
    time_min: Optional[datetime] = None,
    time_max: Optional[datetime] = None,
    max_results: int = 10,
) -> list[dict]:
    """
    List calendar events within a time range

    Args:
        time_min: Start of time range (defaults to now)
        time_max: End of time range (defaults to 30 days from now)
        max_results: Maximum number of events to return

    Returns:
        List of event dictionaries
    """
    try:
        service = get_calendar_service()

        # Default time range: now to 30 days ahead
        if time_min is None:
            time_min = datetime.utcnow()
        if time_max is None:
            time_max = time_min + timedelta(days=30)

        logger.info(f"Listing events from {time_min.date()} to {time_max.date()}")

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min.isoformat() + "Z",
                timeMax=time_max.isoformat() + "Z",
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = events_result.get("items", [])
        logger.info(f"Found {len(events)} events")

        return events

    except HttpError as error:
        logger.error(f"Google Calendar API error: {error}")
        return []
    except Exception as error:
        logger.error(f"Failed to list events: {error}")
        return []


def search_events(search_criteria: EventSearchCriteria) -> list[dict]:
    """
    Search for events matching criteria

    Args:
        search_criteria: Keywords, date filters, time filters

    Returns:
        List of matching events
    """
    logger.info("Searching for events matching criteria")
    logger.debug(f"Search criteria: {search_criteria.model_dump()}")

    # Determine time range based on date_filter
    time_min = datetime.utcnow()
    time_max = time_min + timedelta(days=30)  # Default: next 30 days

    if search_criteria.date_filter:
        # Parse relative dates
        date_str = search_criteria.date_filter.lower()
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        if date_str == "today":
            time_min = today
            time_max = today + timedelta(days=1)
        elif date_str == "tomorrow":
            time_min = today + timedelta(days=1)
            time_max = today + timedelta(days=2)
        elif date_str == "this week":
            time_min = today
            time_max = today + timedelta(days=7)
        elif date_str == "next week":
            time_min = today + timedelta(days=7)
            time_max = today + timedelta(days=14)
        else:
            # Try to parse as ISO date
            try:
                parsed_date = datetime.fromisoformat(search_criteria.date_filter)
                time_min = parsed_date.replace(hour=0, minute=0, second=0)
                time_max = time_min + timedelta(days=1)
            except:
                logger.warning(
                    f"Could not parse date filter: {search_criteria.date_filter}"
                )

    # Get events in time range
    all_events = list_calendar_events(
        time_min=time_min, time_max=time_max, max_results=50
    )

    if not all_events:
        logger.info("No events found in time range")
        return []

    # Filter by keywords if provided
    if search_criteria.event_name_keywords:
        keywords_lower = [kw.lower() for kw in search_criteria.event_name_keywords]
        filtered_events = []

        for event in all_events:
            event_summary = event.get("summary", "").lower()
            # Check if any keyword matches
            if any(keyword in event_summary for keyword in keywords_lower):
                filtered_events.append(event)

        logger.info(f"Filtered to {len(filtered_events)} events matching keywords")
        return filtered_events

    return all_events


def display_events(events: list[dict]) -> None:
    """Display events in a user-friendly format"""
    if not events:
        print("   No events found.")
        return

    print(f"\n   Found {len(events)} event(s):\n")

    for i, event in enumerate(events, 1):
        summary = event.get("summary", "Untitled Event")
        start = event.get("start", {})
        event_id = event.get("id", "unknown")

        # Parse start time
        if "dateTime" in start:
            start_time = datetime.fromisoformat(
                start["dateTime"].replace("Z", "+00:00")
            )
            time_str = start_time.strftime("%A, %B %d at %I:%M %p")
        elif "date" in start:
            time_str = start["date"]
        else:
            time_str = "Unknown time"

        # Get attendees
        attendees = event.get("attendees", [])
        attendee_str = ""
        if attendees:
            attendee_emails = [a.get("email", "") for a in attendees[:3]]
            attendee_str = f" | Attendees: {', '.join(attendee_emails)}"
            if len(attendees) > 3:
                attendee_str += f" (+{len(attendees) - 3} more)"

        print(f"   {i}. {summary}")
        print(f"      📅 {time_str}{attendee_str}")
        print(f"      🔗 ID: {event_id[:20]}...")
        print()


def update_google_calendar_event(
    event_id: str, updates: EventUpdateRequest
) -> Optional[str]:
    """Update an existing Google Calendar event"""
    try:
        service = get_calendar_service()

        # First, get the existing event
        logger.info(f"Fetching event {event_id[:20]}... for update")
        event = service.events().get(calendarId="primary", eventId=event_id).execute()

        logger.info(f"Current event: {event.get('summary')}")

        # Apply updates
        if updates.new_name:
            event["summary"] = updates.new_name
            logger.info(f"Updating name to: {updates.new_name}")

        if updates.new_date:
            # Parse new date
            new_start = datetime.fromisoformat(updates.new_date)

            # Calculate duration from existing event or use new duration
            if updates.new_duration_minutes:
                duration = updates.new_duration_minutes
            else:
                # Calculate existing duration
                old_start = datetime.fromisoformat(
                    event["start"]["dateTime"].replace("Z", "+00:00")
                )
                old_end = datetime.fromisoformat(
                    event["end"]["dateTime"].replace("Z", "+00:00")
                )
                duration = int((old_end - old_start).total_seconds() / 60)

            new_end = new_start + timedelta(minutes=duration)

            event["start"] = {"dateTime": new_start.isoformat(), "timeZone": "UTC"}
            event["end"] = {"dateTime": new_end.isoformat(), "timeZone": "UTC"}
            logger.info(f"Updating date to: {new_start}")

        elif updates.new_duration_minutes:
            # Just changing duration, keep same start time
            old_start = datetime.fromisoformat(
                event["start"]["dateTime"].replace("Z", "+00:00")
            )
            new_end = old_start + timedelta(minutes=updates.new_duration_minutes)
            event["end"] = {"dateTime": new_end.isoformat(), "timeZone": "UTC"}
            logger.info(f"Updating duration to: {updates.new_duration_minutes} minutes")

        if updates.new_location:
            event["location"] = updates.new_location
            logger.info(f"Updating location to: {updates.new_location}")

        # Handle participants
        attendees = event.get("attendees", [])

        if updates.add_participants:
            for email in updates.add_participants:
                if not any(a.get("email") == email for a in attendees):
                    attendees.append({"email": email})
            logger.info(f"Adding participants: {updates.add_participants}")

        if updates.remove_participants:
            attendees = [
                a
                for a in attendees
                if a.get("email") not in updates.remove_participants
            ]
            logger.info(f"Removing participants: {updates.remove_participants}")

        if updates.add_participants or updates.remove_participants:
            event["attendees"] = attendees

        # Update the event
        updated_event = (
            service.events()
            .update(
                calendarId="primary", eventId=event_id, body=event, sendUpdates="all"
            )
            .execute()
        )

        event_link = updated_event.get("htmlLink")
        logger.info(f"✅ Event updated successfully! Link: {event_link}")

        return event_link

    except HttpError as error:
        logger.error(f"Google Calendar API error: {error}")
        return None
    except Exception as error:
        logger.error(f"Failed to update event: {error}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        return None


def delete_google_calendar_event(event_id: str) -> bool:
    """Delete a Google Calendar event"""
    try:
        service = get_calendar_service()

        # Get event details before deleting (for logging)
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
        event_name = event.get("summary", "Untitled")

        logger.info(f"Deleting event: {event_name} (ID: {event_id[:20]}...)")

        # Delete the event
        service.events().delete(
            calendarId="primary", eventId=event_id, sendUpdates="all"
        ).execute()

        logger.info(f"✅ Event '{event_name}' deleted successfully")
        return True

    except HttpError as error:
        logger.error(f"Google Calendar API error: {error}")
        return False
    except Exception as error:
        logger.error(f"Failed to delete event: {error}")
        return False


def ask_user_confirmation(message: str) -> bool:
    """Ask user for yes/no confirmation"""
    while True:
        response = input(f"\n{message} (yes/no): ").strip().lower()
        if response in ["yes", "y"]:
            return True
        elif response in ["no", "n"]:
            return False
        else:
            print("   Please answer 'yes' or 'no'")


# Step 4: Define the LLM functions


def classify_intent(user_input: str) -> IntentClassification:
    """First step: Classify what the user wants to do"""
    logger.info("Classifying user intent")
    logger.debug(f"Input text: {user_input}")

    today = datetime.now()
    date_context = f"Today is {today.strftime('%A, %B %d, %Y')}."

    result = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": f"""{date_context}

Analyze the user's request and classify their intent into one of these categories:

1. "create" - User wants to CREATE a new calendar event
   Examples: "Schedule a meeting", "Book an appointment", "Add to my calendar"

2. "update" - User wants to MODIFY an existing event
   Examples: "Change the meeting time", "Move my appointment", "Reschedule the call"

3. "delete" - User wants to REMOVE an existing event
   Examples: "Cancel my meeting", "Delete the appointment", "Remove the event"

4. "list" - User wants to VIEW/LIST their calendar events
   Examples: "What's on my calendar?", "Show my meetings", "What do I have tomorrow?"

5. "invalid" - Request is not related to calendar operations
   Examples: "What's the weather?", "Send an email", "Search the web"

Provide high confidence (>0.8) only when the intent is very clear.
""",
            },
            {"role": "user", "content": user_input},
        ],
        response_model=IntentClassification,
    )

    logger.info(
        f"Intent classified: {result.intent} "
        f"(confidence: {result.confidence_score:.2f}) - {result.reasoning}"
    )

    return result


def extract_event_info(user_input: str) -> EventExtraction:
    """First LLM call to determine if input is a calendar event"""
    logger.info("Starting event extraction analysis")
    logger.debug(f"Input text: {user_input}")

    today = datetime.now()
    date_context = f"Today is {today.strftime('%A, %B %d, %Y')}."

    result = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": f"{date_context} Analyze if the text describes a calendar event.",
            },
            {"role": "user", "content": user_input},
        ],
        response_model=EventExtraction,
    )

    logger.info(
        f"Extraction complete - is calendar event: {result.is_calendar_event}, "
        f"Confidence: {result.confidence_score:.2f}"
    )
    return result


def parse_event_details(description: str) -> EventDetails:
    """Second LLM call to extract specific event details"""
    logger.info("Starting event details parsing")

    today = datetime.now()
    date_context = f"Today is {today.strftime('%A, %B %d, %Y')}."

    result = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": f"""{date_context} Extract detailed event information. 
                
Important rules:
- When dates reference 'next Tuesday' or similar relative dates, use the current date as reference
- For participants, ONLY include email addresses if explicitly provided. If only names are given (like 'Alice' or 'Bob'), return an empty participants list
- Use ISO 8601 format for dates (YYYY-MM-DDTHH:MM:SS)
- If no specific time is mentioned, default to 09:00:00
- If duration is not mentioned, default to 60 minutes
""",
            },
            {"role": "user", "content": description},
        ],
        response_model=EventDetails,
    )

    logger.info(
        f"Parsed event details - Name: {result.name}, DATE: {result.date}, Duration: {result.duration_minutes}min"
    )
    if result.participants:
        logger.debug(f"Participants: {', '.join(result.participants)}")
    return result


def generate_confirmation(
    event_details: EventDetails, calendar_link: Optional[str] = None
) -> EventConfirmation:
    """Third LLM call to generate a confirmation message"""
    logger.info("Generating confirmation message")

    # Include calendar link info in the prompt if available
    link_context = ""
    if calendar_link:
        link_context = (
            f"\n\nThe event has been added to Google Calendar. Link: {calendar_link}"
        )

    result = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": f"Generate a natural, friendly confirmation message for the event.{link_context}\n\nSign off with: Best regards, Preda (Calendar AI Agent)",
            },
            {"role": "user", "content": str(event_details.model_dump())},
        ],
        response_model=EventConfirmation,
    )

    # Add the calendar link to the response
    if calendar_link:
        result.calendar_link = calendar_link

    logger.info("Confirmation message generated successfully")
    return result


# Step 5: Chain the functions together


def check_rate_limit(operation: str, max_per_hour: int) -> bool:
    """Check if operation exceeds rate limit"""
    now = datetime.now()
    one_hour_ago = now - timedelta(hours=1)

    # Clean old entries
    operation_tracker[operation] = [
        timestamp
        for timestamp in operation_tracker[operation]
        if timestamp > one_hour_ago
    ]

    # Check limit
    if len(operation_tracker[operation]) >= max_per_hour:
        logger.warning(f"Rate limit exceeded for {operation}")
        return False

    # Record this operation
    operation_tracker[operation].append(now)
    return True


def llm_safety_check(user_input: str, operation: str) -> tuple[bool, str]:
    """
    LLM-based safety check to prevent malicious or dangerous operations
    Returns: (is_safe, reason)
    """
    logger.info(f"Running safety check for {operation} operation")

    class SafetyCheck(BaseModel):
        is_safe: bool = Field(description="Whether the operation is safe to perform")
        risk_level: Literal["none", "low", "medium", "high", "critical"] = Field(
            description="Risk level of the operation"
        )
        reason: str = Field(description="Explanation of the safety assessment")

    result = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": f"""You are a safety guardian for a calendar agent. Analyze if this {operation} request is safe.

REJECT (is_safe=false) if the request:
- Attempts to delete ALL events or a very large number of events
- Uses suspicious patterns like "delete everything", "cancel all", "remove all meetings"
- Seems to be testing limits or attempting abuse
- Is vague but destructive (e.g., "delete my calendar")

APPROVE (is_safe=true) if:
- Targets specific events with clear criteria
- Is a normal calendar operation
- Has reasonable scope (1-5 events)

Be strict for DELETE operations, more lenient for UPDATE and CREATE.
""",
            },
            {
                "role": "user",
                "content": f"Operation: {operation}\nRequest: {user_input}",
            },
        ],
        response_model=SafetyCheck,
    )

    logger.info(f"Safety check result: {result.is_safe} (risk: {result.risk_level})")

    return result.is_safe, result.reason


def process_calendar_request(user_input: str) -> Optional[EventConfirmation]:
    """Main function with routing logic"""
    logger.info("=" * 60)
    logger.info("Processing calendar request")
    logger.debug(f"Raw input: {user_input}")

    # STEP 1: Classify user intent (NEW!)
    intent = classify_intent(user_input)

    # Gate check: Verify confidence level
    if intent.confidence_score < 0.7:
        logger.warning(
            f"Low confidence intent classification: {intent.intent} "
            f"({intent.confidence_score:.2f})"
        )
        print(f"\n I'm not quite sure what you want to do. Could you rephrase?")
        print(f"   (I understood it as: {intent.reasoning})")
        return None

    # Route based on intent
    if intent.intent == "invalid":
        logger.info("Request is not calendar-related")
        print(f"\n This doesn't appear to be a calendar request.")
        print(f"   {intent.reasoning}")
        return None

    elif intent.intent == "list":
        logger.info("Routing to LIST operation")

        # Parse what they want to list
        result = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": f"""Extract search criteria from the user's request to list calendar events.
                    
Today is {datetime.now().strftime("%A, %B %d, %Y")}.

If they mention a timeframe, put it in date_filter (e.g., "today", "tomorrow", "this week", "next week").
If they mention specific event names or keywords, extract those.
""",
                },
                {"role": "user", "content": user_input},
            ],
            response_model=EventSearchCriteria,
        )

        logger.info(f"Searching with criteria: {result.model_dump()}")

        # Search for events
        events = search_events(result)

        # Display results
        print("\n📋 YOUR CALENDAR EVENTS:")
        display_events(events)

        return None

    elif intent.intent == "update":
        logger.info("Routing to UPDATE operation")

    # SECURITY CHECK: Rate limiting
    if not check_rate_limit("update", MAX_UPDATES_PER_HOUR):
        print(
            f"\n⏰ Rate limit exceeded. You can only update up to {MAX_UPDATES_PER_HOUR} events per hour."
        )
        print(f"Please try again later.")
        return None

        # Step 1: Extract search criteria to find the event
        search_criteria = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": f"""Extract information to identify which event the user wants to update.
                    
Today is {datetime.now().strftime("%A, %B %d, %Y")}.

Look for:
- Keywords from the event name
- Date/time references (today, tomorrow, next Tuesday, etc.)
""",
                },
                {"role": "user", "content": user_input},
            ],
            response_model=EventSearchCriteria,
        )

        # Step 2: Search for matching events
        events = search_events(search_criteria)

        if not events:
            print("\n❌ I couldn't find any matching events to update.")
            print("   Try being more specific about which event you want to change.")
            return None

        if len(events) > 1:
            print(
                f"\n⚠️  I found {len(events)} matching events. Please be more specific:"
            )
            display_events(events)
            print("   Try mentioning the exact date or more details about the event.")
            return None

        # Step 3: Found exactly one event - extract what to update
        event = events[0]
        print(f"\n✏️  Found event to update: {event.get('summary')}")

        updates = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": f"""Extract what changes the user wants to make to the event.
                    
Today is {datetime.now().strftime("%A, %B %d, %Y")}.

Current event details:
- Name: {event.get("summary")}
- Start: {event.get("start", {}).get("dateTime", "Unknown")}

Determine what they want to change:
- New name/title?
- New date/time?
- New duration?
- New location?
- Add or remove participants?
""",
                },
                {"role": "user", "content": user_input},
            ],
            response_model=EventUpdateRequest,
        )

        logger.info(f"Updates to apply: {updates.model_dump()}")

        # Step 4: Update the event
        event_id = event["id"]
        calendar_link = update_google_calendar_event(event_id, updates)

        if calendar_link:
            print(f"\n✅ Event updated successfully!")
            print(f"🔗 View in Google Calendar: {calendar_link}")
        else:
            print(f"\n❌ Failed to update the event. Please try again.")

        return None

    elif intent.intent == "delete":
        logger.info("Routing to DELETE operation")

        # SECURITY CHECK 1: LLM Guardrail
        is_safe, reason = llm_safety_check(user_input, "delete")
        if not is_safe:
            print(f"\n🛑 SECURITY ALERT: This operation was blocked for safety.")
            print(f"   Reason: {reason}")
            logger.warning(f"Blocked unsafe delete request: {reason}")
            return None

        # SECURITY CHECK 2: Rate limiting
        if not check_rate_limit("delete", MAX_DELETES_PER_HOUR):
            print(
                f"\n⏰ Rate limit exceeded. You can only delete up to {MAX_DELETES_PER_HOUR} events per hour."
            )
            print(f"   Please try again later.")
            return None

        # Step 1: Extract search criteria to find events to delete
        search_criteria = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": f"""Extract information to identify which event(s) the user wants to delete.
                
    Today is {datetime.now().strftime("%A, %B %d, %Y")}.

    Look for:
    - Keywords from the event name
    - Date/time references (today, tomorrow, next Tuesday, etc.)
    - Whether they want to delete multiple events or just one
    """,
                },
                {"role": "user", "content": user_input},
            ],
            response_model=EventSearchCriteria,
        )

        # Step 2: Search for matching events
        events = search_events(search_criteria)

        if not events:
            print("\n❌ I couldn't find any matching events to delete.")
            print("   Try being more specific about which event you want to remove.")
            return None

        # SECURITY CHECK 3: Maximum events limit
        if len(events) > MAX_EVENTS_PER_DELETE:
            print(
                f"\n🛑 SECURITY LIMIT: Found {len(events)} events, but I can only delete up to {MAX_EVENTS_PER_DELETE} at once."
            )
            print(f"   Please be more specific to target fewer events.")
            logger.warning(f"Blocked deletion of {len(events)} events (exceeds limit)")
            return None

        # Step 3: Determine risk level
        num_events = len(events)
        if num_events == 1:
            risk_level = "low"
        elif num_events <= 3:
            risk_level = "medium"
        else:
            risk_level = "high"

        # Step 4: Show what will be deleted
        print(f"\n🗑️  Found {num_events} event(s) to delete:")
        display_events(events)

        # Step 5: SECURITY CHECK - Ask for confirmation
        event_names = [e.get("summary", "Untitled") for e in events]

        if num_events == 1:
            confirmation_msg = f"⚠️  Are you sure you want to delete '{event_names[0]}'?"
        else:
            confirmation_msg = (
                f"⚠️  Are you sure you want to delete these {num_events} events?"
            )

        if not ask_user_confirmation(confirmation_msg):
            print("\n✋ Deletion cancelled. No events were removed.")
            logger.info("User cancelled deletion")
            return None

        # Step 6: Delete the events
        print("\n🔄 Deleting events...")
        deleted_count = 0
        failed_count = 0

        for event in events:
            event_id = event["id"]
            if delete_google_calendar_event(event_id):
                deleted_count += 1
            else:
                failed_count += 1

        # Step 7: Report results
        print(f"\n✅ Successfully deleted {deleted_count} event(s)")
        if failed_count > 0:
            print(f"❌ Failed to delete {failed_count} event(s)")

        logger.info(
            f"Deletion complete: {deleted_count} deleted, {failed_count} failed"
        )
        return None


# Step 6: Main execution

def main():
    """Main CLI interface"""
    print("=" * 60)
    print("🤖 Calendar AI Agent v2.0 - Advanced Calendar Management")
    print("=" * 60)
    print("\n✨ New Features:")
    print("  ✅ CREATE events")
    print("  ✏️  UPDATE existing events")
    print("  🗑️  DELETE events (with safety checks)")
    print("  📋 LIST and search your calendar")
    print("\nExamples:")
    print("  - 'Schedule a team meeting next Tuesday at 2pm'")
    print("  - 'Move my dentist appointment to Friday at 3pm'")
    print("  - 'Cancel my lunch meeting tomorrow'")
    print("  - 'What meetings do I have this week?'\n")

    while True:
        try:
            user_input = input(
                "\n📅 Enter your calendar request (or 'quit' to exit): "
            ).strip()

            if user_input.lower() in ["quit", "exit", "q"]:
                print("\n👋 Goodbye!")
                break

            if not user_input:
                print("⚠️  Please enter a request")
                continue

            print("\n🔄 Processing your request...\n")

            result = process_calendar_request(user_input)

            if result:
                print("✅ SUCCESS!\n")
                print(result.confirmation_message)
                if result.calendar_link:
                    print(f"\n🔗 View in Google Calendar: {result.calendar_link}")

        except KeyboardInterrupt:
            print("\n\n👋 Interrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ An error occurred: {str(e)}")
            logger.error(f"Unexpected error: {e}", exc_info=True)
            print("   Please try again or rephrase your request.")


if __name__ == "__main__":
    main()
