from typing import Optional
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


# Step 2: Google Calendar Authentication


def get_calendar_service():
    """Authenticate and return Google Calendar service"""
    creds = None

    # Token file stores user's access and refresh tokens
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    # If no valid credentials, let user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired credentials")
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                logger.error(
                    "credentials.json not found! Please download it from Google Cloud Console."
                )
                logger.error("Visit: https://console.cloud.google.com/apis/credentials")
                raise FileNotFoundError(
                    "credentials.json is required for Google Calendar access"
                )

            logger.info("Starting OAuth flow - browser will open for authorization")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        # Save credentials for next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())
        logger.info("Credentials saved to token.json")

    return build("calendar", "v3", credentials=creds)


# Step 3: Create actual Google Calendar event


def create_google_calendar_event(event_details: EventDetails) -> Optional[str]:
    """Create an actual event in Google Calendar and return the event link"""
    try:
        service = get_calendar_service()

        # Parse the ISO datetime
        start_time = datetime.fromisoformat(event_details.date)
        end_time = start_time + timedelta(minutes=event_details.duration_minutes)

        # Prepare event body for Google Calendar API
        event_body = {
            "summary": event_details.name,
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": "UTC",  # You can make this configurable
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
        return None
    except Exception as error:
        logger.error(f"Failed to create calendar event: {error}")
        return None


# Step 4: Define the LLM functions


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


def generate_confirmation(event_details: EventDetails, calendar_link: Optional[str] = None) -> EventConfirmation:
    """Third LLM call to generate a confirmation message"""
    logger.info("Generating confirmation message")

    # Include calendar link info in the prompt if available
    link_context = ""
    if calendar_link:
        link_context = f"\n\nThe event has been added to Google Calendar. Link: {calendar_link}"

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
    """Main function implementing the prompt chain with gate check"""
    logger.info("Processing calendar request")
    logger.debug(f"Raw input: {user_input}")

    # First LLM call: Extract basic info
    initial_extraction = extract_event_info(user_input)

    # Gate check: Verify if it's a calendar event with sufficient confidence
    if (
        not initial_extraction.is_calendar_event
        or initial_extraction.confidence_score < 0.7
    ):
        logger.warning(
            f"Gate check failed - is_calendar_event: {initial_extraction.is_calendar_event}, "
            f"confidence: {initial_extraction.confidence_score:.2f}"
        )
        return None

    logger.info("Gate check passed, proceeding with event processing")

    # Second LLM call: Get detailed event information
    event_details = parse_event_details(initial_extraction.description)

    # Create the actual Google Calendar event
    calendar_link = create_google_calendar_event(event_details)

    # Third LLM call: Generate confirmation
    confirmation = generate_confirmation(event_details, calendar_link)

    logger.info("Calendar request processing completed successfully")
    return confirmation

# Step 6: Test the chain with a valid input

user_input = "Let's schedule a 1h team meeting next Tuesday at 2pm with Alice and Bob to discuss the project roadmap."

result = process_calendar_request(user_input)
if result:
    print(f"Confirmation: {result.confirmation_message}")
    if result.calendar_link:
        print(f"Calendar Link: {result.calendar_link}")

    else:
        print("This doesn't appear to be a calendar event request.")


# Step 7: Test the chain with an invalid input

user_input = (
    "Cam you send an e-mail to Alice and Bob to discuss about the project roadmap?"
)

result = process_calendar_request(user_input)
if result:
    print(f"Confirmation: {result.confirmation_message}")
    if result.calendar_link:
        print(f"Calendar Link: {result.calendar_link}")

    else:
        print("This doesn't appear to be a calendar event request.")
