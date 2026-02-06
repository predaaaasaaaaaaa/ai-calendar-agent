from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
from groq import Groq
import os
import logging
import instructor


# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

client = instructor.from_groq(Groq(api_key=os.getenv("GROQ_API_KEY")))
model = "llama-3.3-70b-versatile"


# Step 1: Define the data mdels for each stage


class EventExtraction(BaseModel):
    """First LLM call: Extract basic event information"""

    description: str = Field(description="Raw description of the event")
    is_calendar_event: bool = Field(
        description="Whether this text describes a calendar event"
    )
    confidence_score: float = Field(description="Confidence score between 0 and 1")


class EventDetails(BaseModel):
    """Second LLM call: Past specific event details"""

    name: str = Field(description="Name of the event")
    date: str = Field(
        description="Date and time of the event. Use ISO 8601 to format this value."
    )
    duration_minutes: int = Field(description="Expected duration in minutes")
    participants: list[str] = Field(description="List of participants")


class EventConfirmation(BaseModel):
    """Third LLM call: Generate confirmation message"""

    confirmation_message: str = Field(
        description="Natural language confirmatoin message"
    )
    calendar_link: Optional[str] = Field(
        description="Generated calendar link if applicable"
    )


# Step 2: Define the functions


def extract_event_info(user_input: str) -> EventExtraction:
    """ "First LLM call to determine if input is a calendar event"""
    logger.info("Starting event extraction analysis")
    logger.debug(f"Input text: {user_input}")

    today = datetime.now()
    date_context = f"Today is {today.strftime('%A, %B, %Y')}."

    result = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": f"{date_context} Anaslyze if the text describes a calenar event.",
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
    """Secone LLM call to  extarct specific event details"""
    logger.info("Starting event details parsing")

    today = datetime.now()
    date_context = f"Today is {today.strftime('%A, %B %d, %Y')}."

    result = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": f"{date_context} Extarct detailed event information. When date reference 'next Tuesday' or similar relative dates, use this current date as reference.",
            },
            {"role": "user", "content": description},
        ],
        response_model=EventDetails,
    )

    logger.info(
        f"Parsed event details - Name: {result.name}, DATE: {result.date}, Duration: {result.duration_minutes}min"
    )
    logger.debug(f"Participants: {', '.join(result.participants)}")
    return result


def generate_confirmaion(event_details: EventDetails) -> EventConfirmation:
    """Third LLM call to generate a confirmation message"""
    logger.info("Generating confirmation message")

    result = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "Generate a natural confirmation message for the event. Sign of with your name; Preda",
            },
            {"role": "user", "content": str(event_details.model_dump())},
        ],
        response_model=EventConfirmation,
    )

    logger.info("Confirmation message generated successfully")
    return result


# Step 3: Chain the fuctions together


def process_calendar_request(user_input: str) -> Optional[EventConfirmation]:
    """Main Function implementing the prompt chain with gate check"""
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
            f"Gate check failed - is_calendar_event: {initial_extraction.is_calendar_event}, confidence: {initial_extraction.confidence_score:.2f}"
        )
        return None

    logger.info("Gate check passed, processing with event processing")

    # Second LLM call: Get detailed event information
    event_details = parse_event_details(initial_extraction.description)

    # Third LLM call: Generate confirmation
    confirmation = generate_confirmaion(event_details)

    logger.info("Calendar request processing completed successfully")
    return confirmation


# Step 4: Test the chain with a valid input

user_input = "Let's schedule a 1h team meeting next Tuesday at 2pm with Alice and Bob to discuss the project roadmap."

result = process_calendar_request(user_input)
if result:
    print(f"Confirmation: {result.confirmation_message}")
    if result.calendar_link:
        print(f"Calendar Link: {result.calendar_link}")

    else:
        print("This doesn't appear to be a calendar event request.")


# Step 5: Test the chain with an invalid input

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
