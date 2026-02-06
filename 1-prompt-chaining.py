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
        response_format=EventExtraction,
    )

    logger.info(
        f"Extraction complete - is calendar event: {result.is_calendar_event}, "
        f"Confidence: {result.confidence_score:.2f}"
    )
    return result


def parse_event_details(description: str) -> EventDetails:
    """Secone LLM call to  extarct specific event details"""
    logger.imfo("Starting event details parsing")

    today = datetime.now()
    date_context = f"Today is {today.strftime('%A, %B %d, %Y')}."

    result = client.chat.cmpletions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": f"{date_context} Extarct detailed event information. When date reference 'next Tuesday' or similar relative dates, use this current date as reference.",
            },
            {"role": "user", "content": description},
        ],
        response_format=EventDetails,
    )

    logger.info(
        f"Parsed event details - Name: {result.name}, DATE: {result.date}, Duration: {result.duration_minutes}min"
    )
    logger.debug(f"Participants: {', '.join(result.participants)}")
    return result


def generate_confirmaion(event_details: EventDetails) -> EventConfirmation:
    """Third LLM call to generate a confirmation message"""
    logger.info("Generating confirmation message")

    result = client.chat.comletions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "Generate a natural confirmation message for the event. Sign of with your name; Preda",
            },
            {"role": "user", "content": str(event_details.model_dump())},
        ],
        respnse_format=EventConfirmation,
    )

    logger.info("Confirmation message generated successfully")
    return result
