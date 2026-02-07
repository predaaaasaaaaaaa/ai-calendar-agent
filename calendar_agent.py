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
        print(f"\n LIST feature coming soon!")
        print(f"   I understand you want to: {intent.reasoning}")
        return None

    elif intent.intent == "update":
        logger.info("Routing to UPDATE operation")
        print(f"\n UPDATE feature coming soon!")
        print(f"   I understand you want to: {intent.reasoning}")
        return None

    elif intent.intent == "delete":
        logger.info("Routing to DELETE operation")
        print(f"\n DELETE feature coming soon!")
        print(f"   I understand you want to: {intent.reasoning}")
        return None

    elif intent.intent == "create":
        logger.info("Routing to CREATE operation (existing flow)")

        # Original CREATE flow (unchanged)
        initial_extraction = extract_event_info(user_input)

        if (
            not initial_extraction.is_calendar_event
            or initial_extraction.confidence_score < 0.7
        ):
            logger.warning(
                f"Gate check failed - is_calendar_event: {initial_extraction.is_calendar_event}, "
                f"confidence: {initial_extraction.confidence_score:.2f}"
            )
            return None

        logger.info("Gate check passed, proceeding with event creation")

        event_details = parse_event_details(initial_extraction.description)
        calendar_link = create_google_calendar_event(event_details)
        confirmation = generate_confirmation(event_details, calendar_link)

        logger.info("Calendar request processing completed successfully")
        return confirmation

    else:
        logger.error(f"Unknown intent: {intent.intent}")
        return None


# Step 6: Main execution


def main():
    """Main CLI interface"""
    print("=" * 60)
    print("🤖 Calendar AI Agent - Natural Language Calendar Events")
    print("=" * 60)
    print("\nExamples:")
    print("  - 'Schedule a team meeting next Tuesday at 2pm for 1 hour'")
    print("  - 'Book a dentist appointment on Feb 15th at 10am'")
    print("  - 'Create a lunch meeting with john@example.com tomorrow at noon'\n")

    while True:
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
        else:
            print("❌ This doesn't appear to be a calendar event request.")
            print("   Please try rephrasing or provide more details.")


if __name__ == "__main__":
    main()
